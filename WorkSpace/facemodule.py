# facemodule.py

from dataclasses import dataclass
from collections import deque
from typing import Dict, List
import time


@dataclass
class FaceFeatures:
    # 기본 상태
    face_detected: bool

    # 눈 관련 feature
    eye_blink_left: float
    eye_blink_right: float
    eye_closed_score: float
    eye_closed_duration: float

    # 입 / 하품 관련 feature
    jaw_open: float
    mouth_open_duration: float
    yawn_count_window: int

    # 얼굴 미검출 시간
    no_face_duration: float

    # 모델 입력용 보조 점수
    fatigue_feature_score: float


class FaceModule:
    """
    FaceLandmarker 결과(face_res)에서
    피로도 판단 모델에 넣을 수 있는 feature를 추출하는 모듈.

    이 클래스는 최종 라벨을 판단하는 모델이 아니라,
    모델에 넣을 입력값을 만드는 역할이다.
    """

    MODEL_FEATURE_ORDER = [
        "eye_blink_left",
        "eye_blink_right",
        "eye_closed_score",
        "eye_closed_duration",
        "jaw_open",
        "mouth_open_duration",
        "yawn_count_window",
        "no_face_duration",
        "fatigue_feature_score",
    ]

    def __init__(
        self,
        eye_closed_threshold: float = 0.55,
        mouth_open_threshold: float = 0.45,
        yawn_min_duration: float = 1.0,
        window_sec: float = 60.0,
    ):
        self.eye_closed_threshold = eye_closed_threshold
        self.mouth_open_threshold = mouth_open_threshold
        self.yawn_min_duration = yawn_min_duration
        self.window_sec = window_sec

        self.eye_closed_duration = 0.0
        self.mouth_open_duration = 0.0
        self.no_face_duration = 0.0

        self.yawn_events = deque()
        self._yawn_counted = False

        self._last_time = None

    def update(self, face_res, dt: float | None = None) -> FaceFeatures:
        """
        매 프레임마다 호출하는 함수.

        Parameters
        ----------
        face_res:
            MediaPipe FaceLandmarker의 detect 결과

        dt:
            이전 프레임과 현재 프레임 사이의 시간.
            main.py에서 계산해서 넣어주는 것을 추천.
        """

        now = time.time()

        if dt is None:
            if self._last_time is None:
                dt = 0.0
            else:
                dt = now - self._last_time

        self._last_time = now

        # 너무 큰 dt가 들어오면 누적값이 튀는 것을 방지
        dt = max(0.0, min(dt, 0.5))

        if not face_res or not face_res.face_landmarks:
            return self._handle_no_face(dt)

        scores = self._get_blendshape_scores(face_res)

        eye_blink_left = scores.get("eyeBlinkLeft", 0.0)
        eye_blink_right = scores.get("eyeBlinkRight", 0.0)
        jaw_open = scores.get("jawOpen", 0.0)

        eye_closed_score = (eye_blink_left + eye_blink_right) / 2.0

        is_eye_closed = eye_closed_score >= self.eye_closed_threshold
        is_mouth_open = jaw_open >= self.mouth_open_threshold

        if is_eye_closed:
            self.eye_closed_duration += dt
        else:
            self.eye_closed_duration = 0.0

        if is_mouth_open:
            self.mouth_open_duration += dt

            if self.mouth_open_duration >= self.yawn_min_duration and not self._yawn_counted:
                self.yawn_events.append(now)
                self._yawn_counted = True
        else:
            self.mouth_open_duration = 0.0
            self._yawn_counted = False

        self.no_face_duration = 0.0
        self._remove_old_yawn_events(now)

        fatigue_feature_score = self._calculate_debug_fatigue_score(
            eye_closed_duration=self.eye_closed_duration,
            jaw_open=jaw_open,
            yawn_count=len(self.yawn_events),
        )

        return FaceFeatures(
            face_detected=True,
            eye_blink_left=eye_blink_left,
            eye_blink_right=eye_blink_right,
            eye_closed_score=eye_closed_score,
            eye_closed_duration=self.eye_closed_duration,
            jaw_open=jaw_open,
            mouth_open_duration=self.mouth_open_duration,
            yawn_count_window=len(self.yawn_events),
            no_face_duration=self.no_face_duration,
            fatigue_feature_score=fatigue_feature_score,
        )

    def to_model_input(self, features: FaceFeatures) -> List[float]:
        """
        머신러닝 / 딥러닝 모델에 넣기 좋은 고정 순서 리스트로 변환한다.
        나중에 MLP, GRU, RandomForest 등에 그대로 넣기 좋다.
        """

        return [
            float(getattr(features, name))
            for name in self.MODEL_FEATURE_ORDER
        ]

    def get_feature_names(self) -> List[str]:
        return self.MODEL_FEATURE_ORDER.copy()

    def _get_blendshape_scores(self, face_res) -> Dict[str, float]:
        """
        MediaPipe face_blendshapes 결과를
        {이름: 점수} 딕셔너리로 변환한다.
        """

        if not face_res.face_blendshapes:
            return {}

        blendshapes = face_res.face_blendshapes[0]

        return {
            category.category_name: float(category.score)
            for category in blendshapes
        }

    def _handle_no_face(self, dt: float) -> FaceFeatures:
        """
        얼굴이 감지되지 않았을 때 처리.
        """

        self.no_face_duration += dt
        self.eye_closed_duration = 0.0
        self.mouth_open_duration = 0.0
        self._yawn_counted = False

        return FaceFeatures(
            face_detected=False,
            eye_blink_left=0.0,
            eye_blink_right=0.0,
            eye_closed_score=0.0,
            eye_closed_duration=self.eye_closed_duration,
            jaw_open=0.0,
            mouth_open_duration=self.mouth_open_duration,
            yawn_count_window=len(self.yawn_events),
            no_face_duration=self.no_face_duration,
            fatigue_feature_score=0.0,
        )

    def _remove_old_yawn_events(self, now: float):
        """
        최근 window_sec초 안의 하품 이벤트만 유지한다.
        기본값은 최근 60초.
        """

        while self.yawn_events and now - self.yawn_events[0] > self.window_sec:
            self.yawn_events.popleft()

    def _calculate_debug_fatigue_score(
        self,
        eye_closed_duration: float,
        jaw_open: float,
        yawn_count: int,
    ) -> float:
        """
        모델 학습 전 확인용 피로도 feature 점수.

        최종 라벨 판단용 if문이 아니라,
        feature가 정상적으로 쌓이는지 보기 위한 보조 수치다.
        """

        eye_duration_score = min(eye_closed_duration / 3.0, 1.0)
        mouth_score = min(jaw_open, 1.0)
        yawn_score = min(yawn_count / 3.0, 1.0)

        score = (
            eye_duration_score * 0.5
            + yawn_score * 0.3
            + mouth_score * 0.2
        )

        return round(score, 4)