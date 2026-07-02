import importlib.util
import re
from pathlib import Path
from threading import RLock

from modules.features import FEATURE_NAMES


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_TYPE = "gru"


class InferenceManager:
    def __init__(self, camera_manager, vision_processor, model_type=None):
        self.camera_manager = camera_manager
        self.vision_processor = vision_processor
        self.model_type = (model_type or self._config_value("MODEL_VERSION", DEFAULT_MODEL_TYPE)).lower()
        self._service = None
        self._ready = False
        self._posture_model_ready = False
        self._fatigue_model_ready = False
        self._last_error = None
        self._lock = RLock()

    def load(self):
        with self._lock:
            if self._ready:
                return True

            try:
                self._service = self._create_service()
                if hasattr(self._service, "enable_logging"):
                    self._service.enable_logging = False

                start_result = self._service.start()
                if not start_result.success:
                    self._last_error = start_result.message
                    self._ready = False
                    return False

                self._ready = True
                self._posture_model_ready = True
                self._fatigue_model_ready = True
                self._last_error = None
                return True

            except Exception as exc:
                self._service = None
                self._ready = False
                self._posture_model_ready = False
                self._fatigue_model_ready = False
                self._last_error = str(exc)
                return False

    def is_ready(self):
        with self._lock:
            return self._ready

    def predict_once(self, elapsed_sec=0):
        frame = self.camera_manager.get_latest_frame()
        vision_result = self.vision_processor.process(frame)
        return self.predict(vision_result, elapsed_sec=elapsed_sec)

    def predict(self, vision_result, elapsed_sec=0):
        if vision_result is None:
            return self._fallback(elapsed_sec, "vision result 없음")

        if not vision_result.ok:
            return self._fallback(
                elapsed_sec,
                vision_result.error or "feature 없음",
                vision_result=vision_result,
            )

        pose_features = self._feature_values(vision_result.pose_features, FEATURE_NAMES)
        if pose_features is None:
            return self._fallback(
                elapsed_sec,
                "pose feature 없음",
                vision_result=vision_result,
            )

        if not self.load():
            return self._fallback(
                elapsed_sec,
                self._last_error or "모델 로딩 실패",
                vision_result=vision_result,
            )

        with self._lock:
            try:
                result = self._service.update(pose_features, vision_result.face_result)
            except Exception as exc:
                self._last_error = str(exc)
                return self._fallback(elapsed_sec, str(exc), vision_result=vision_result)

        if not result.success:
            self._last_error = result.message
            return self._fallback(
                elapsed_sec,
                result.message,
                vision_result=vision_result,
            )

        self._last_error = None
        return {
            "type": "measurement",
            "state": "MEASURING",
            "elapsed_sec": elapsed_sec or result.elapsed_sec,
            "posture": {
                "label": self._normalize_label(result.posture_type),
                "confidence": float(result.confidence),
            },
            "fatigue": {
                "label": self._normalize_label(result.fatigue_label),
                "probability": float(result.fatigue_probability),
            },
            "rank": self._parse_rank(result.rank_text),
            "vision": self._vision_status(vision_result),
            "error": None,
        }

    def status(self):
        with self._lock:
            return {
                "ready": self._ready,
                "model_type": self.model_type,
                "posture_model_ready": self._posture_model_ready,
                "fatigue_model_ready": self._fatigue_model_ready,
                "last_error": self._last_error,
            }

    def release(self):
        with self._lock:
            if self._service is not None:
                try:
                    self._service.stop()
                except Exception:
                    pass

            self._service = None
            self._ready = False
            self._posture_model_ready = False
            self._fatigue_model_ready = False

    close = release

    def _create_service(self):
        config = self._load_config()

        if self.model_type == "mlp":
            module = self._load_service_module("mlp_inference_service.py")
            return module.FrameInferenceService(
                model_path=self._resolve_workspace_path(config.MODEL_PATH),
                face_model_path=self._resolve_workspace_path(config.MODEL_FACE_PATH),
                scaler_path=self._resolve_workspace_path(config.SCALER_PATH),
                face_scaler_path=self._resolve_workspace_path(config.SCALER_FACE_PATH),
                baseline_path=self._resolve_workspace_path(config.BASELINE_PATH),
                labels=config.POSTURE_LABELS,
                smoothing_frame=config.LABEL_FRAME,
                ui_emit_interval=0.5,
                fatigue_threshold=0.5,
            )

        module = self._load_service_module("gru_inference_service.py")
        return module.GruInferenceService(
            model_path=self._resolve_workspace_path(config.MODEL_PATH_GRU),
            face_model_path=self._resolve_workspace_path(config.MODEL_FACE_PATH_GRU),
            scaler_path=self._resolve_workspace_path(config.SCALER_PATH_GRU),
            face_scaler_path=self._resolve_workspace_path(config.SCALER_FACE_PATH_GRU),
            base_line_path=self._resolve_workspace_path(config.BASELINE_PATH),
            face_base_line_path=self._resolve_workspace_path(config.FACE_BASELINE_PATH),
            labels=config.POSTURE_LABELS,
            ui_emit_interval=0.5,
        )

    def _fallback(self, elapsed_sec, error, vision_result=None):
        return {
            "type": "measurement",
            "state": "MEASURING",
            "elapsed_sec": elapsed_sec,
            "posture": {
                "label": "Unknown",
                "confidence": 0.0,
            },
            "fatigue": {
                "label": "Unknown",
                "probability": 0.0,
            },
            "rank": [],
            "vision": self._vision_status(vision_result),
            "error": error or "모델 로딩 실패 또는 feature 없음",
        }

    def _vision_status(self, vision_result):
        if vision_result is None:
            return {
                "pose_detected": False,
                "face_detected": False,
            }

        return {
            "pose_detected": bool(vision_result.pose_detected),
            "face_detected": bool(vision_result.face_detected),
        }

    def _feature_values(self, features, feature_names):
        if not features:
            return None

        values = []
        for name in feature_names:
            if name not in features:
                return None
            values.append(float(features[name]))

        return values

    def _parse_rank(self, rank_text):
        if not rank_text:
            return []

        rank = []
        for line in rank_text.splitlines():
            match = re.search(r"\d+위\s+(.+?)(?:\s+\d+회|\s*$)", line)
            if not match:
                continue

            label = match.group(1).strip()
            if label and label != "-":
                rank.append(label)

        return rank[:3]

    def _normalize_label(self, label):
        if not label or label == "-":
            return "Unknown"

        return str(label)

    def _resolve_workspace_path(self, path_text):
        path = Path(path_text)

        if path.is_absolute():
            return path

        return ROOT_DIR / path

    def _config_value(self, name, default):
        try:
            config = self._load_config()
            return getattr(config, name, default)
        except Exception:
            return default

    def _load_config(self):
        import modules.config as config

        return config

    def _load_service_module(self, filename):
        service_path = ROOT_DIR / "pyQt" / "services" / filename
        module_name = f"server_reused_{service_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, service_path)

        if spec is None or spec.loader is None:
            raise ImportError(f"추론 서비스를 불러올 수 없습니다: {service_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
