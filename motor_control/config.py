"""
motor_control/config.py

[역할]
motor_control 패키지 전체에서 공통으로 사용하는 설정값과
팀원용 모터 제어 방향 기준을 정의한다.

------------------------------------------------------------
[최종 팀원용 방향 기준 - 중요]

shoulder_lift
    +각도 = 위
    -각도 = 아래

elbow_flex
    +각도 = 위
    -각도 = 아래

wrist_flex
    +각도 = 위
    -각도 = 아래

wrist_roll
    +각도 = CCW (반시계 방향)
    -각도 = CW  (시계 방향)

------------------------------------------------------------
[Calibration direction과의 차이]

servo_calibration_result.json의 direction:

    URDF +각도와
    STS raw Position 증가/감소의 관계

이 파일의 COMMAND_TO_URDF_DIRECTION:

    팀원이 입력한 + / - 각도를
    URDF + / - 각도로 어떻게 변환할지 결정

두 값은 역할이 다르므로 혼동하면 안 된다.
"""

import os


# ============================================================
# 1. 프로젝트 경로
# ============================================================

PACKAGE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_ROOT = os.path.dirname(
    PACKAGE_DIR
)


# Calibration 결과 JSON
CALIBRATION_FILE = os.path.join(
    PROJECT_ROOT,
    "servo_calibration_result.json"
)


# STServo Python SDK
SDK_PATH = os.path.join(
    PROJECT_ROOT,
    "STServo_Python",
    "stservo-env",
    "scservo_sdk"
)


# ============================================================
# 2. Serial 기본 설정
# ============================================================
#
# Calibration JSON 안에 device / baudrate가 존재하면
# 그 값을 우선 사용한다.
#
# 아래 값은 JSON에 정보가 없을 때 사용하는 기본값이다.

DEFAULT_DEVICE = "/dev/ttyACM0"
DEFAULT_BAUDRATE = 1000000


# ============================================================
# 3. STS Position 기준
# ============================================================

STS_POSITION_MIN = 0
STS_POSITION_MAX = 4095

STS_POSITION_RESOLUTION = 4096


# 1도당 약 11.377... Position
POSITION_PER_DEGREE = (
    STS_POSITION_RESOLUTION
    / 360.0
)


# Position 1당 약 0.08789도
DEGREE_PER_POSITION = (
    360.0
    / STS_POSITION_RESOLUTION
)


# ============================================================
# 4. 팀원 입력 각도 -> URDF 각도 방향 변환
# ============================================================
#
# 값 의미:
#
# +1
#     팀원 +각도 = URDF +각도
#
# -1
#     팀원 +각도 = URDF -각도
#
#
# ------------------------------------------------------------
# shoulder_lift
#
# 현재 URDF +방향 = 아래
# 팀원 +방향      = 위
#
# 따라서 -1
# ------------------------------------------------------------
#
# elbow_flex
#
# 현재 URDF +방향 = 아래
# 팀원 +방향      = 위
#
# 따라서 -1
# ------------------------------------------------------------
#
# wrist_flex
#
# 현재 URDF +방향 = 아래
# 팀원 +방향      = 위
#
# 따라서 -1
# ------------------------------------------------------------
#
# wrist_roll
#
# 실제 테스트:
#
# raw Position 증가 = CW
# raw Position 감소 = CCW
#
# Calibration direction = -1
#
# 따라서 URDF +각도:
#
# raw Position 감소
# -> CCW
#
# 팀원 +각도 역시 CCW로 사용하기로 확정했으므로
#
# 팀원 + = URDF +
#
# 따라서 +1
# ------------------------------------------------------------

COMMAND_TO_URDF_DIRECTION = {

    "shoulder_lift": -1,

    "elbow_flex": -1,

    "wrist_flex": -1,

    "wrist_roll": +1,
}


# ============================================================
# 5. 사람이 이해하기 쉬운 방향 설명
# ============================================================

COMMAND_DIRECTION_DESCRIPTION = {

    "shoulder_lift": {
        "positive": "위",
        "negative": "아래",
    },

    "elbow_flex": {
        "positive": "위",
        "negative": "아래",
    },

    "wrist_flex": {
        "positive": "위",
        "negative": "아래",
    },

    "wrist_roll": {
        "positive": "CCW",
        "negative": "CW",
    },
}


# ============================================================
# 6. 팀원 +각도 명령 시 예상 raw Position 방향
# ============================================================
#
# 프로그램 시작 시 Direction 설정 오류를 잡기 위한 값.
#
# +1
#     raw Position 증가
#
# -1
#     raw Position 감소
#
#
# shoulder / elbow / wrist_flex
#
# 팀원 + = 위
# 실제 raw Position 감소 = 위
#
# 따라서 -1
#
#
# wrist_roll
#
# 팀원 + = CCW
# 실제 raw Position 감소 = CCW
#
# 따라서 -1

EXPECTED_RAW_SIGN_FOR_POSITIVE_COMMAND = {

    "shoulder_lift": -1,

    "elbow_flex": -1,

    "wrist_flex": -1,

    "wrist_roll": -1,
}


# ============================================================
# 7. Acceleration 기본값
# ============================================================
#
# acc는 선택 인자.
#
# 팀원이 입력하지 않으면 10을 사용한다.

DEFAULT_ACC = 10


# STS Acc 입력 허용 범위
MIN_ACC = 0
MAX_ACC = 254


# ============================================================
# 8. wait 기본 설정
# ============================================================

DEFAULT_WAIT = True


# ============================================================
# 9. 목표 도착 확인 설정
# ============================================================

DEFAULT_TIMEOUT_SEC = 5.0

POSITION_TOLERANCE = 5

POLL_INTERVAL_SEC = 0.05