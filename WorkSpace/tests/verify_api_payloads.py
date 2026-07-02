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


def main():
    controller = make_controller()

    expected_hints = {
        SessionStatus.IDLE: "HOME",
        SessionStatus.PREPARE_POSTURE: "PREPARE",
        SessionStatus.WAITING_5S: "PREPARE",
        SessionStatus.CALIBRATING: "PREPARE",
        SessionStatus.INITIAL_MEASURING_30S: "PREPARE",
        SessionStatus.COUNTDOWN_3S: "PREPARE",
        SessionStatus.MEASURING: "MEASUREMENT",
        SessionStatus.STOPPED: "RESULT",
        SessionStatus.ERROR: "ERROR",
    }
    for state, screen_hint in expected_hints.items():
        assert controller._get_screen_hint(state) == screen_hint

    snapshot = controller.app_state.set_state(
        state=SessionStatus.MEASURING,
        message="측정 중입니다.",
        elapsed_sec=120,
        remain_sec=1680,
        duration_sec=1800,
        session_id="2026-06-25_102030",
        latest_result={
            "posture_label": "Forward Head",
            "posture_confidence": 0.82,
            "fatigue_label": "Normal",
            "fatigue_probability": 0.21,
            "pose_detected": True,
            "face_detected": True,
            "error": None,
            "pose_features": {"hidden": True},
        },
        is_running=True,
    )
    status = controller._build_session_status_payload(snapshot)
    ws_snapshot = controller._build_session_snapshot_payload(snapshot)
    assert {k: v for k, v in status.items() if k != "type"} == {
        k: v for k, v in ws_snapshot.items() if k != "type"
    }

    controller._session_id = "2026-06-25_102030"
    controller._duration_sec = 1800
    controller._measuring_started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    controller.latest_result = snapshot.latest_result
    measurement = controller._build_measurement_payload()
    assert FORBIDDEN_APP_FIELDS.isdisjoint(measurement.keys())

    error = controller._build_error_payload("INVALID_DURATION", "측정 시간이 올바르지 않습니다.")
    assert {"code", "message", "state", "screen_hint"}.issubset(error.keys())

    print("api_payloads_ok")


if __name__ == "__main__":
    main()
