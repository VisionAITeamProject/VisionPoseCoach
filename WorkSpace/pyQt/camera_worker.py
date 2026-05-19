import sys
import time
import traceback
import platform
from enum import Enum, auto
from pathlib import Path

import mediapipe as mp
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

import cv2

from mediapipe.tasks import python
from mediapipe.tasks.python import vision


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))


import modules.config as config
from modules.features import calculate_features, calculate_face_features_for_window
from modules.visualizer import Visualizer

from services.calibration_service import CalibrationService
from services.mlp_inference_service import FrameInferenceService
from services.gru_inference_service import GruInferenceService
from services.hardware_controller import HardwareController


# =========================================================
# Camera Source Wrappers
# =========================================================

class OpenCVCameraSource:
    """
    Windows / 일반 Linux 웹캠용 카메라 래퍼.

    내부적으로 cv2.VideoCapture를 사용하지만,
    외부에서는 Picamera2Source와 동일하게
    open(), start(), read(), release() 형태로 사용한다.
    """

    def __init__(self, camera_index=0, width=640, height=480):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.cap = None

    def open(self):
        self.cap = cv2.VideoCapture(self.camera_index)

        if not self.cap.isOpened():
            raise RuntimeError("OpenCV 기본 카메라를 열 수 없습니다.")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

    def start(self):
        """
        cv2.VideoCapture는 별도의 start가 필요 없다.
        Picamera2Source와 인터페이스를 맞추기 위해 비워둔다.
        """
        pass

    def read(self):
        if self.cap is None:
            return False, None

        ret, frame = self.cap.read()

        if not ret or frame is None:
            return False, None

        # OpenCV는 BGR 프레임을 반환한다.
        return True, frame

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class PiCamera2Source:
    """
    Raspberry Pi Camera Module용 카메라 래퍼.
    haha
    내부적으로 Picamera2를 사용하지만,
    외부에서는 OpenCVCameraSource와 동일하게
    open(), start(), read(), release() 형태로 사용한다.
    """

    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self.picam2 = None

    def open(self):
        """
        picamera2는 Windows에 없을 수 있으므로
        파일 상단에서 import하지 않고 여기서 지연 import한다.
        """
        from picamera2 import Picamera2

        self.picam2 = Picamera2()

        camera_config = self.picam2.create_preview_configuration(
            main={
                # "format": "RGB888",
                "size": (self.width, self.height),
            }
        )

        self.picam2.configure(camera_config)

    def start(self):
        if self.picam2 is not None:
            self.picam2.start()

    def read(self):
        if self.picam2 is None:
            return False, None

        frame = self.picam2.capture_array()

        if frame is None:
            return False, None

        # Picamera2에서 RGB888로 받았으므로
        # 기존 OpenCV 처리 흐름에 맞추기 위해 BGR로 변환한다.
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        return True, frame

    def release(self):
        if self.picam2 is not None:
            try:
                self.picam2.stop()
            except Exception:
                pass

            try:
                self.picam2.close()
            except Exception:
                pass

            self.picam2 = None


class RunMode(Enum):
    """
    CameraWorker의 현재 동작 상태.

    PREVIEW:
        카메라와 랜드마크만 보여주는 상태.

    HARDWARE:
        하드웨어 수평 보정 중인 상태.

    CALIBRATING:
        baseline.pkl 생성을 위해 feature를 수집하는 상태.

    MEASURING:
        실시간 자세 / 피로도 추론 중인 상태.
    """

    PREVIEW = auto()
    HARDWARE = auto()
    CALIBRATING = auto()
    MEASURING = auto()


class CameraWorker(QThread):
    """
    PyQt 카메라 처리 전용 Worker.

    담당:
    1. 실행 환경에 맞는 카메라 선택
       - Linux: Picamera2 먼저 시도 후 실패하면 OpenCV fallback
       - Windows: OpenCV 기본 카메라 사용
    2. MediaPipe Pose / FaceLandmarker 실행
    3. 프레임에 랜드마크 그리기
    4. calculate_features()로 pose feature 추출
    5. 현재 mode에 따라 CalibrationService 또는 InferenceService 호출
    6. QImage와 결과 dict를 PyQt UI로 emit
    """

    frame_changed = pyqtSignal(QImage)
    status_changed = pyqtSignal(str)
    calibration_finished = pyqtSignal(bool, str)
    measurement_started = pyqtSignal(bool, str)
    result_changed = pyqtSignal(dict)

    def __init__(self, hardware_controller=None, parent=None):
        super().__init__(parent)

        self.running = False
        self.mode = RunMode.PREVIEW

        # Camera / Vision
        self.camera = None
        self.viz = None
        self.pose_detector = None
        self.face_detector = None

        # Service
        self.calibration_service = CalibrationService(
            baseline_path=self.resolve_workspace_path(config.BASELINE_PATH),
            duration=config.CALIBRATION_TIME,
        )


        print("초기화 성공")

        # 하드웨어 컨트롤러
        if hardware_controller is None:
            self.hardware_controller = HardwareController(
                enabled=config.HARDWARE_ENABLED,
                serial_port=config.HARDWARE_SERIAL_PORT,
                baud_rate=config.HARDWARE_BAUD_RATE,
                timeout=config.HARDWARE_TIMEOUT,
            )
            self.owns_hardware_controller = True
        else:
            self.hardware_controller = hardware_controller
            self.owns_hardware_controller = False

        # face calibration service 추가
        self.calibration_service_face = CalibrationService(
            baseline_path=self.resolve_workspace_path(config.FACE_BASELINE_PATH),
            duration=config.CALIBRATION_TIME,
        )


        self.pose_calibration_result = None
        self.face_calibration_result = None

        print("초기화 성공")

        # 하드웨어 컨트롤러
        if hardware_controller is None:
            self.hardware_controller = HardwareController(
                enabled=config.HARDWARE_ENABLED,
                serial_port=config.HARDWARE_SERIAL_PORT,
                baud_rate=config.HARDWARE_BAUD_RATE,
                timeout=config.HARDWARE_TIMEOUT,
            )
            self.owns_hardware_controller = True
        else:
            self.hardware_controller = hardware_controller
            self.owns_hardware_controller = False

        self.inference_service = None

        # 버튼을 누른 시점에 worker가 아직 시작 전일 수 있으므로 pending 처리
        self.pending_preview_start = False
        self.pending_calibration_start = False
        self.pending_measurement_start = False

        # 하드웨어 관련 변수
        self.HarwareInit_requested = False

        # 상태 메시지 너무 자주 emit하지 않기 위한 변수
        self.last_status_emit_time = 0.0
        self.status_emit_interval = 0.4

    # ---------------------------------------------------------
    # Main Loop
    # ---------------------------------------------------------
    def run(self):
        """
        QThread 시작 시 실행되는 메인 루프.

        카메라를 계속 읽고,
        현재 mode에 따라 캘리브레이션 또는 추론을 수행한다.
        """

        self.running = True
        error_message = None

        try:
            self.initialize_camera_system()
            self.status_changed.emit("카메라 프리뷰 준비 완료")

            # worker 시작 전에 버튼이 눌렸던 경우 처리
            self.apply_pending_command()

            self.camera.start()
            print("카메라 시작 성공")

            while self.running:
                ret, frame = self.camera.read()

                if not ret or frame is None:
                    self.emit_status_interval("카메라 프레임을 읽지 못했습니다.")
                    continue

                # main.py에서 가져온 기본 전처리
                frame = cv2.flip(frame, 1)
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=img_rgb
                )

                # MediaPipe
                results_pose = self.pose_detector.process(img_rgb)
                results_face = self.face_detector.detect(mp_image)
                raw_features = None

                if results_pose.pose_landmarks:
                    face_landmarks = self.extract_face_landmarks(results_face)

                    # 화면 표시용 랜드마크 그리기
                    self.viz.draw_landmarks(
                        frame,
                        results_pose.pose_landmarks,
                        face_landmarks
                    )

                    landmark_list = [results_pose.pose_landmarks.landmark]
                    raw_features = calculate_features(landmark_list)

                    if self.is_valid_feature(raw_features):
                        self.process_by_mode(raw_features, results_face)
                    else:
                        if self.mode == RunMode.CALIBRATING:
                            self.emit_status_interval("feature 추출이 아직 불안정합니다.")

                else:
                    if self.mode == RunMode.CALIBRATING:
                        self.emit_status_interval("자세가 인식되지 않습니다. 카메라 정면에 앉아주세요.")

                # PyQt QLabel 표시용으로 프레임 전달
                q_image = self.convert_frame_to_qimage(frame)
                self.frame_changed.emit(q_image)

        except Exception as e:
            error_message = traceback.format_exc()
            print(error_message)
            self.status_changed.emit(f"카메라 오류 발생:\n{e}")

        finally:
            self.release_resources(show_message=(error_message is None))

    # ---------------------------------------------------------
    # Initialize
    # ---------------------------------------------------------
    def initialize_camera_system(self):
        """
        카메라와 MediaPipe 시스템을 초기화한다.
        """

        face_task_path = self.resolve_workspace_path(config.FACE_MODEL_PATH)

        if not face_task_path.exists():
            raise FileNotFoundError(
                f"FaceLandmarker 모델 파일을 찾을 수 없습니다:\n{face_task_path}"
            )

        self.camera = self.create_camera_source()
        print("카메라 초기화 성공")

        self.viz = Visualizer()

        mp_pose = mp.solutions.pose

        self.pose_detector = mp_pose.Pose(
            min_detection_confidence=config.MIN_CONFIDENCE,
            min_tracking_confidence=config.MIN_CONFIDENCE,
        )

        with open(face_task_path, "rb") as f:
            face_model_buffer = f.read()

        base_options = python.BaseOptions(
            model_asset_buffer=face_model_buffer
        )

        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_face_blendshapes=True,
            num_faces=1,
        )

        self.face_detector = vision.FaceLandmarker.create_from_options(options)

    def create_camera_source(self):
        """
        실행 환경에 따라 사용할 카메라 소스를 선택한다.

        Linux:
            1. Picamera2 먼저 시도
            2. 실패하면 OpenCV 기본 카메라로 fallback

        Windows:
            1. OpenCV 기본 카메라 사용
        """

        width = config.FRAME_WIDTH
        height = config.FRAME_HEIGHT

        errors = []
        system_name = platform.system().lower()

        is_linux = system_name == "linux"

        if is_linux:
            try:
                camera = PiCamera2Source(
                    width=width,
                    height=height,
                )
                camera.open()

                self.status_changed.emit("Picamera2 카메라를 사용합니다.")
                print("Picamera2 카메라 선택 완료")

                return camera

            except Exception as e:
                error_text = f"Picamera2 실패: {e}"
                errors.append(error_text)
                print(error_text)

                self.status_changed.emit(
                    "Picamera2 사용 실패. OpenCV 기본 카메라를 시도합니다."
                )

        try:
            camera = OpenCVCameraSource(
                camera_index=0,
                width=width,
                height=height,
            )
            camera.open()

            self.status_changed.emit("OpenCV 기본 카메라를 사용합니다.")
            print("OpenCV 카메라 선택 완료")

            return camera

        except Exception as e:
            error_text = f"OpenCV 카메라 실패: {e}"
            errors.append(error_text)
            print(error_text)

        raise RuntimeError(
            "사용 가능한 카메라를 찾지 못했습니다.\n" + "\n".join(errors)
        )

    # ---------------------------------------------------------
    # Pending Command
    # ---------------------------------------------------------
    def apply_pending_command(self):
        """
        Worker가 완전히 시작되기 전에 버튼 명령이 들어온 경우 처리한다.
        """

        if self.pending_calibration_start:
            self.pending_calibration_start = False
            self.start_calibration()
            return

        if self.pending_measurement_start:
            self.pending_measurement_start = False
            self.start_measurement()
            return

        if self.pending_preview_start:
            self.pending_preview_start = False
            self.start_preview()
            return

    # ---------------------------------------------------------
    # Button Control
    # ---------------------------------------------------------
    def start_preview(self):
        """
        Calibration 버튼을 눌렀을 때 호출.

        카메라는 계속 켜두고,
        프리뷰와 랜드마크만 보여주는 상태로 둔다.
        """

        if not self.running:
            self.pending_preview_start = True
            self.status_changed.emit("카메라 준비 중입니다. 준비되면 프리뷰를 시작합니다.")
            return

        self.mode = RunMode.PREVIEW
        self.status_changed.emit("프리뷰 모드입니다. 바른 자세를 준비해주세요.")

    def start_calibration(self):
        """
        Calibration Start 버튼을 눌렀을 때 호출.

        실제 baseline feature 수집을 시작한다.
        """

        if not self.running:
            self.pending_calibration_start = True
            self.status_changed.emit("카메라 준비 중입니다. 준비되면 초기 측정을 시작합니다.")
            return

        # 하드웨어 모드 진입
        self.mode = RunMode.HARDWARE
        self.HarwareInit_requested = True
        self.status_changed.emit("카메라 수평 보정을 시작합니다.")

    def start_measurement(self):
        """
        추론 시작 버튼을 눌렀을 때 호출.

        config.MODEL_VERSION을 보고 사용할 추론 서비스를 선택한다.
        현재는 mlp 모델을 우선 연결한다.
        """

        if not self.running:
            self.pending_measurement_start = True
            self.status_changed.emit("카메라 준비 중입니다. 준비되면 추론을 시작합니다.")
            return

        try:
            # 기존 추론 서비스가 있으면 먼저 정리
            if self.inference_service is not None:
                self.inference_service.stop()
                self.inference_service = None

            model_version = getattr(config, "MODEL_VERSION", "mlp")

            if model_version == "mlp":
                self.inference_service = FrameInferenceService(
                    model_path=self.resolve_workspace_path(config.MODEL_PATH),
                    face_model_path=self.resolve_workspace_path(config.MODEL_FACE_PATH),
                    scaler_path=self.resolve_workspace_path(config.SCALER_PATH),
                    face_scaler_path=self.resolve_workspace_path(config.SCALER_FACE_PATH),
                    baseline_path=self.resolve_workspace_path(config.BASELINE_PATH),
                    labels=config.POSTURE_LABELS,
                    smoothing_frame=config.LABEL_FRAME,
                    ui_emit_interval=0.5,
                    fatigue_threshold=0.5,
                )

            elif model_version == "gru":
                self.inference_service = GruInferenceService(
                    model_path=self.resolve_workspace_path(config.MODEL_PATH_GRU),
                    face_model_path=self.resolve_workspace_path(config.MODEL_FACE_PATH_GRU),
                    scaler_path=self.resolve_workspace_path(config.SCALER_PATH_GRU),
                    face_scaler_path=self.resolve_workspace_path(config.SCALER_FACE_PATH_GRU),
                    base_line_path=self.resolve_workspace_path(config.BASELINE_PATH),
                    face_base_line_path=self.resolve_workspace_path(config.FACE_BASELINE_PATH),
                    labels=config.POSTURE_LABELS,
                    ui_emit_interval=0.5,
                )

            else:
                self.measurement_started.emit(
                    False,
                    f"지원하지 않는 MODEL_VERSION입니다: {model_version}"
                )
                return

            start_result = self.inference_service.start()

            if not start_result.success:
                self.mode = RunMode.PREVIEW
                self.measurement_started.emit(False, start_result.message)
                self.status_changed.emit(start_result.message)
                return

            self.mode = RunMode.MEASURING
            self.measurement_started.emit(True, start_result.message)
            self.status_changed.emit(start_result.message)

        except Exception as e:
            msg = f"추론 시작 실패:\n{e}"
            self.mode = RunMode.PREVIEW
            self.measurement_started.emit(False, msg)
            self.status_changed.emit(msg)

    def stop_measurement(self):
        """
        추론만 종료하고 카메라는 유지하고 싶을 때 사용한다.
        """

        if self.inference_service is not None:
            self.inference_service.stop()
            self.inference_service = None

        self.mode = RunMode.PREVIEW
        self.status_changed.emit("추론을 종료하고 프리뷰 모드로 돌아갑니다.")

    # ---------------------------------------------------------
    # Mode Processing
    # ---------------------------------------------------------
    def process_by_mode(self, raw_features, results_face):
        """
        현재 mode에 따라 feature를 처리한다.

        HARDWARE:
            하드웨어 수평 보정 후 캘리브레이션 시작

        CALIBRATING:
            baseline feature 수집

        MEASURING:
            실시간 자세 / 피로도 추론
        """

        if self.mode == RunMode.HARDWARE:
            self.process_HardWare_then_calibration()

        if self.mode == RunMode.CALIBRATING:
            self.process_calibration(raw_features, results_face)

        elif self.mode == RunMode.MEASURING:
            self.process_measurement(raw_features, results_face)

    def process_HardWare_then_calibration(self):
        """
        하드웨어 수평 보정 후 캘리브레이션을 시작한다.

        이 함수는 CameraWorker 스레드 안에서 호출되므로
        blocking 함수인 start_HardwareSet()을 실행해도 UI 메인 스레드는 멈추지 않는다.
        """

        if not self.HarwareInit_requested:
            return

        self.HarwareInit_requested = False

        self.status_changed.emit("카메라 수평 보정 중입니다.")

        hardware_success = self.hardware_controller.start_HardwareSet()

        if not hardware_success:
            self.status_changed.emit("수평 보정에 실패했거나 건너뛰었습니다.")

        self.pose_calibration_result = None
        self.face_calibration_result = None

        result = self.calibration_service.start()
        result = self.calibration_service_face.start()  #face calibration 시작

        self.mode = RunMode.CALIBRATING
        self.status_changed.emit("초기 자세/얼굴 기준값 측정을 시작합니다. "
                                 f"{config.CALIBRATION_TIME}초 동안 바른 자세를 유지해주세요.")


    def process_calibration(self, raw_features, results_face): #face feature도 넘겨주도록 수정
        """
        Pose baseline과 Face baseline을 동시에 수집한다.
        둘 중 하나가 먼저 끝나도 결과를 보관하고,
        둘 다 끝났을 때만 calibration 완료 처리한다.
        """

        # 1. pose calibration
        if self.pose_calibration_result is None:
            pose_result = self.calibration_service.update(raw_features)
            self.emit_status_interval(pose_result.message)

            if pose_result.is_finished:
                self.pose_calibration_result = pose_result

        # 2. face calibration
        if self.face_calibration_result is None:
            face_features = self.build_face_calibration_features(results_face)

            if face_features is None:
                self.emit_status_interval("얼굴 feature를 수집하지 못했습니다. 얼굴이 보이도록 앉아주세요.")
                return

            face_result = self.calibration_service_face.update(face_features)
            self.emit_status_interval(face_result.message)

            if face_result.is_finished:
                self.face_calibration_result = face_result

        # 3. 둘 다 끝났는지 확인
        if self.pose_calibration_result is None:
            return

        if self.face_calibration_result is None:
            return

        self.mode = RunMode.PREVIEW # preview 모드로 돌아가지만, 수집된 baseline은 보관한다.

        success = (
            self.pose_calibration_result.success
            and self.face_calibration_result.success
        )

        final_message = (
            f"{self.pose_calibration_result.message}\n"
            f"자세 기준값 저장 경로: {self.pose_calibration_result.baseline_path}\n\n"
            f"{self.face_calibration_result.message}\n"
            f"얼굴 기준값 저장 경로: {self.face_calibration_result.baseline_path}"
        )

        self.status_changed.emit(final_message)
        self.calibration_finished.emit(success, final_message)

    def process_measurement(self, raw_features, results_face):
        """
        추론 서비스에 feature와 face 결과를 넘기고 UI 결과를 emit한다.
        """

        if self.inference_service is None:
            return

        result = self.inference_service.update(raw_features, results_face)

        if not result.success:
            self.emit_status_interval(result.message)
            return

        # 하드웨어 제어는 UI emit 여부와 별개로 수행한다.
        # get_posture_result_from_ai() 내부에서 3초 지속 여부와 중복 전송 방지를 처리한다.
        self.hardware_controller.update_hardware(result)

        if not result.should_emit_ui:
            return

        self.result_changed.emit({
            "posture_type": result.posture_type,
            "confidence": result.confidence,
            "fatigue_label": result.fatigue_label,
            "fatigue_probability": result.fatigue_probability,
            "elapsed_sec": result.elapsed_sec,
            "rank_text": result.rank_text,
        })

        self.status_changed.emit(result.message)

    # ---------------------------------------------------------
    # Helper
    # ---------------------------------------------------------
    def is_valid_feature(self, raw_features):
        """
        pose feature가 추론/캘리브레이션에 사용할 수 있는 상태인지 검사한다.
        """

        if raw_features is None:
            return False

        feature_array = np.asarray(raw_features, dtype=np.float32)

        if feature_array.size != config.POSE_FEATURE_SIZE:
            self.emit_status_interval(
                f"pose feature 개수 불일치: 현재={feature_array.size}, 필요={config.POSE_FEATURE_SIZE}"
            )
            return False

        if not np.any(feature_array):
            return False

        return True
    
    # face feature가 유효한지 검사하는 함수 추가
    def build_face_calibration_features(self, results_face):
        """
        Face calibration용 4개 feature를 만든다.
        GRU face 모델 입력과 동일한 순서:
        [eyeBlinkLeft, eyeBlinkRight, blink_average, jawOpen]
        """

        if results_face is None:
            return None

        if not hasattr(results_face, "face_blendshapes"):
            return None

        face_features = calculate_face_features_for_window(
            results_face.face_blendshapes
        )

        if face_features is None:
            return None

        feature_array = np.asarray(face_features, dtype=np.float32)

        if feature_array.size != config.FACE_FEATURE_SIZE:
            self.emit_status_interval(
                f"face feature 개수 불일치: 현재={feature_array.size}, 필요={config.FACE_FEATURE_SIZE}"
            )
            return None

        if not np.any(feature_array):
            return None

        return feature_array

    def extract_face_landmarks(self, results_face):
        """
        Visualizer에 넘길 face landmark를 안전하게 꺼낸다.
        """

        if results_face is None:
            return None

        if not hasattr(results_face, "face_landmarks"):
            return None

        if not results_face.face_landmarks:
            return None

        if len(results_face.face_landmarks) <= 0:
            return None

        return results_face.face_landmarks[0]

    def resolve_workspace_path(self, path_text):
        """
        config 경로를 프로젝트 ROOT 기준 절대 경로로 변환한다.
        """

        path = Path(path_text)

        if path.is_absolute():
            return path

        return ROOT_DIR / path

    def emit_status_interval(self, message):
        """
        상태 메시지가 너무 자주 바뀌면 UI가 지저분해지므로
        일정 간격마다만 emit한다.
        """

        now = time.time()

        if now - self.last_status_emit_time < self.status_emit_interval:
            return

        self.last_status_emit_time = now
        self.status_changed.emit(message)

    def convert_frame_to_qimage(self, frame):
        """
        OpenCV BGR frame을 PyQt QLabel에 표시 가능한 QImage로 변환한다.
        """

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w

        return QImage(
            rgb_frame.data,
            w,
            h,
            bytes_per_line,
            QImage.Format_RGB888,
        ).copy()

    # ---------------------------------------------------------
    # Stop / Release
    # ---------------------------------------------------------
    def stop(self):
        """
        Camera Off 또는 창 종료 시 호출한다.

        카메라 루프 종료, 서비스 정리, 리소스 해제를 수행한다.
        """
        self.running = False

        self.pending_preview_start = False
        self.pending_calibration_start = False
        self.pending_measurement_start = False

        self.calibration_service.cancel()
        self.calibration_service_face.cancel()

        self.pose_calibration_result = None
        self.face_calibration_result = None

        if self.inference_service is not None:
            self.inference_service.stop()
            self.inference_service = None

        self.wait()

    def release_resources(self, show_message=True):
        """
        카메라와 MediaPipe 리소스를 정리한다.
        """

        if self.camera is not None:
            self.camera.release()
            self.camera = None

        if self.pose_detector is not None:
            self.pose_detector.close()
            self.pose_detector = None

        if (self.hardware_controller is not None and self.owns_hardware_controller):
            self.hardware_controller.close()

        if self.face_detector is not None:
            self.face_detector.close()
            self.face_detector = None

        if show_message:
            self.status_changed.emit("카메라가 종료되었습니다.")