import base64
import time
from threading import Event, Lock, Thread

import cv2
import numpy as np


FALLBACK_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/"
    "9oADAMBAAIQAxAAAAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/ASP/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/ASP/"
    "xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Al//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IV//2gAMAwEAAgADAAAAEP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8QH//EABQQAQAAAAAAAAAAAAAAAAAAABD/2gAIAQEAAT8QH//Z"
)


class CameraManager:
    def __init__(
        self,
        camera_index=0,
        width=640,
        height=480,
        retry_interval=3.0,
        frame_interval=0.03,
    ):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.retry_interval = retry_interval
        self.frame_interval = frame_interval

        self._lock = Lock()
        self._capture = None
        self._thread = None
        self._stop_event = Event()
        self._last_open_attempt = 0.0
        self._latest_frame = None
        self._last_frame_time = None
        self._using_dummy = True
        self._running = False

    @property
    def using_dummy(self):
        with self._lock:
            return self._using_dummy

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._stop_event.clear()
            self._running = True
            self._thread = Thread(
                target=self._frame_loop,
                name="CameraManagerFrameLoop",
                daemon=True,
            )
            self._thread.start()

    def stop(self):
        with self._lock:
            thread = self._thread
            self._running = False
            self._stop_event.set()

        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

        with self._lock:
            self._thread = None
            self._latest_frame = None
            self._last_frame_time = None
            self._using_dummy = True
            self._release_locked()

    def get_jpeg_frame(self):
        frame = self.get_latest_frame()

        if frame is None:
            frame = self._create_dummy_frame()

        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return FALLBACK_JPEG

        return buffer.tobytes()

    def get_latest_frame(self):
        with self._lock:
            if self._latest_frame is None:
                return None

            return self._latest_frame.copy()

    def status(self):
        with self._lock:
            using_dummy = self._using_dummy
            running = self._running
            has_frame = self._latest_frame is not None
            last_frame_time = self._last_frame_time

        return {
            "camera_index": self.camera_index,
            "using_dummy": using_dummy,
            "running": running,
            "has_frame": has_frame,
            "last_frame_time": last_frame_time,
            "width": self.width,
            "height": self.height,
        }

    def release(self):
        self.stop()

    def _frame_loop(self):
        while not self._stop_event.is_set():
            try:
                frame = self._read_camera_frame()
            except Exception:
                frame = None
                with self._lock:
                    self._release_locked()

            if frame is None:
                with self._lock:
                    self._using_dummy = True
                    self._latest_frame = None
                    self._last_frame_time = None
                self._stop_event.wait(self.frame_interval)
                continue

            with self._lock:
                self._using_dummy = False
                self._latest_frame = frame
                self._last_frame_time = time.time()

            self._stop_event.wait(self.frame_interval)

        with self._lock:
            self._running = False
            self._release_locked()

    def _read_camera_frame(self):
        capture = self._ensure_capture()
        if capture is None:
            return None

        ok, frame = capture.read()
        if not ok or frame is None:
            self._release_locked()
            return None

        return cv2.resize(frame, (self.width, self.height))

    def _ensure_capture(self):
        with self._lock:
            if self._capture is not None and self._capture.isOpened():
                return self._capture

            now = time.time()
            if now - self._last_open_attempt < self.retry_interval:
                return None

            self._last_open_attempt = now

        capture = cv2.VideoCapture(self.camera_index)
        if not capture.isOpened():
            capture.release()
            return None

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

        with self._lock:
            if self._stop_event.is_set():
                capture.release()
                return None

            self._capture = capture
            return self._capture

    def _release_locked(self):
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _create_dummy_frame(self):
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (35, 35, 35)

        cv2.putText(
            frame,
            "VisionPoseCoach Server",
            (30, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Camera not available - dummy frame",
            (30, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 220, 255),
            2,
            cv2.LINE_AA,
        )

        return frame
