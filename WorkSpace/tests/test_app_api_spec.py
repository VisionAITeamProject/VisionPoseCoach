import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(module_name, relative_path):
    import sys

    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_controller_payload_helpers_exist():
    module = load_module("session_controller", "core/session_controller.py")
    controller = module.SessionController.__new__(module.SessionController)

    assert hasattr(controller, "_build_session_snapshot_payload")
    assert hasattr(controller, "_build_status_payload")
    assert hasattr(controller, "_build_measurement_payload")
    assert hasattr(controller, "_build_error_payload")
    assert hasattr(controller, "_compact_latest_result")
    assert hasattr(controller, "_get_screen_hint")
