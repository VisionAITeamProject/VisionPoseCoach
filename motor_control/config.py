"""
motor_control/config.py

[역할]
motor_control 패키지 전체에서 공통으로 사용하는 설정값과
팀원용 모터 제어 방향 기준을 정의한다.

[최종 팀원용 방향]
- shoulder_lift : + = 위,   - = 아래
- elbow_flex    : + = 위,   - = 아래
- wrist_flex    : + = 위,   - = 아래
- wrist_roll    : + = CCW,  - = CW

주의:
servo_calibration_result.json의 direction은 "URDF 각도 ↔ raw Position" 관계이고,
COMMAND_TO_URDF_DIRECTION은 "팀원용 각도 ↔ URDF 각도" 관계이다.
둘은 서로 다른 값이다.
"""

import os


# ============================================================
# 1. 프로젝트 경로
# ============================================================

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

CALIBRATION_FILE = os.path.join(
    PROJECT_ROOT,
    "servo_calibration_result.json",
)

SDK_PATH = os.path.join(
    PROJECT_ROOT,
    "STServo_Python",
    "stservo-env",
    "scservo_sdk",
)


# ============================================================
# 2. Serial 기본 설정
# ============================================================
# Calibration JSON에 device / baudrate가 있으면 그 값을 우선 사용한다.

DEFAULT_DEVICE = "/dev/ttyACM0"
DEFAULT_BAUDRATE = 1_000_000


# ============================================================
# 3. STS Position 기준
# ============================================================

STS_POSITION_MIN = 0
STS_POSITION_MAX = 4095
STS_POSITION_RESOLUTION = 4096

POSITION_PER_DEGREE = STS_POSITION_RESOLUTION / 360.0
DEGREE_PER_POSITION = 360.0 / STS_POSITION_RESOLUTION


# ============================================================
# 4. 팀원 입력 각도 -> URDF 각도 방향
# ============================================================
# +1 : 팀원 +각도 = URDF +각도
# -1 : 팀원 +각도 = URDF -각도
#
# wrist_roll은 실물 재확인 결과:
#   raw 증가 = CW
#   raw 감소 = CCW
#   calibration direction = -1
#
# 따라서 URDF + -> raw 감소 -> CCW이고,
# 팀원 +도 CCW이므로 wrist_roll은 +1이다.

COMMAND_TO_URDF_DIRECTION = {
    "shoulder_lift": -1,
    "elbow_flex": -1,
    "wrist_flex": -1,
    "wrist_roll": +1,
}


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
# 5. 팀원 +각도 명령 시 예상 raw Position 변화 방향
# ============================================================
#
# +1 : raw Position 증가
# -1 : raw Position 감소
#
# 현재 네 관절 모두 팀원 +명령 시
# raw Position이 감소해야 한다.

EXPECTED_RAW_SIGN_FOR_POSITIVE_COMMAND = {
    "shoulder_lift": -1,
    "elbow_flex": -1,
    "wrist_flex": -1,
    "wrist_roll": -1,
}


# ============================================================
# 6. 제어 기본값
# ============================================================

# acc는 선택 인자이며 생략하면 10을 사용한다.
DEFAULT_ACC = 10

MIN_ACC = 0
MAX_ACC = 254


# wait 기본값
DEFAULT_WAIT = True


# wait=True 목표 도착 제한시간
DEFAULT_TIMEOUT_SEC = 5.0


# 목표 위치 도착으로 인정할 raw Position 오차
POSITION_TOLERANCE = 5


# 목표 도착 확인 주기
POLL_INTERVAL_SEC = 0.05


# ============================================================
# 7. Emergency Stop / Torque 설정
# ============================================================
#
# STS3215 계열 Torque Enable SRAM 주소
#
# 0 = Torque OFF
# 1 = Torque ON
#
# 현재 공개 API의 emergency_stop()은
# TORQUE_OFF만 사용한다.
#
# Torque ON 복구는 실제 기구에서
# 안전 복구 절차를 검증한 뒤 추가한다.

ADDR_TORQUE_ENABLE = 40

TORQUE_OFF = 0
TORQUE_ON = 1