"""The test suite runs offline: no model is called, whatever credentials the machine has. Tests that exercise the AI
layer hand in their own Router with scripted providers, or set the environment themselves (monkeypatch wins).

Session scope, so module-scoped fixtures that run the guided setup (test_intake, test_stress_intake) are offline too.
"""
import pytest


@pytest.fixture(autouse=True, scope="session")
def _models_off():
    from projectmodel.ai.calls import set_default_router
    from projectmodel.ai.config import load_config

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PM_AI", "off")
        load_config.cache_clear()
        set_default_router(None)
        yield
    load_config.cache_clear()
