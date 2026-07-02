from dataclasses import asdict, dataclass
from enum import Enum
from threading import Lock


class SessionStatus(str, Enum):
    IDLE = "IDLE"
    PREPARE_POSTURE = "PREPARE_POSTURE"
    WAITING_5S = "WAITING_5S"
    CALIBRATING = "CALIBRATING"
    INITIAL_MEASURING_30S = "INITIAL_MEASURING_30S"
    COUNTDOWN_3S = "COUNTDOWN_3S"
    MEASURING = "MEASURING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass
class StateSnapshot:
    session_id: str | None = None
    session_created_at: str | None = None
    measuring_started_at: str | None = None
    duration_sec: int | None = None
    session_duration_sec: int | None = None
    elapsed_sec: int = 0
    session_elapsed_sec: int = 0
    remain_sec: int | None = None
    session_remain_sec: int | None = None
    stage_remain_sec: int | None = None
    latest_result: dict | None = None
    stop_reason: str | None = None
    is_running: bool = False
    connected_clients: int = 0
    last_client_connected_at: str | None = None
    last_client_disconnected_at: str | None = None
    state: str = SessionStatus.IDLE.value
    message: str | None = None
    camera_connected: bool = False
    last_error: str | None = None


_UNSET = object()


class AppState:
    def __init__(self):
        self._lock = Lock()
        self._session_id = None
        self._session_created_at = None
        self._measuring_started_at = None
        self._duration_sec = None
        self._session_elapsed_sec = 0
        self._session_remain_sec = None
        self._stage_remain_sec = None
        self._latest_result = None
        self._stop_reason = None
        self._is_running = False
        self._connected_clients = 0
        self._last_client_connected_at = None
        self._last_client_disconnected_at = None
        self._state = SessionStatus.IDLE
        self._message = None
        self._camera_connected = False
        self._last_error = None

    def set_state(
        self,
        state: SessionStatus,
        message: str | None = None,
        elapsed_sec: int = 0,
        remain_sec: int | None = None,
        camera_connected: bool = False,
        last_error: str | None = _UNSET,
        session_id: str | None = _UNSET,
        session_created_at: str | None = _UNSET,
        measuring_started_at: str | None = _UNSET,
        duration_sec: int | None = _UNSET,
        session_elapsed_sec: int | None = _UNSET,
        session_remain_sec: int | None = _UNSET,
        stage_remain_sec: int | None = _UNSET,
        latest_result: dict | None = _UNSET,
        stop_reason: str | None = _UNSET,
        is_running: bool | None = _UNSET,
        connected_clients: int | None = _UNSET,
        last_client_connected_at: str | None = _UNSET,
        last_client_disconnected_at: str | None = _UNSET,
    ) -> StateSnapshot:
        with self._lock:
            self._state = state
            self._message = message
            self._session_elapsed_sec = elapsed_sec
            self._session_remain_sec = remain_sec
            self._stage_remain_sec = stage_remain_sec
            self._camera_connected = camera_connected

            if last_error is not _UNSET:
                self._last_error = last_error
            if session_id is not _UNSET:
                self._session_id = session_id
            if session_created_at is not _UNSET:
                self._session_created_at = session_created_at
            if measuring_started_at is not _UNSET:
                self._measuring_started_at = measuring_started_at
            if duration_sec is not _UNSET:
                self._duration_sec = duration_sec
            if session_elapsed_sec is not _UNSET:
                self._session_elapsed_sec = session_elapsed_sec
            if session_remain_sec is not _UNSET:
                self._session_remain_sec = session_remain_sec
            if latest_result is not _UNSET:
                self._latest_result = latest_result
            if stop_reason is not _UNSET:
                self._stop_reason = stop_reason
            if is_running is not _UNSET:
                self._is_running = is_running
            if connected_clients is not _UNSET:
                self._connected_clients = connected_clients
            if last_client_connected_at is not _UNSET:
                self._last_client_connected_at = last_client_connected_at
            if last_client_disconnected_at is not _UNSET:
                self._last_client_disconnected_at = last_client_disconnected_at

            return self._snapshot_locked()

    def update_client_count(
        self,
        delta: int,
        last_client_connected_at: str | None = None,
        last_client_disconnected_at: str | None = None,
    ) -> StateSnapshot:
        with self._lock:
            self._connected_clients = max(0, self._connected_clients + delta)
            if last_client_connected_at is not None:
                self._last_client_connected_at = last_client_connected_at
            if last_client_disconnected_at is not None:
                self._last_client_disconnected_at = last_client_disconnected_at
            return self._snapshot_locked()

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def as_dict(self):
        return asdict(self.snapshot())

    def _snapshot_locked(self) -> StateSnapshot:
        return StateSnapshot(
            session_id=self._session_id,
            session_created_at=self._session_created_at,
            measuring_started_at=self._measuring_started_at,
            duration_sec=self._duration_sec,
            session_duration_sec=self._duration_sec,
            elapsed_sec=self._session_elapsed_sec,
            session_elapsed_sec=self._session_elapsed_sec,
            remain_sec=self._session_remain_sec,
            session_remain_sec=self._session_remain_sec,
            stage_remain_sec=self._stage_remain_sec,
            latest_result=self._latest_result,
            stop_reason=self._stop_reason,
            is_running=self._is_running,
            connected_clients=self._connected_clients,
            last_client_connected_at=self._last_client_connected_at,
            last_client_disconnected_at=self._last_client_disconnected_at,
            state=self._state.value,
            message=self._message,
            camera_connected=self._camera_connected,
            last_error=self._last_error,
        )
