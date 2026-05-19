import os
import sys
import time
from dataclasses import dataclass
from collections import deque, Counter
from pathlib import Path

import joblib
import numpy as np

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    import tensorflow.lite as tflite


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))

import modules.config as config
from modules.features import calculate_face_features_for_window
from modules.logger import StudyLogger


@dataclass
class InferenceStartResult:
    success: bool
    message: str


@dataclass
class InferenceResult:
    success: bool
    message: str
    should_emit_ui: bool = False

    posture_type: str = "-"
    confidence: float = 0.0

    fatigue_label: str = "Normal"
    fatigue_probability: float = 0.0

    elapsed_sec: int = 0
    rank_text: str = ""


class GruInferenceService:
    """
    GRU / Sequence 모델 전용 추론 서비스.

    역할:
    1. 매 프레임 pose feature 10개를 pose_window에 누적
    2. 매 프레임 face feature 4개를 face_window에 누적
    3. WINDOW_SIZE만큼 쌓이면 STRIDE 간격마다 추론
    4. 입력 shape을 [1, WINDOW_SIZE, FEATURE_SIZE]로 변환
    5. 자세 / 피로도 결과를 PyQt UI 형식으로 반환
    """

    def __init__(
        self,
        model_path,
        face_model_path,
        scaler_path,
        face_scaler_path,
        base_line_path,
        face_base_line_path,
        labels=None,
        ui_emit_interval=0.5,
        log_dir="../data/session_log",
    ):
        self.model_path = str(model_path)
        self.face_model_path = str(face_model_path)
        self.scaler_path = str(scaler_path)
        self.face_scaler_path = str(face_scaler_path)


        self.base_line = self.load_baseline(base_line_path, feature_size=config.POSE_FEATURE_SIZE, name="pose")
        print(f"self.base_line : {self.base_line}")

        self.base_line_face = self.load_baseline(face_base_line_path, feature_size=config.FACE_FEATURE_SIZE, name="face")
        print(f"self.base_line_face : {self.base_line_face}")

        self.labels = labels if labels is not None else config.POSTURE_LABELS
        self.face_labels = config.FACE_LABELS

        self.ui_emit_interval = ui_emit_interval
        self.log_dir = log_dir

        self.pose_scaler = None
        self.face_scaler = None

        self.pose_interpreter = None
        self.face_interpreter = None

        self.pose_input_details = None
        self.pose_output_details = None
        self.face_input_details = None
        self.face_output_details = None

        self.pose_window = deque(maxlen=config.WINDOW_SIZE)
        self.face_window = deque(maxlen=config.WINDOW_SIZE)

        self.frame_count = 0

        self.latest_posture_type = "-"
        self.latest_confidence = 0.0
        self.latest_fatigue_label = "Normal"
        self.latest_fatigue_probability = 0.0

        self.posture_counter = Counter()

        self.session_start_time = None
        self.last_ui_emit_time = 0.0
        self.is_running = False

        self.logger = None
        self.enable_logging = True

    # ---------------------------------------------------------
    # Life Cycle
    # ---------------------------------------------------------
    def start(self):
        try:
            self.pose_scaler = joblib.load(self.scaler_path)
            self.face_scaler = joblib.load(self.face_scaler_path)

            self.pose_interpreter = tflite.Interpreter(model_path=self.model_path)
            self.pose_interpreter.allocate_tensors()

            self.face_interpreter = tflite.Interpreter(model_path=self.face_model_path)
            self.face_interpreter.allocate_tensors()

            self.pose_input_details = self.pose_interpreter.get_input_details()
            self.pose_output_details = self.pose_interpreter.get_output_details()

            self.face_input_details = self.face_interpreter.get_input_details()
            self.face_output_details = self.face_interpreter.get_output_details()

        except Exception as e:
            return InferenceStartResult(
                success=False,
                message=f"GRU 모델 로드 실패:\n{e}"
            )

        self.pose_window.clear()
        self.face_window.clear()
        self.posture_counter.clear()

        self.frame_count = 0

        self.latest_posture_type = "-"
        self.latest_confidence = 0.0
        self.latest_fatigue_label = "Normal"
        self.latest_fatigue_probability = 0.0

        self.session_start_time = time.time()
        self.last_ui_emit_time = 0.0
        self.is_running = True

        if self.enable_logging:
            self.logger = StudyLogger(base_dir=self.log_dir)

        return InferenceStartResult(
            success=True,
            message=(
                f"GRU 모델 추론을 시작했습니다. "
                f"{config.WINDOW_SIZE}프레임 수집 후 {config.STRIDE}프레임마다 갱신됩니다."
            )
        )

    def stop(self):
        self.is_running = False

        self.pose_window.clear()
        self.face_window.clear()
        self.posture_counter.clear()

        self.frame_count = 0
        self.session_start_time = None
        self.last_ui_emit_time = 0.0

        self.pose_interpreter = None
        self.face_interpreter = None
        self.pose_scaler = None
        self.face_scaler = None
        self.logger = None

    # ---------------------------------------------------------
    # Update
    # ---------------------------------------------------------
    def update(self, pose_features, results_face=None):
        if not self.is_running:
            return InferenceResult(
                success=False,
                message="GRU 추론이 실행 중이 아닙니다."
            )

        self.frame_count += 1
        safe_pose_features = self.build_pose_features(pose_features)
        safe_face_features = self.build_face_features(results_face)

        safe_pose_features = np.array(safe_pose_features)- self.base_line
        safe_pose_features = list(safe_pose_features)
        
        safe_face_features = np.array(safe_face_features)- self.base_line_face
        safe_face_features = list(safe_face_features)

        self.pose_window.append(safe_pose_features)
        self.face_window.append(safe_face_features)

        elapsed_sec = self.get_elapsed_sec()

        # 아직 WINDOW_SIZE만큼 안 쌓였으면 최근 결과만 유지
        if len(self.pose_window) == config.WINDOW_SIZE and self.frame_count % config.STRIDE != 0:
            try:
                # print(f"face_window : {self.face_window.__len__()}")
                # print(f"pose_window : {self.pose_window.__len__()}")

                posture_type, posture_confidence = self.predict_pose()
                fatigue_label, fatigue_probability = self.predict_face()
                # fatigue_label, fatigue_probability = "Normal", 0.0

            except Exception as e:
                return InferenceResult(
                    success=False,
                    message=f"GRU 추론 오류: {e}"
                )
            
            self.latest_posture_type = posture_type
            self.latest_confidence = posture_confidence
            self.latest_fatigue_label = fatigue_label
            self.latest_fatigue_probability = fatigue_probability

            normal_label = self.labels.get(0, "Optimal")

            if posture_type != normal_label:
                self.posture_counter[posture_type] += 1

            should_emit_ui = self.should_emit_ui()

            if should_emit_ui:
                self.save_log(
                    posture_type=posture_type,
                    fatigue_label=fatigue_label,
                    fatigue_probability=fatigue_probability,
                )

            return InferenceResult(
                success=True,
                message=f"GRU 측정 중: {posture_type} / {posture_confidence * 100:.1f}%",
                should_emit_ui=should_emit_ui,
                posture_type=posture_type,
                confidence=posture_confidence,
                fatigue_label=fatigue_label,
                fatigue_probability=fatigue_probability,
                elapsed_sec=elapsed_sec,
                rank_text=self.build_rank_text(),
            )


        if self.latest_posture_type == "-" :
            return InferenceResult(
                success=False,
                message=f"GRU 입력 수집 중: {len(self.pose_window)}/{config.WINDOW_SIZE}",
                should_emit_ui=self.should_emit_ui(),
                posture_type=self.latest_posture_type,
                confidence=self.latest_confidence,
                fatigue_label=self.latest_fatigue_label,
                fatigue_probability=self.latest_fatigue_probability,
                elapsed_sec=elapsed_sec,
                rank_text=self.build_rank_text(),
            )
        else :
            return InferenceResult(
                success=True,
                message=f"GRU 입력 수집 중: {len(self.pose_window)}/{config.WINDOW_SIZE}",
                should_emit_ui=self.should_emit_ui(),
                posture_type=self.latest_posture_type,
                confidence=self.latest_confidence,
                fatigue_label=self.latest_fatigue_label,
                fatigue_probability=self.latest_fatigue_probability,
                elapsed_sec=elapsed_sec,
                rank_text=self.build_rank_text(),
            )


        # try:
        #     posture_type, posture_confidence = self.predict_pose()
        #     fatigue_label, fatigue_probability = self.predict_face()

        # except Exception as e:
        #     return InferenceResult(
        #         success=False,
        #         message=f"GRU 추론 오류: {e}"
        #     )

        # self.latest_posture_type = posture_type
        # self.latest_confidence = posture_confidence
        # self.latest_fatigue_label = fatigue_label
        # self.latest_fatigue_probability = fatigue_probability

        # normal_label = self.labels.get(0, "Optimal")

        # if posture_type != normal_label:
        #     self.posture_counter[posture_type] += 1

        # should_emit_ui = self.should_emit_ui()

        # if should_emit_ui:
        #     self.save_log(
        #         posture_type=posture_type,
        #         fatigue_label=fatigue_label,
        #         fatigue_probability=fatigue_probability,
        #     )

        # return InferenceResult(
        #     success=True,
        #     message=f"GRU 측정 중: {posture_type} / {posture_confidence * 100:.1f}%",
        #     should_emit_ui=should_emit_ui,
        #     posture_type=posture_type,
        #     confidence=posture_confidence,
        #     fatigue_label=fatigue_label,
        #     fatigue_probability=fatigue_probability,
        #     elapsed_sec=elapsed_sec,
        #     rank_text=self.build_rank_text(),
        # )

    # ---------------------------------------------------------
    # Feature
    # ---------------------------------------------------------
    def build_pose_features(self, pose_features):
        if pose_features is None:
            return [0.0] * config.POSE_FEATURE_SIZE

        pose_features = list(pose_features)

        if len(pose_features) != config.POSE_FEATURE_SIZE:
            return [0.0] * config.POSE_FEATURE_SIZE

        return pose_features

    def build_face_features(self, results_face):
        if results_face is None:
            return [0.0] * config.FACE_FEATURE_SIZE

        if not hasattr(results_face, "face_blendshapes"):
            return [0.0] * config.FACE_FEATURE_SIZE

        face_features = calculate_face_features_for_window(
            results_face.face_blendshapes
        )

        if face_features is None:
            return [0.0] * config.FACE_FEATURE_SIZE

        if len(face_features) != config.FACE_FEATURE_SIZE:
            return [0.0] * config.FACE_FEATURE_SIZE

        return face_features

    # ---------------------------------------------------------
    # Predict
    # ---------------------------------------------------------
    def predict_pose(self):
        model_input = np.asarray(self.pose_window, dtype=np.float32)

        # 팀원 코드 기준: [WINDOW_SIZE, FEATURE_SIZE]에서 scaler 적용

        model_input = model_input.reshape(1, -1)  # 2D 형태로 변환
        model_input = self.pose_scaler.transform(model_input)
        input_tensor = model_input.reshape(1 ,config.WINDOW_SIZE, config.POSE_FEATURE_SIZE)

        self.pose_interpreter.set_tensor(
            self.pose_input_details[0]["index"],
            input_tensor
        )
        self.pose_interpreter.invoke()

        output = self.pose_interpreter.get_tensor(
            self.pose_output_details[0]["index"]
        )

        label_index, confidence = self.parse_output_pose(output)

        label = self.labels.get(label_index, f"Unknown({label_index})")

        # print(f"Pose_Confidence : {confidence}")
        # print(f"Pose_label_index : {label_index}")
        # print(f"Pose_label : {label}")

        return label, confidence

    def predict_face(self):
        model_input = np.asarray(self.face_window, dtype=np.float32)

        # model_input = self.face_scaler.transform(model_input.flatten())
        # # input_tensor = np.expand_dims(model_input, axis=0).astype(np.float32)
        # input_tensor = model_input.reshape(config.WINDOW_SIZE, config.FACE_FEATURE_SIZE)

        model_input = model_input.reshape(1, -1)  # 2D 형태로 변환
        model_input = self.face_scaler.transform(model_input)
        input_tensor = model_input.reshape(1 ,config.WINDOW_SIZE, config.FACE_FEATURE_SIZE)

        self.face_interpreter.set_tensor(
            self.face_input_details[0]["index"],
            input_tensor
        )
        self.face_interpreter.invoke()

        output = self.face_interpreter.get_tensor(
            self.face_output_details[0]["index"]
        )

        label_index, confidence = self.parse_output(output)
        
        label = self.face_labels.get(label_index, f"Unknown({label_index})")

        # print(f"face_Confidence : {confidence}")
        # print(f"face_label_index : {label_index}")
        # print(f"face_label : {label}")

        return label, confidence
    


    def parse_output_pose(self, output):
        """
        TFLite 출력 형태를 label_index / confidence로 변환한다.

        지원:
        - [[0.1, 0.9]] 같은 softmax 배열
        - [[0.87]] 같은 단일 확률
        """

        output = np.asarray(output)
        probs = np.squeeze(output)

        # hand_visible = output[-1]
        # probs = np.squeeze(output)

        # if len(probs) > 3 and hand_visible == 0:
        #     probs[3] = 0

        # 단일 확률 출력
        if probs.ndim == 0:
            probability = float(probs)
            label_index = 1 if probability >= 0.5 else 0
            confidence = probability if label_index == 1 else 1.0 - probability
            return label_index, confidence

        if probs.ndim == 1 and probs.shape[0] == 1:
            probability = float(probs[0])
            label_index = 1 if probability >= 0.5 else 0
            confidence = probability if label_index == 1 else 1.0 - probability
            return label_index, confidence

        # softmax 출력
        label_index = int(np.argmax(probs))
        confidence = float(probs[label_index])


        return label_index, confidence



    def parse_output(self, output):
        """
        TFLite 출력 형태를 label_index / confidence로 변환한다.

        지원:
        - [[0.1, 0.9]] 같은 softmax 배열
        - [[0.87]] 같은 단일 확률
        """

        output = np.asarray(output)
        probs = np.squeeze(output)

        # 단일 확률 출력
        if probs.ndim == 0:
            probability = float(probs)
            label_index = 1 if probability >= 0.5 else 0
            confidence = probability if label_index == 1 else 1.0 - probability
            return label_index, confidence

        if probs.ndim == 1 and probs.shape[0] == 1:
            probability = float(probs[0])
            label_index = 1 if probability >= 0.5 else 0
            confidence = probability if label_index == 1 else 1.0 - probability
            return label_index, confidence

        # softmax 출력
        label_index = int(np.argmax(probs))
        confidence = float(probs[label_index])


        return label_index, confidence

    # ---------------------------------------------------------
    # Helper
    # ---------------------------------------------------------
    def get_elapsed_sec(self):
        if self.session_start_time is None:
            return 0

        return int(time.time() - self.session_start_time)

    def should_emit_ui(self):
        now = time.time()

        if now - self.last_ui_emit_time < self.ui_emit_interval:
            return False

        self.last_ui_emit_time = now
        return True

    def build_rank_text(self):
        total_count = sum(self.posture_counter.values())

        if total_count <= 0:
            return (
                "불안정 자세 TOP 3\n\n"
                "1위  -\n"
                "2위  -\n"
                "3위  -"
            )

        top_3 = self.posture_counter.most_common(3)

        lines = ["불안정 자세 TOP 3", ""]

        for index in range(3):
            if index < len(top_3):
                posture_type, count = top_3[index]
                ratio = count / total_count * 100
                lines.append(
                    f"{index + 1}위  {posture_type}  {count}회  {ratio:.1f}%"
                )
            else:
                lines.append(f"{index + 1}위  -")

        return "\n".join(lines)

    def save_log(self, posture_type, fatigue_label, fatigue_probability):
        if not self.enable_logging:
            return

        if self.logger is None:
            return

        self.logger.save({
            "posture_type": posture_type,
            "fatigue_label": fatigue_label,
            "fatigue_probability": float(fatigue_probability),
        })

    def load_baseline(self, path, feature_size, name="baseline"):
        if os.path.exists(path):
            print(f"{name} 기준값 로드 완료: {path}")
            
            baseline = joblib.load(path)
            baseline = np.asarray(baseline, dtype=np.float32)

            if baseline.size != feature_size:
                print(f"{name} 기준값 개수 불일치: "
                    f"현재={baseline.size}, 필요={feature_size}. 0으로 대체합니다.")
                return np.zeros(feature_size, dtype=np.float32)

            return baseline

        else:
            print(f"{name} 기준값 파일이 없어 모든 피처를 0으로 초기화합니다.")
            return np.zeros(feature_size, dtype=np.float32)
