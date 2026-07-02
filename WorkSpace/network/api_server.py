import json
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from camera.camera_manager import CameraManager
from camera.vision_processor import VisionProcessor
from core.app_state import AppState
from core.calibration_manager import CalibrationManager
from core.inference_manager import InferenceManager
from core.session_controller import SessionController
from network.mjpg_streamer import MjpgStreamer


class WebSocketConnectionManager:
    def __init__(self, disconnect_callback=None):
        self._connections: set[WebSocket] = set()
        self._disconnect_callback = disconnect_callback

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        self._connections.discard(websocket)
        if self._disconnect_callback is not None:
            await self._disconnect_callback()

    async def broadcast(self, payload: dict):
        disconnected = []

        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                disconnected.append(websocket)

        for websocket in disconnected:
            await self.disconnect(websocket)


def create_app():
    app_state = AppState()
    camera_manager = CameraManager()
    vision_processor = VisionProcessor()
    calibration_manager = CalibrationManager(camera_manager, vision_processor)
    inference_manager = InferenceManager(camera_manager, vision_processor)
    mjpg_streamer = MjpgStreamer(camera_manager)
    session_controller = SessionController(
        app_state,
        None,
        camera_manager.status,
        calibration_manager,
        inference_manager,
    )
    ws_manager = WebSocketConnectionManager(disconnect_callback=session_controller.client_disconnected)
    session_controller.broadcast = ws_manager.broadcast

    app = FastAPI(title="VisionPoseCoach Server", version="0.1.0")

    @app.get("/health")
    def health():
        session_snapshot = app_state.snapshot()
        camera_status = camera_manager.status()
        vision_status = vision_processor.status()
        calibration_status = calibration_manager.status()
        inference_status = inference_manager.status()

        return {
            "type": "health",
            "ok": True,
            "app": {
                "server_ready": True,
                "device_ready": camera_status.get("using_dummy", False) is False,
                "camera_ready": camera_status.get("using_dummy", True) is False,
                "vision_ready": vision_status.get("enabled", False),
                "calibration_ready": calibration_status.get("ready", False),
                "inference_ready": inference_status.get("ready", False),
                "session_running": session_snapshot.is_running,
                "state": session_snapshot.state,
                "message": session_snapshot.message or "기기 준비됨",
            },
            "debug": {
                "camera": camera_status,
                "vision": vision_status,
                "calibration": calibration_status,
                "inference": inference_status,
                "logger": session_controller.session_logger.status(),
                "measurement_loop": session_controller.measurement_loop_status(),
            },
        }

    @app.get("/mjpg")
    def mjpg():
        return StreamingResponse(
            mjpg_streamer.frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/vision/once")
    def vision_once():
        frame = camera_manager.get_latest_frame()
        result = vision_processor.process(frame)

        return {
            "ok": result.ok,
            "pose_detected": result.pose_detected,
            "face_detected": result.face_detected,
            "pose_feature_keys": _feature_keys(result.pose_features),
            "face_feature_keys": _feature_keys(result.face_features),
            "error": result.error,
            "vision": vision_processor.status(),
            "camera": camera_manager.status(),
        }

    @app.get("/inference/once")
    def inference_once():
        return inference_manager.predict_once()

    @app.post("/calibration/test")
    async def calibration_test():
        result = await calibration_manager.run()

        return {
            "ok": result.success,
            "message": result.message,
            "pose_baseline_path": result.pose_baseline_path,
            "face_baseline_path": result.face_baseline_path,
            "valid_pose_samples": result.valid_pose_samples,
            "valid_face_samples": result.valid_face_samples,
            "error": result.error,
            "calibration": calibration_manager.status(),
        }

    @app.get("/session/status")
    def session_status():
        return session_controller.get_session_status_payload()

    @app.get("/session/latest-report")
    def session_latest_report():
        summary = session_controller.session_logger.latest_report()
        if summary is None:
            return {"ok": False, "message": "No reports available."}
        return {"ok": True, "summary": summary}

    @app.get("/session/report/{session_id}")
    def session_report(session_id: str):
        summary = session_controller.session_logger.get_summary(session_id)
        if summary is None:
            return {"ok": False, "message": "Report not found."}
        return {"ok": True, "summary": summary}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        await session_controller.client_connected()
        await websocket.send_json(session_controller._build_session_snapshot_payload())

        try:
            while True:
                message = await websocket.receive_text()
                command = _parse_command(message)
                if command is None:
                    await websocket.send_json(
                        session_controller._build_error_payload(
                            "UNKNOWN_COMMAND",
                            "알 수 없는 명령입니다.",
                            state=app_state.snapshot().state,
                        )
                    )
                    continue

                response = await session_controller.handle_command(command)
                if response is None:
                    action = command.get("action") if isinstance(command, dict) else command
                    if action not in {"start_session", "stop_session"}:
                        await websocket.send_json(
                            session_controller._build_error_payload(
                                "UNKNOWN_COMMAND",
                                "알 수 없는 명령입니다.",
                                state=app_state.snapshot().state,
                            )
                        )
                    continue

                if isinstance(response, dict) and response.get("type") == "error":
                    await websocket.send_json(response)
        except WebSocketDisconnect:
            await ws_manager.disconnect(websocket)

    @app.on_event("startup")
    def startup():
        camera_manager.start()
        vision_processor.start()

    @app.on_event("shutdown")
    async def shutdown():
        await session_controller.shutdown()
        calibration_manager.cancel()
        inference_manager.release()
        vision_processor.release()
        camera_manager.release()

    return app


def _parse_command(message: str):
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return message

    if isinstance(payload, dict):
        if payload.get("command") in {"start_session", "stop_session"}:
            return payload

        if payload.get("type") == "command" and payload.get("action") in {"start_session", "stop_session"}:
            return payload

        if payload.get("command") or payload.get("action"):
            return payload

    if isinstance(payload, str):
        return payload

    return None


def _feature_keys(features):
    if not features:
        return []

    return list(features.keys())
