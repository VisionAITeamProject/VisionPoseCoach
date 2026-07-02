import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from core.app_state import AppState, SessionStatus
from core.session_logger import SessionLogger


Broadcast = Callable[[dict], Awaitable[None]]
CameraStatusProvider = Callable[[], dict]
_KEEP_CURRENT = object()


class _SkippedCalibrationResult:
    success = True
    error = None


class SessionController:
    DEFAULT_DURATION_SEC = 1800
    MIN_DURATION_SEC = 300
    MAX_DURATION_SEC = 7200

    def __init__(
        self,
        app_state: AppState,
        broadcast: Broadcast,
        camera_status_provider: CameraStatusProvider,
        calibration_manager=None,
        inference_manager=None,
    ):
        self.app_state = app_state
        self.broadcast = broadcast
        self.camera_status_provider = camera_status_provider
        self.calibration_manager = calibration_manager
        self.inference_manager = inference_manager
        self._lock = asyncio.Lock()
        self._session_task: asyncio.Task | None = None
        self._session_created_at: datetime | None = None
        self._measuring_started_at: datetime | None = None
        self._session_end_time: datetime | None = None
        self._duration_sec: int | None = None
        self._session_id: str | None = None
        self.inference_interval_sec = 0.1
        self.emit_interval_sec = 1.0
        self.warmup_task: asyncio.Task | None = None
        self.inference_task: asyncio.Task | None = None
        self.emit_task: asyncio.Task | None = None
        self.latest_result: dict | None = None
        self.latest_result_updated_at: str | None = None
        self.inference_error_count = 0
        self.last_inference_error: str | None = None
        self.total_inference_count = 0
        self.session_logger = SessionLogger()

    async def handle_command(self, command):
        if isinstance(command, dict):
            action = command.get("action") or command.get("command")
            if action == "start_session":
                duration_sec = command.get("duration_sec")
                if self._validate_duration(duration_sec) is None:
                    return self._build_error_payload(
                        "INVALID_DURATION",
                        "측정 시간이 올바르지 않습니다.",
                        state=self.app_state.snapshot().state,
                    )
                return await self.start_session(duration_sec)
            if action == "stop_session":
                return await self.stop_session()

            return self._build_error_payload(
                "UNKNOWN_COMMAND",
                "알 수 없는 명령입니다.",
                state=self.app_state.snapshot().state,
            )

        if command == "start_session":
            return self._build_error_payload(
                "INVALID_DURATION",
                "측정 시간이 올바르지 않습니다.",
                state=self.app_state.snapshot().state,
            )

        if command == "stop_session":
            return await self.stop_session()

        return self._build_error_payload(
            "UNKNOWN_COMMAND",
            "알 수 없는 명령입니다.",
            state=self.app_state.snapshot().state,
        )

    async def start_session(self, duration_sec=None):
        async with self._lock:
            if self._session_task is not None and not self._session_task.done():
                return self._build_error_payload(
                    "SESSION_ALREADY_RUNNING",
                    "이미 측정이 진행 중입니다.",
                    state=self.app_state.snapshot().state,
                )

            duration_sec = self._normalize_duration(duration_sec)
            self._session_created_at = datetime.now(timezone.utc)
            self._measuring_started_at = None
            self._session_end_time = None
            self._duration_sec = duration_sec
            self._session_id = self._generate_session_id(self._session_created_at)
            self._reset_measurement_state()
            self._start_logging()
            self._session_task = asyncio.create_task(self._run_session())

            return await self._publish_status(
                SessionStatus.PREPARE_POSTURE,
                "정자세를 취해주세요.",
                elapsed_sec=0,
                remain_sec=duration_sec,
                session_id=self._session_id,
                session_created_at=self._session_created_at.isoformat(),
                duration_sec=duration_sec,
                session_elapsed_sec=0,
                session_remain_sec=duration_sec,
                stage_remain_sec=None,
                latest_result=None,
                stop_reason=None,
                is_running=True,
            )

    async def stop_session(self):
        task = None

        async with self._lock:
            if self._session_task is not None and not self._session_task.done():
                task = self._session_task
                task.cancel()
            else:
                return self._build_error_payload(
                    "NO_ACTIVE_SESSION",
                    "진행 중인 측정 세션이 없습니다.",
                    state=self.app_state.snapshot().state,
                )
            self._session_task = None

        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._stop_measurement_tasks()

        self._finish_logging("user_stopped")

        if self.app_state.snapshot().is_running:
            return await self._publish_status(
                SessionStatus.STOPPED,
                "측정이 중지되었습니다.",
                elapsed_sec=self._current_elapsed(),
                remain_sec=self._current_remain(),
                stop_reason="user_stopped",
                is_running=False,
            )

        return await self._publish_snapshot()

    async def client_connected(self):
        self._refresh_measurement_state()
        snapshot = self.app_state.update_client_count(
            delta=1,
            last_client_connected_at=self._iso_now(),
        )
        return snapshot

    async def client_disconnected(self):
        snapshot = self.app_state.update_client_count(
            delta=-1,
            last_client_disconnected_at=self._iso_now(),
        )
        return snapshot

    async def shutdown(self):
        await self.stop_session()

    def measurement_loop_status(self):
        status = {
            "warmup_running": self.warmup_task is not None and not self.warmup_task.done(),
            "inference_running": self.inference_task is not None and not self.inference_task.done(),
            "emit_running": self.emit_task is not None and not self.emit_task.done(),
            "inference_interval_sec": self.inference_interval_sec,
            "emit_interval_sec": self.emit_interval_sec,
            "total_inference_count": self.total_inference_count,
            "inference_error_count": self.inference_error_count,
            "last_inference_error": self.last_inference_error,
            "latest_result_updated_at": self.latest_result_updated_at,
            "logger": self.session_logger.status(),
        }
        return status

    async def _run_session(self):
        try:
            await self._run_timed_status(
                SessionStatus.WAITING_5S,
                "정자세를 유지해주세요.",
                5,
            )

            calibration_result = await self._run_calibration()
            if not calibration_result.success:
                await self._publish_status(
                    SessionStatus.ERROR,
                    "캘리브레이션에 실패했습니다.",
                    last_error=calibration_result.error,
                    is_running=False,
                )
                self._finish_logging("calibration_failed")
                return

            await self._run_warmup_phase(
                SessionStatus.INITIAL_MEASURING_30S,
                "초기 측정을 시작합니다.",
                30,
            )

            await self._run_timed_status(
                SessionStatus.COUNTDOWN_3S,
                "측정을 시작합니다.",
                3,
            )

            self._measuring_started_at = datetime.now(timezone.utc)
            self.session_logger.set_measuring_started_at(self._measuring_started_at.isoformat())
            self._session_end_time = self._measuring_started_at + timedelta(seconds=self._duration_sec or 0)

            await self._publish_status(
                SessionStatus.MEASURING,
                "측정 중입니다.",
                elapsed_sec=0,
                remain_sec=self._duration_sec,
                session_elapsed_sec=0,
                session_remain_sec=self._duration_sec,
                stage_remain_sec=None,
                measuring_started_at=self._measuring_started_at.isoformat(),
                is_running=True,
            )
            await self._run_measurement_phase()
        except asyncio.CancelledError:
            await self._stop_measurement_tasks()
            raise
        except Exception as exc:
            await self._stop_measurement_tasks()
            self._finish_logging("error")
            await self._publish_status(
                SessionStatus.ERROR,
                "측정 흐름 중 오류가 발생했습니다.",
                last_error=str(exc),
                is_running=False,
            )

    async def _run_timed_status(
        self,
        state: SessionStatus,
        message: str,
        duration_sec: int,
    ):
        for stage_elapsed in range(duration_sec):
            await self._publish_status(
                state,
                message,
                elapsed_sec=0,
                remain_sec=None,
                session_elapsed_sec=self._current_session_elapsed(),
                session_remain_sec=self._current_session_remain(),
                stage_remain_sec=max(duration_sec - stage_elapsed, 0),
                is_running=True,
            )

            await asyncio.sleep(1)

    async def _run_calibration(self):
        if self.calibration_manager is None:
            return _SkippedCalibrationResult()

        async def publish_progress(elapsed_sec, remain_sec, last_error):
            await self._publish_status(
                SessionStatus.CALIBRATING,
                "캘리브레이션 중입니다.",
                elapsed_sec=0,
                remain_sec=None,
                session_elapsed_sec=self._current_session_elapsed(),
                session_remain_sec=self._current_session_remain(),
                stage_remain_sec=remain_sec,
                last_error=last_error,
                is_running=True,
            )

        return await self.calibration_manager.run(
            progress_callback=publish_progress,
        )

    async def _run_measurement_phase(self):
        self.inference_task = asyncio.create_task(self._inference_loop())
        self.emit_task = asyncio.create_task(self._emit_loop())

        try:
            while not self._has_expired():
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            raise
        finally:
            await self._stop_measurement_tasks()

        if self._has_expired():
            await self._publish_stopped("duration_finished")
            self._finish_logging("duration_finished")

    async def _run_warmup_phase(
        self,
        state: SessionStatus,
        message: str,
        duration_sec: int,
    ):
        self.warmup_task = asyncio.create_task(self._warmup_loop(duration_sec))

        try:
            for stage_elapsed in range(duration_sec):
                await self._publish_status(
                    state,
                    message,
                    elapsed_sec=0,
                    remain_sec=None,
                    session_elapsed_sec=self._current_session_elapsed(),
                    session_remain_sec=self._current_session_remain(),
                    stage_remain_sec=max(duration_sec - stage_elapsed, 0),
                    is_running=True,
                )
                await asyncio.sleep(1)
        finally:
            if self.warmup_task is not None and not self.warmup_task.done():
                self.warmup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.warmup_task
            self.warmup_task = None

    async def _warmup_loop(self, duration_sec: int):
        end_time = asyncio.get_running_loop().time() + duration_sec
        while asyncio.get_running_loop().time() < end_time:
            try:
                raw = await asyncio.to_thread(self._run_inference_once, 0)
                latest_result = self._compact_result(raw)
                self._set_latest_result(latest_result)
                if latest_result.get("error"):
                    self.inference_error_count += 1
                    self.last_inference_error = latest_result["error"]
                else:
                    self.last_inference_error = None
                self.total_inference_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.total_inference_count += 1
                self.inference_error_count += 1
                self.last_inference_error = str(exc)
                self._set_latest_result(self._fallback_latest_result(str(exc)))
            await asyncio.sleep(self.inference_interval_sec)

    async def _inference_loop(self):
        while not self._has_expired():
            started_at = asyncio.get_running_loop().time()
            try:
                elapsed_sec = self._current_session_elapsed()
                raw = await asyncio.to_thread(self._run_inference_once, elapsed_sec)
                latest_result = self._compact_result(raw)
                self.total_inference_count += 1
                self._set_latest_result(latest_result)

                if latest_result.get("error"):
                    self.inference_error_count += 1
                    self.last_inference_error = latest_result["error"]
                else:
                    self.last_inference_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.total_inference_count += 1
                self.inference_error_count += 1
                self.last_inference_error = str(exc)
                self._set_latest_result(self._fallback_latest_result(str(exc)))

            elapsed = asyncio.get_running_loop().time() - started_at
            await asyncio.sleep(max(self.inference_interval_sec - elapsed, 0.0))

    async def _emit_loop(self):
        while not self._has_expired():
            await asyncio.sleep(self.emit_interval_sec)
            measurement = self._build_measurement_payload()
            self._update_measurement_state(measurement)
            self.session_logger.write_measurement(measurement)

            if self.app_state.snapshot().connected_clients > 0:
                await self.broadcast(measurement)

    def _run_inference_once(self, elapsed_sec):
        if self.inference_manager is None:
            return {
                "posture": {"label": "Unknown", "confidence": 0.0},
                "fatigue": {"label": "Unknown", "probability": 0.0},
                "vision": {"pose_detected": False, "face_detected": False},
                "error": "InferenceManager가 연결되지 않았습니다.",
            }

        camera_manager = getattr(self.inference_manager, "camera_manager", None)
        vision_processor = getattr(self.inference_manager, "vision_processor", None)

        if camera_manager is None or vision_processor is None:
            return self.inference_manager.predict_once(elapsed_sec=elapsed_sec)

        frame = camera_manager.get_latest_frame()
        vision_result = vision_processor.process(frame)
        return self.inference_manager.predict(vision_result, elapsed_sec=elapsed_sec)

    def _compact_result(self, raw):
        posture = raw.get("posture", {})
        fatigue = raw.get("fatigue", {})
        vision = raw.get("vision", {})

        return {
            "posture_label": posture.get("label", "Unknown"),
            "posture_confidence": float(posture.get("confidence", 0.0) or 0.0),
            "fatigue_label": fatigue.get("label", "Unknown"),
            "fatigue_probability": float(fatigue.get("probability", 0.0) or 0.0),
            "pose_detected": bool(vision.get("pose_detected", False)),
            "face_detected": bool(vision.get("face_detected", False)),
            "error": raw.get("error"),
        }

    def _fallback_latest_result(self, error):
        return {
            "posture_label": "Unknown",
            "posture_confidence": 0.0,
            "fatigue_label": "Unknown",
            "fatigue_probability": 0.0,
            "pose_detected": False,
            "face_detected": False,
            "error": error,
        }

    def _set_latest_result(self, latest_result: dict):
        self.latest_result = latest_result
        self.latest_result_updated_at = self._iso_now()
        current = self.app_state.snapshot()
        self.app_state.set_state(
            state=SessionStatus(current.state),
            message=current.message,
            elapsed_sec=current.elapsed_sec,
            remain_sec=current.remain_sec,
            camera_connected=current.camera_connected,
            last_error=current.last_error,
            session_id=current.session_id,
            session_created_at=current.session_created_at,
            measuring_started_at=current.measuring_started_at,
            duration_sec=current.duration_sec,
            session_elapsed_sec=current.session_elapsed_sec,
            session_remain_sec=current.session_remain_sec,
            stage_remain_sec=current.stage_remain_sec,
            latest_result=latest_result,
            stop_reason=current.stop_reason,
            is_running=current.is_running,
            connected_clients=current.connected_clients,
            last_client_connected_at=current.last_client_connected_at,
            last_client_disconnected_at=current.last_client_disconnected_at,
        )

    def _build_measurement_payload(self):
        latest_result = self.latest_result or self._fallback_latest_result("아직 추론 결과가 없습니다.")
        elapsed_sec = self._current_session_elapsed()
        remain_sec = self._current_session_remain()

        return {
            "type": "measurement",
            "session_id": self._session_id,
            "is_running": True,
            "state": SessionStatus.MEASURING.value,
            "screen_hint": self._get_screen_hint(SessionStatus.MEASURING),
            "elapsed_sec": elapsed_sec,
            "duration_sec": self._duration_sec,
            "remain_sec": remain_sec,
            "posture_label": latest_result.get("posture_label"),
            "posture_confidence": latest_result.get("posture_confidence"),
            "fatigue_label": latest_result.get("fatigue_label"),
            "fatigue_probability": latest_result.get("fatigue_probability"),
            "pose_detected": latest_result.get("pose_detected"),
            "face_detected": latest_result.get("face_detected"),
            "error": latest_result.get("error"),
        }

    def _update_measurement_state(self, measurement: dict):
        self.app_state.set_state(
            state=SessionStatus.MEASURING,
            message="측정 중입니다.",
            elapsed_sec=measurement["elapsed_sec"],
            remain_sec=measurement["remain_sec"],
            session_elapsed_sec=measurement["elapsed_sec"],
            session_remain_sec=measurement["remain_sec"],
            camera_connected=self._camera_connected(),
            latest_result=self.latest_result,
            is_running=True,
        )

    def _refresh_measurement_state(self):
        if self.app_state.snapshot().state != SessionStatus.MEASURING.value:
            return

        self._update_measurement_state(self._build_measurement_payload())

    def _start_logging(self):
        try:
            self.session_logger.start(
                session_id=self._session_id,
                duration_sec=self._duration_sec,
                started_at=self._session_created_at.isoformat() if self._session_created_at is not None else None,
            )
        except Exception as exc:
            self.session_logger.last_error = str(exc)

    def _finish_logging(self, stop_reason: str):
        try:
            if self.session_logger.active:
                self.session_logger.finish(stop_reason)
        except Exception as exc:
            self.session_logger.last_error = str(exc)

    async def _stop_measurement_tasks(self):
        tasks = [
            task
            for task in (self.inference_task, self.emit_task)
            if task is not None and not task.done()
        ]

        for task in tasks:
            task.cancel()

        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

        self.inference_task = None
        self.emit_task = None

    def _reset_measurement_state(self):
        self.inference_task = None
        self.emit_task = None
        self.latest_result = None
        self.latest_result_updated_at = None
        self.inference_error_count = 0
        self.last_inference_error = None
        self.total_inference_count = 0

    async def _publish_stopped(self, stop_reason: str):
        snapshot = self.app_state.set_state(
            state=SessionStatus.STOPPED,
            message=("측정이 완료되었습니다." if stop_reason == "duration_finished" else "측정이 중지되었습니다."),
            elapsed_sec=self._duration_sec if self._duration_sec is not None else self._current_session_elapsed(),
            remain_sec=0,
            session_elapsed_sec=self._duration_sec if self._duration_sec is not None else self._current_session_elapsed(),
            session_remain_sec=0,
            camera_connected=self._camera_connected(),
            stop_reason=stop_reason,
            is_running=False,
        )
        await self._broadcast(self._build_status_payload(snapshot))
        return snapshot

    async def _publish_status(
        self,
        state: SessionStatus,
        message: str,
        elapsed_sec: int = 0,
        remain_sec: int | None = None,
        last_error: str | None = None,
        session_id: str | None = None,
        session_created_at: str | None = None,
        measuring_started_at: str | None = None,
        duration_sec: int | None = None,
        session_elapsed_sec: int | None = None,
        session_remain_sec: int | None = None,
        stage_remain_sec: int | None = None,
        latest_result: dict | None | object = _KEEP_CURRENT,
        stop_reason: str | None | object = _KEEP_CURRENT,
        is_running: bool | None = None,
    ):
        current_snapshot = self.app_state.snapshot()
        snapshot = self.app_state.set_state(
            state=state,
            message=message,
            elapsed_sec=elapsed_sec,
            remain_sec=remain_sec,
            camera_connected=self._camera_connected(),
            last_error=last_error,
            session_id=session_id,
            session_created_at=session_created_at,
            measuring_started_at=measuring_started_at,
            duration_sec=duration_sec,
            session_elapsed_sec=session_elapsed_sec,
            session_remain_sec=session_remain_sec,
            stage_remain_sec=stage_remain_sec,
            latest_result=latest_result if latest_result is not _KEEP_CURRENT else current_snapshot.latest_result,
            stop_reason=stop_reason if stop_reason is not _KEEP_CURRENT else current_snapshot.stop_reason,
            is_running=is_running if is_running is not None else current_snapshot.is_running,
        )
        await self._broadcast(self._build_status_payload(snapshot))
        return snapshot

    async def _publish_snapshot(self):
        snapshot = self.app_state.snapshot()
        await self._broadcast(self._build_session_snapshot_payload(snapshot))
        return snapshot

    async def _broadcast(self, payload: dict):
        if self.broadcast is not None:
            await self.broadcast(payload)

    def _compact_latest_result(self, result: dict | None):
        if result is None:
            return None
        return {
            "posture_label": result.get("posture_label"),
            "posture_confidence": result.get("posture_confidence"),
            "fatigue_label": result.get("fatigue_label"),
            "fatigue_probability": result.get("fatigue_probability"),
            "pose_detected": result.get("pose_detected"),
            "face_detected": result.get("face_detected"),
            "error": result.get("error"),
        }

    def _get_screen_hint(self, state):
        if state is None:
            return "HOME"

        normalized_state = state.value if isinstance(state, SessionStatus) else str(state)
        mapping = {
            SessionStatus.IDLE.value: "HOME",
            SessionStatus.PREPARE_POSTURE.value: "PREPARE",
            SessionStatus.WAITING_5S.value: "PREPARE",
            SessionStatus.CALIBRATING.value: "PREPARE",
            SessionStatus.INITIAL_MEASURING_30S.value: "PREPARE",
            SessionStatus.COUNTDOWN_3S.value: "PREPARE",
            SessionStatus.MEASURING.value: "MEASUREMENT",
            SessionStatus.STOPPED.value: "RESULT",
            SessionStatus.ERROR.value: "ERROR",
        }
        return mapping.get(normalized_state, "HOME")

    def _build_session_base_payload(self, snapshot=None):
        if snapshot is None:
            snapshot = self.app_state.snapshot()
        message = snapshot.message or ("측정 대기 중입니다." if snapshot.state == SessionStatus.IDLE.value else None)
        return {
            "session_id": snapshot.session_id,
            "is_running": snapshot.is_running,
            "state": snapshot.state,
            "message": message,
            "screen_hint": self._get_screen_hint(snapshot.state),
            "stage_remain_sec": snapshot.stage_remain_sec,
            "elapsed_sec": snapshot.elapsed_sec,
            "duration_sec": snapshot.duration_sec,
            "remain_sec": snapshot.remain_sec,
            "stop_reason": snapshot.stop_reason,
            "latest_result": self._compact_latest_result(snapshot.latest_result),
        }

    def _build_session_snapshot_payload(self, snapshot=None):
        return {"type": "session_snapshot", **self._build_session_base_payload(snapshot)}

    def _build_status_payload(self, snapshot):
        return {
            "type": "status",
            "session_id": snapshot.session_id,
            "is_running": snapshot.is_running,
            "state": snapshot.state,
            "message": snapshot.message,
            "screen_hint": self._get_screen_hint(snapshot.state),
            "stage_remain_sec": snapshot.stage_remain_sec,
            "elapsed_sec": snapshot.elapsed_sec,
            "duration_sec": snapshot.duration_sec,
            "remain_sec": snapshot.remain_sec,
            "stop_reason": snapshot.stop_reason,
        }

    def _build_error_payload(self, code: str, message: str, state: str | None = None):
        if state is None:
            state = self.app_state.snapshot().state
        payload = {
            "type": "error",
            "code": code,
            "message": message,
            "state": state,
            "screen_hint": self._get_screen_hint(state),
        }
        return payload

    def _build_session_status_payload(self, snapshot=None):
        return {"type": "session_status", **self._build_session_base_payload(snapshot)}

    def get_session_status_payload(self):
        return self._build_session_status_payload()

    def _has_expired(self):
        return self._session_end_time is not None and datetime.now(timezone.utc) >= self._session_end_time

    def _current_session_elapsed(self):
        if self._measuring_started_at is None:
            return 0
        elapsed = int((datetime.now(timezone.utc) - self._measuring_started_at).total_seconds())
        if self._duration_sec is not None:
            elapsed = min(elapsed, self._duration_sec)
        return max(elapsed, 0)

    def _current_session_remain(self):
        if self._duration_sec is None:
            return None
        return max(self._duration_sec - self._current_session_elapsed(), 0)

    def _current_elapsed(self):
        return self._current_session_elapsed()

    def _current_remain(self):
        return self._current_session_remain()

    def _validate_duration(self, duration_sec):
        try:
            duration = int(duration_sec)
        except (TypeError, ValueError):
            return None

        if self.MIN_DURATION_SEC <= duration <= self.MAX_DURATION_SEC:
            return duration
        return None

    def _normalize_duration(self, duration_sec):
        validated = self._validate_duration(duration_sec)
        if validated is not None:
            return validated
        return self.DEFAULT_DURATION_SEC

    def _generate_session_id(self, timestamp: datetime):
        return timestamp.strftime("%Y-%m-%d_%H%M%S")

    def _iso_now(self):
        return datetime.now(timezone.utc).isoformat()

    def _camera_connected(self):
        status = self.camera_status_provider()
        return not status.get("using_dummy", True)
