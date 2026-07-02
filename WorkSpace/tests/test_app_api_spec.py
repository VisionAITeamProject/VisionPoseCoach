import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app_state import AppState, SessionStatus
from core.session_controller import SessionController


FORBIDDEN_APP_FIELDS = {
    "pose_features",
    "face_features",
    "landmarks",
    "blendshapes",
    "raw_frame",
    "frame",
    "image_base64",
    "condition",
    "model_raw_output",
}


def make_controller():
    return SessionController(
        AppState(),
        broadcast=None,
        camera_status_provider=lambda: {"using_dummy": False},
    )


def test_screen_hint_mapping():
    controller = make_controller()

    assert controller._get_screen_hint(SessionStatus.IDLE) == "HOME"
    assert controller._get_screen_hint(SessionStatus.PREPARE_POSTURE) == "PREPARE"
    assert controller._get_screen_hint(SessionStatus.WAITING_5S) == "PREPARE"
    assert controller._get_screen_hint(SessionStatus.CALIBRATING) == "PREPARE"
    assert controller._get_screen_hint(SessionStatus.INITIAL_MEASURING_30S) == "PREPARE"
    assert controller._get_screen_hint(SessionStatus.COUNTDOWN_3S) == "PREPARE"
    assert controller._get_screen_hint(SessionStatus.MEASURING) == "MEASUREMENT"
    assert controller._get_screen_hint(SessionStatus.STOPPED) == "RESULT"
    assert controller._get_screen_hint(SessionStatus.ERROR) == "ERROR"


def test_session_status_and_snapshot_share_shape_except_type():
    controller = make_controller()
    latest_result = {
        "posture_label": "Forward Head",
        "posture_confidence": 0.82,
        "fatigue_label": "Normal",
        "fatigue_probability": 0.21,
        "pose_detected": True,
        "face_detected": True,
        "error": None,
        "pose_features": {"hidden": True},
    }
    snapshot = controller.app_state.set_state(
        state=SessionStatus.MEASURING,
        message="측정 중입니다.",
        elapsed_sec=120,
        remain_sec=1680,
        duration_sec=1800,
        latest_result=latest_result,
        session_id="2026-06-25_102030",
        stop_reason=None,
        is_running=True,
    )

    status = controller._build_session_status_payload(snapshot)
    ws_snapshot = controller._build_session_snapshot_payload(snapshot)

    assert status["type"] == "session_status"
    assert ws_snapshot["type"] == "session_snapshot"
    assert {k: v for k, v in status.items() if k != "type"} == {
        k: v for k, v in ws_snapshot.items() if k != "type"
    }
    assert FORBIDDEN_APP_FIELDS.isdisjoint(status["latest_result"].keys())


def test_status_payload_contains_app_routing_fields():
    controller = make_controller()
    snapshot = controller.app_state.set_state(
        state=SessionStatus.WAITING_5S,
        message="정자세를 유지해주세요.",
        elapsed_sec=0,
        remain_sec=1800,
        duration_sec=1800,
        stage_remain_sec=5,
        session_id="2026-06-25_102030",
        is_running=True,
    )

    payload = controller._build_status_payload(snapshot)

    assert payload["type"] == "status"
    assert payload["is_running"] is True
    assert payload["screen_hint"] == "PREPARE"
    assert payload["stage_remain_sec"] == 5
    assert payload["remain_sec"] == 1800


def test_measurement_payload_has_no_forbidden_fields():
    controller = make_controller()
    controller._session_id = "2026-06-25_102030"
    controller._duration_sec = 1800
    controller._measuring_started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    controller.latest_result = {
        "posture_label": "Forward Head",
        "posture_confidence": 0.82,
        "fatigue_label": "Normal",
        "fatigue_probability": 0.21,
        "pose_detected": True,
        "face_detected": True,
        "error": None,
        "model_raw_output": {"hidden": True},
    }

    payload = controller._build_measurement_payload()

    assert payload["type"] == "measurement"
    assert payload["is_running"] is True
    assert payload["state"] == "MEASURING"
    assert payload["screen_hint"] == "MEASUREMENT"
    assert FORBIDDEN_APP_FIELDS.isdisjoint(payload.keys())


def test_error_payload_contains_required_fields():
    controller = make_controller()

    payload = controller._build_error_payload(
        "INVALID_DURATION",
        "측정 시간이 올바르지 않습니다.",
        state=SessionStatus.IDLE.value,
    )

    assert payload == {
        "type": "error",
        "code": "INVALID_DURATION",
        "message": "측정 시간이 올바르지 않습니다.",
        "state": "IDLE",
        "screen_hint": "HOME",
    }
