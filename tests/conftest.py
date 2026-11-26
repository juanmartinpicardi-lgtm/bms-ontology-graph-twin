"""The test suite runs offline: no model is called, whatever credentials the machine has. Tests that exercise the AI
layer hand in their own Router with scripted providers, or set the environment themselves (monkeypatch wins).
Calibration is off too (PM_CALIBRATION=off), except in test_calibration.py, and spot checks are off
(PM_SPOT_CHECK=0), except in test_spotcheck.py.

Session scope, so module-scoped fixtures that run the guided setup (test_intake, test_stress_intake) are offline too.
"""
import pytest


@pytest.fixture(autouse=True, scope="session")
def _models_off():
    from projectmodel.ai.calls import set_default_router
    from projectmodel.ai.config import load_config

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PM_AI", "off")
        # Raw confidences, as the rules and models give them: tests don't depend on the last refit. The calibrated
        # path has its own tests (test_calibration.py), which turn it on.
        mp.setenv("PM_CALIBRATION", "off")
        # No spot checks: the tests count the readers' own questions. test_spotcheck.py turns them on.
        mp.setenv("PM_SPOT_CHECK", "0")
        load_config.cache_clear()
        set_default_router(None)
        yield
    load_config.cache_clear()
