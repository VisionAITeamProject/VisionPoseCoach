import asyncio
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from camera.vision_processor import FACE_FEATURE_NAMES
from modules.features import FEATURE_NAMES


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_PATH = "saved_model/baseline.pkl"
DEFAULT_FACE_BASELINE_PATH = "saved_model/baseline_face.pkl"
DEFAULT_CALIBRATION_TIME = 5
COLLECT_INTERVAL_SEC = 0.1

ProgressCallback = Callable[[int, int, str | None], Awaitable[None]]


@dataclass
class CalibrationRunResult:
    success: bool
    message: str
    pose_baseline_path: str
    face_baseline_path: str
    valid_pose_samples: int
    valid_face_samples: int
    error: str | None = None


class CalibrationManager:
    def __init__(
        self,
        camera_manager,
        vision_processor,
        duration_sec: int | None = None,
    ):
        self.camera_manager = camera_manager
        self.vision_processor = vision_processor
        self.duration_sec = int(
            duration_sec
            if duration_sec is not None
            else self._config_value("CALIBRATION_TIME", DEFAULT_CALIBRATION_TIME)
        )
        self.pose_baseline_path = self._resolve_workspace_path(
            self._config_value("BASELINE_PATH", DEFAULT_BASELINE_PATH)
        )
        self.face_baseline_path = self._resolve_workspace_path(
            self._config_value("FACE_BASELINE_PATH", DEFAULT_FACE_BASELINE_PATH)
        )

        calibration_service = self._load_calibration_service()
        self._calibration_service_class = calibration_service.CalibrationService
        self._pose_service = None
        self._face_service = None
        self._running = False
        self._last_success = None
        self._valid_pose_samples = 0
        self._valid_face_samples = 0
        self._last_error = None

    def reset(self):
        if self._pose_service is not None:
            self._pose_service.cancel()

        if self._face_service is not None:
            self._face_service.cancel()

        self._pose_service = self._new_service(self.pose_baseline_path)
        self._face_service = self._new_service(self.face_baseline_path)
        self._valid_pose_samples = 0
        self._valid_face_samples = 0
        self._last_error = None

    async def run(
        self,
        duration_sec: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> CalibrationRunResult:
        if self._running:
            return self._failure("캘리브레이션이 이미 진행 중입니다.")

        duration = int(duration_sec or self.duration_sec)
        self.duration_sec = duration
        self.reset()
        self._running = True
        self._pose_service.start()
        self._face_service.start()
        last_progress_elapsed = -1

        try:
            loop = asyncio.get_running_loop()
            started_at = loop.time()

            while True:
                elapsed = loop.time() - started_at
                elapsed_sec = min(int(elapsed), duration)
                remain_sec = max(duration - elapsed_sec, 0)

                if progress_callback is not None and elapsed_sec != last_progress_elapsed:
                    await progress_callback(elapsed_sec, remain_sec, None)
                    last_progress_elapsed = elapsed_sec

                self.collect_once()

                if elapsed >= duration:
                    break

                await asyncio.sleep(COLLECT_INTERVAL_SEC)

            pose_result = self._pose_service.finish()
            face_result = self._face_service.finish()

            success = (
                pose_result.success
                and face_result.success
                and self._valid_pose_samples > 0
                and self._valid_face_samples > 0
            )

            if not success:
                error = self._build_failure_message(pose_result, face_result)
                self._last_success = False
                self._last_error = error
                return CalibrationRunResult(
                    success=False,
                    message="캘리브레이션에 실패했습니다.",
                    pose_baseline_path=str(self.pose_baseline_path),
                    face_baseline_path=str(self.face_baseline_path),
                    valid_pose_samples=self._valid_pose_samples,
                    valid_face_samples=self._valid_face_samples,
                    error=error,
                )

            self._last_success = True
            self._last_error = None
            return CalibrationRunResult(
                success=True,
                message="캘리브레이션이 완료되었습니다.",
                pose_baseline_path=str(self.pose_baseline_path),
                face_baseline_path=str(self.face_baseline_path),
                valid_pose_samples=self._valid_pose_samples,
                valid_face_samples=self._valid_face_samples,
                error=None,
            )

        except asyncio.CancelledError:
            self.cancel()
            raise
        except Exception as exc:
            self._last_success = False
            self._last_error = str(exc)
            return self._failure(str(exc))
        finally:
            self._running = False

    def collect_once(self):
        frame = self.camera_manager.get_latest_frame()
        vision_result = self.vision_processor.process(frame)

        if not vision_result.ok:
            self._last_error = vision_result.error
            return vision_result

        pose_values = self._feature_values(vision_result.pose_features, FEATURE_NAMES)
        if pose_values is not None:
            pose_result = self._pose_service.update(pose_values)
            self._valid_pose_samples = max(
                self._valid_pose_samples,
                pose_result.sample_count,
            )

        face_values = self._feature_values(vision_result.face_features, FACE_FEATURE_NAMES)
        if face_values is not None:
            face_result = self._face_service.update(face_values)
            self._valid_face_samples = max(
                self._valid_face_samples,
                face_result.sample_count,
            )

        return vision_result

    def cancel(self):
        if self._pose_service is not None:
            self._pose_service.cancel()

        if self._face_service is not None:
            self._face_service.cancel()

        self._running = False

    def status(self):
        return {
            "ready": self._calibration_service_class is not None,
            "running": self._running,
            "last_success": self._last_success,
            "valid_pose_samples": self._valid_pose_samples,
            "valid_face_samples": self._valid_face_samples,
            "pose_baseline_path": str(self.pose_baseline_path),
            "face_baseline_path": str(self.face_baseline_path),
            "last_error": self._last_error,
        }

    def _new_service(self, baseline_path):
        return self._calibration_service_class(
            baseline_path=baseline_path,
            duration=self.duration_sec,
        )

    def _failure(self, error):
        self._last_success = False
        self._last_error = error
        return CalibrationRunResult(
            success=False,
            message="캘리브레이션에 실패했습니다.",
            pose_baseline_path=str(self.pose_baseline_path),
            face_baseline_path=str(self.face_baseline_path),
            valid_pose_samples=self._valid_pose_samples,
            valid_face_samples=self._valid_face_samples,
            error=error,
        )

    def _build_failure_message(self, pose_result, face_result):
        messages = []

        if self._valid_pose_samples <= 0:
            messages.append("유효한 pose feature가 수집되지 않았습니다.")
        elif not pose_result.success:
            messages.append(pose_result.message)

        if self._valid_face_samples <= 0:
            messages.append("유효한 face feature가 수집되지 않았습니다.")
        elif not face_result.success:
            messages.append(face_result.message)

        return " ".join(messages) or "유효한 feature가 수집되지 않았습니다."

    def _feature_values(self, features, feature_names):
        if not features:
            return None

        values = []
        for name in feature_names:
            if name not in features:
                return None
            values.append(float(features[name]))

        return values

    def _resolve_workspace_path(self, path_text):
        path = Path(path_text)

        if path.is_absolute():
            return path

        return ROOT_DIR / path

    def _config_value(self, name, default):
        try:
            import modules.config as config

            return getattr(config, name, default)
        except Exception:
            return default

    def _load_calibration_service(self):
        service_path = ROOT_DIR / "pyQt" / "services" / "calibration_service.py"
        spec = importlib.util.spec_from_file_location(
            "server_reused_calibration_service",
            service_path,
        )

        if spec is None or spec.loader is None:
            raise ImportError(f"CalibrationService를 불러올 수 없습니다: {service_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
