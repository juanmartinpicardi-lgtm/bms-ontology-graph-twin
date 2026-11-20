"""Where model calls go: GCP project, Vertex AI region, and whether calls are allowed at all.

Credentials are Application Default Credentials only (`gcloud auth application-default login` on a laptop, the
service account on GCP); no key is ever read from or written to the repo. The project and region are looked up, first
match wins:

  1. environment: PM_GCP_PROJECT (or GOOGLE_CLOUD_PROJECT), PM_VERTEX_REGION
  2. `.streamlit/secrets.toml`, section [ai]: project, region (the file is git-ignored)
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

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AIConfig:
    project: str | None
    region: str = "global"
    enabled: bool = True
    regions: dict[str, str] = field(default_factory=dict)  # per model family override, e.g. {"gemini": "us-central1"}
    why_off: str = ""

    def region_for(self, family: str) -> str:
        return self.regions.get(family, self.region)

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.project)


def _secrets() -> dict:
    path = ROOT / ".streamlit" / "secrets.toml"
    try:
        return tomllib.loads(path.read_text()).get("ai", {}) if path.exists() else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}


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
    project = (os.environ.get("PM_GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or sec.get("project")
               or _gcloud_project() or _adc_project())
    region = os.environ.get("PM_VERTEX_REGION") or sec.get("region") or "global"
    regions = dict(sec.get("regions", {}))
    if g := os.environ.get("PM_VERTEX_REGION_GEMINI"):
        regions["gemini"] = g
    if not project:
        return AIConfig(project=None, region=region, enabled=False,
                        why_off="no GCP project: set PM_GCP_PROJECT or run `gcloud config set project …`")
    return AIConfig(project=project, region=region, regions=regions)
