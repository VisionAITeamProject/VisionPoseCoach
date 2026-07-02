import json

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from camera.camera_manager import CameraManager
from camera.vision_processor import VisionProcessor
from core.app_state import AppState
from core.calibration_manager import CalibrationManager
from core.inference_manager import InferenceManager
from core.session_controller import SessionController
from network.ble_provisioning_manager import BLEProvisioningManager
from network.mjpg_streamer import MjpgStreamer
from network.wifi_manager import WiFiManager


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
    wifi_manager = WiFiManager(mode="dry_run")
    ble_provisioning_manager = BLEProvisioningManager(wifi_manager, mode="dry_run")
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
    app.state.wifi_manager = wifi_manager
    app.state.ble_provisioning_manager = ble_provisioning_manager

    @app.get("/health")
    def health():
        session_snapshot = app_state.snapshot()
        camera_status = camera_manager.status()
        vision_status = vision_processor.status()
        calibration_status = calibration_manager.status()
        inference_status = inference_manager.status()
        network_status = wifi_manager.get_network_status()["wifi"]
        provisioning_status = ble_provisioning_manager.get_status()
        server_ready = True
        network_ready = True if network_status.get("mode") == "dry_run" else bool(network_status.get("connected"))
        camera_ready = camera_status.get("using_dummy", True) is False
        device_ready = server_ready and network_ready and camera_ready

        return {
            "type": "health",
            "ok": True,
            "app": {
                "server_ready": server_ready,
                "device_ready": device_ready,
                "network_ready": network_ready,
                "wifi_connected": bool(network_status.get("connected")),
                "provisioning_required": bool(network_status.get("provisioning_required")),
                "provisioning_state": provisioning_status.get("provisioning_state"),
                "ble_available": bool(provisioning_status.get("available")),
                "ble_advertising": bool(provisioning_status.get("advertising")),
                "camera_ready": camera_ready,
                "vision_ready": vision_status.get("enabled", False),
                "calibration_ready": calibration_status.get("ready", False),
                "inference_ready": inference_status.get("ready", False),
                "session_running": session_snapshot.is_running,
                "state": session_snapshot.state,
                "screen_hint": session_controller._get_screen_hint(session_snapshot.state),
                "message": session_snapshot.message or "기기 준비됨",
            },
            "debug": {
                "network": network_status,
                "provisioning": provisioning_status,
                "camera": camera_status,
                "vision": vision_status,
                "calibration": calibration_status,
                "inference": inference_status,
                "logger": session_controller.session_logger.status(),
                "measurement_loop": session_controller.measurement_loop_status(),
            },
        }

    @app.get("/network/status")
    def network_status():
        return wifi_manager.get_network_status()

    @app.get("/network/wifi/scan")
    def network_wifi_scan():
        return wifi_manager.list_networks()

    @app.post("/network/wifi/configure")
    def network_wifi_configure(payload: dict = Body(...)):
        safe_payload = wifi_manager.mask_sensitive_data(payload)
        return wifi_manager.configure_wifi(
            safe_payload.get("ssid"),
            payload.get("password"),
        )

    @app.post("/network/wifi/forget")
    def network_wifi_forget():
        return wifi_manager.forget_wifi()

    @app.get("/provisioning/status")
    def provisioning_status():
        return ble_provisioning_manager.get_registration_status()

    @app.get("/provisioning/ble/status")
    def provisioning_ble_status():
        return {
            "type": "ble_status",
            "ble": ble_provisioning_manager.get_status(),
        }

    @app.post("/provisioning/ble/start")
    def provisioning_ble_start():
        return ble_provisioning_manager.start_advertising()

    @app.post("/provisioning/ble/stop")
    def provisioning_ble_stop():
        return ble_provisioning_manager.stop_advertising()

    @app.post("/provisioning/ble/message")
    def provisioning_ble_message(payload: dict = Body(...)):
        return ble_provisioning_manager.handle_provisioning_message(payload)

    @app.post("/provisioning/ble/reset")
    def provisioning_ble_reset():
        return ble_provisioning_manager.reset_provisioning()

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
