"""Model calls for every stage of the app (spec-ai-architecture §4).

  models.py    the models we may call on Vertex AI, with prices
  config.py    GCP project and region (Application Default Credentials only)
  providers.py VertexClaude, VertexGemini, NoModel, Scripted: one interface
  calls.py     Router: every call timed, priced and logged to llm_calls
  prompts/     one versioned file per prompt
  jobs.py      one entry per job: default, contender, escalate, prompt, output schema
"""

from .calls import Router, default_router, set_default_router
from .jobs import JOBS, JobResult, get_job, run_job
from .models import MODELS, get_model
from .providers import ModelError, ModelRequest, ModelResponse, ModelUnavailable, Scripted

__all__ = ["JOBS", "MODELS", "JobResult", "ModelError", "ModelRequest", "ModelResponse", "ModelUnavailable",
           "Router", "Scripted", "default_router", "get_job", "get_model", "run_job", "set_default_router"]
