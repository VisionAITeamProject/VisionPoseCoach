from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import cv2

from modules.features import (
    FEATURE_NAMES,
    calculate_face_features_for_window,
    calculate_features,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FACE_MODEL_PATH = "tasks/face_landmarker.task"
DEFAULT_MIN_CONFIDENCE = 0.5

FACE_FEATURE_NAMES = [
    "eyeBlinkLeft",
    "eyeBlinkRight",
    "blink_average",
    "jawOpen",
]


@dataclass
class VisionResult:
    ok: bool
    display_frame: Any = None
    pose_features: dict | None = None
    face_features: dict | None = None
    face_result: Any = None
    pose_detected: bool = False
    face_detected: bool = False
    error: str | None = None


class VisionProcessor:
    def __init__(
        self,
        face_model_path: str | Path | None = None,
        min_confidence: float | None = None,
    ):
        self.face_model_path = self._resolve_workspace_path(
            face_model_path or self._config_value("FACE_MODEL_PATH", DEFAULT_FACE_MODEL_PATH)
        )
        self.min_confidence = float(
            min_confidence
            if min_confidence is not None
            else self._config_value("MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
        )

        self._lock = Lock()
        self._mp = None
        self._vision = None
        self._python_tasks = None
        self._visualizer = None
        self._pose_detector = None
        self._face_detector = None
        self._started = False
        self._pose_ready = False
        self._face_ready = False
        self._last_error = None

    def start(self):
        with self._lock:
            if self._started:
                return

            self._started = True
            self._last_error = None
            errors = []

            try:
                import mediapipe as mp
                from mediapipe.tasks import python
                from mediapipe.tasks.python import vision

                self._mp = mp
                self._python_tasks = python
                self._vision = vision
            except Exception as exc:
                self._last_error = f"MediaPipe import failed: {exc}"
                return

            try:
                self._pose_detector = self._mp.solutions.pose.Pose(
                    min_detection_confidence=self.min_confidence,
                    min_tracking_confidence=self.min_confidence,
                )
                self._pose_ready = True
            except Exception as exc:
                errors.append(f"Pose init failed: {exc}")
                self._pose_ready = False

            try:
                self._face_detector = self._create_face_detector()
                self._face_ready = self._face_detector is not None
            except Exception as exc:
                errors.append(f"FaceLandmarker init failed: {exc}")
                self._face_ready = False

            try:
                from modules.visualizer import Visualizer

                self._visualizer = Visualizer()
            except Exception as exc:
                errors.append(f"Visualizer init failed: {exc}")
                self._visualizer = None

            if errors:
                self._last_error = " | ".join(errors)

    def process(self, frame):
        if frame is None:
            return VisionResult(
                ok=False,
                error="frame is None",
            )

        self.start()

        with self._lock:
            if not self.enabled:
                return VisionResult(
                    ok=False,
                    display_frame=frame.copy(),
                    error=self._last_error or "VisionProcessor is disabled",
                )

            try:
                display_frame = frame.copy()
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                pose_result = self._process_pose(img_rgb)
                face_result = self._process_face(img_rgb)

                pose_landmarks = self._extract_pose_landmarks(pose_result)
                face_landmarks = self._extract_face_landmarks(face_result)

                if self._visualizer is not None:
                    self._visualizer.draw_landmarks(
                        display_frame,
                        pose_landmarks,
                        face_landmarks,
                    )

                pose_features = self._build_pose_features(pose_landmarks)
                face_features = self._build_face_features(face_result)

                return VisionResult(
                    ok=True,
                    display_frame=display_frame,
                    pose_features=pose_features,
                    face_features=face_features,
                    face_result=face_result,
                    pose_detected=pose_landmarks is not None,
                    face_detected=face_landmarks is not None,
                    error=None,
                )

            except Exception as exc:
                self._last_error = str(exc)
                return VisionResult(
                    ok=False,
                    display_frame=frame.copy(),
                    error=self._last_error,
                )

    def status(self):
        with self._lock:
            return {
                "enabled": self.enabled,
                "pose_ready": self._pose_ready,
                "face_ready": self._face_ready,
                "last_error": self._last_error,
            }

    def release(self):
        with self._lock:
            if self._pose_detector is not None:
                try:
                    self._pose_detector.close()
                except Exception:
                    pass

            if self._face_detector is not None:
                try:
                    self._face_detector.close()
                except Exception:
                    pass

            self._pose_detector = None
            self._face_detector = None
            self._visualizer = None
            self._pose_ready = False
            self._face_ready = False
            self._started = False

    close = release

    @property
    def enabled(self):
        return self._pose_ready or self._face_ready

    def _process_pose(self, img_rgb):
        if self._pose_detector is None:
            return None

        return self._pose_detector.process(img_rgb)

    def _process_face(self, img_rgb):
        if self._face_detector is None:
            return None

        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=img_rgb,
        )
        return self._face_detector.detect(mp_image)

    def _build_pose_features(self, pose_landmarks):
        if pose_landmarks is None:
            return None

        raw_features = calculate_features([pose_landmarks.landmark])
        if raw_features is None:
            return None

        return {
            name: float(value)
            for name, value in zip(FEATURE_NAMES, raw_features)
        }

    def _build_face_features(self, face_result):
        if face_result is None or not hasattr(face_result, "face_blendshapes"):
            return None

        raw_features = calculate_face_features_for_window(face_result.face_blendshapes)
        if raw_features is None:
            return None

        return {
            name: float(value)
            for name, value in zip(FACE_FEATURE_NAMES, raw_features)
        }

    def _extract_pose_landmarks(self, pose_result):
        if pose_result is None:
            return None

        if not getattr(pose_result, "pose_landmarks", None):
            return None

        return pose_result.pose_landmarks

    def _extract_face_landmarks(self, face_result):
        if face_result is None:
            return None

        if not hasattr(face_result, "face_landmarks"):
            return None

        if not face_result.face_landmarks:
            return None

        return face_result.face_landmarks[0]

    def _create_face_detector(self):
        if not self.face_model_path.exists():
            self._last_error = f"FaceLandmarker model not found: {self.face_model_path}"
            return None

        with open(self.face_model_path, "rb") as model_file:
            face_model_buffer = model_file.read()

        base_options = self._python_tasks.BaseOptions(
            model_asset_buffer=face_model_buffer
        )
        options = self._vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_face_blendshapes=True,
            num_faces=1,
        )
        return self._vision.FaceLandmarker.create_from_options(options)

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
