"""Where model calls go: GCP project, Vertex AI region, and whether calls are allowed at all.

Credentials: Application Default Credentials (`gcloud auth application-default login` on a laptop, the attached
service account on GCP), or, where there is no ADC (Streamlit Community Cloud), a service account key kept in the
app's secrets, section [ai.service_account] (the fields of the key's JSON file). No key is ever in the repo.

The project and region are looked up, first match wins:

  1. environment: PM_GCP_PROJECT (or GOOGLE_CLOUD_PROJECT), PM_VERTEX_REGION
  2. the app's secrets, section [ai]: project, region (Streamlit's secrets store; locally `.streamlit/secrets.toml`,
     which is git-ignored); else the service account's own project
  3. the active gcloud configuration (`gcloud config get-value project`)
  4. the project ADC itself names

Region defaults to `global`, which Vertex AI recommends for Claude and also serves Gemini. `PM_AI=off` turns every
model call off (the app then runs on rules only, as before).
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AIConfig:
    project: str | None
    region: str = "global"
    enabled: bool = True
    regions: dict[str, str] = field(default_factory=dict)  # per model family override, e.g. {"gemini": "us-central1"}
    why_off: str = ""
    credentials: Any = field(default=None, compare=False, repr=False)  # None: Application Default Credentials

    def region_for(self, family: str) -> str:
        return self.regions.get(family, self.region)

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.project)


def _plain(value: Any) -> Any:
    if hasattr(value, "items"):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _secrets() -> dict:
    """Section [ai] of the app's secrets: Streamlit's store when the app runs in Streamlit (on Cloud too), else the
    repo's `.streamlit/secrets.toml`."""
    try:
        import streamlit as st
        from streamlit.runtime import exists

        if exists():
            return _plain(st.secrets.get("ai", {}))
    except Exception:  # noqa: BLE001 - no secrets at all is a normal state
        pass
    path = ROOT / ".streamlit" / "secrets.toml"
    try:
        return tomllib.loads(path.read_text()).get("ai", {}) if path.exists() else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _service_account(info: dict | None) -> Any:
    """Credentials from a service account key's fields, scoped for Vertex AI."""
    if not info:
        return None
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"])


def _gcloud_project() -> str | None:
    exe = shutil.which("gcloud")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "config", "get-value", "project"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = out.stdout.strip()
    return value if value and value != "(unset)" else None


def _adc_project() -> str | None:
    try:
        import google.auth

        return google.auth.default()[1]
    except Exception:  # noqa: BLE001 - no ADC at all is a normal state, not an error
        return None


@functools.cache
def load_config() -> AIConfig:
    if os.environ.get("PM_AI", "").lower() in ("off", "0", "false", "none"):
        return AIConfig(project=None, enabled=False, why_off="PM_AI=off")
    sec = _secrets()
    key = sec.get("service_account") or None
    try:
        credentials = _service_account(key)
    except (ValueError, KeyError) as e:
        return AIConfig(project=None, enabled=False, why_off=f"the service account key in the app's secrets is not "
                                                              f"valid: {e}")
    project = (os.environ.get("PM_GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or sec.get("project")
               or (key or {}).get("project_id") or _gcloud_project() or _adc_project())
    region = os.environ.get("PM_VERTEX_REGION") or sec.get("region") or "global"
    regions = dict(sec.get("regions", {}))
    if g := os.environ.get("PM_VERTEX_REGION_GEMINI"):
        regions["gemini"] = g
    if not project:
        return AIConfig(project=None, region=region, enabled=False,
                        why_off="no GCP project: set PM_GCP_PROJECT or run `gcloud config set project …`")
    return AIConfig(project=project, region=region, regions=regions, credentials=credentials)
