#!/usr/bin/env python

"""
servo_calibration.py

[역할]
Raspberry Pi 터미널에서 STS Servo 4개를 직접 수동 조작하면서
실제 로봇팔의 안전 가동범위를 확인하고 저장하기 위한
Calibration 프로그램.

------------------------------------------------------------
[사용 Joint]

Servo ID 1 -> shoulder_lift
Servo ID 2 -> elbow_flex
Servo ID 3 -> wrist_flex
Servo ID 4 -> wrist_roll

사용하지 않는 Joint:
- shoulder_pan
- gripper

------------------------------------------------------------
[이미 실제 테스트로 확인된 Direction]

Servo ID 1 -> direction = +1
Servo ID 2 -> direction = +1
Servo ID 3 -> direction = +1
Servo ID 4 -> direction = -1

direction = +1
    STS Position 증가 방향
    =
    URDF Joint +각도 방향

direction = -1
    STS Position 감소 방향
    =
    URDF Joint +각도 방향

------------------------------------------------------------
[터미널 수동 조작]

1 / 2 / 3 / 4
    -> 조작할 Servo 선택

i
    -> 현재 선택 Joint의 URDF +방향으로 Step 이동

o
    -> 현재 선택 Joint의 URDF -방향으로 Step 이동

step 20
    -> 이동 Step 변경

speed 100
    -> 이동 속도 변경

z
    -> 현재 위치를 Zero Position으로 변경하고 JSON에 즉시 저장

0
    -> Zero Position으로 복귀

min
    -> 현재 위치를 URDF Min 방향의 실제 안전 한계로 변경하고 JSON에 즉시 저장

max
    -> 현재 위치를 URDF Max 방향의 실제 안전 한계로 변경하고 JSON에 즉시 저장

s
    -> 현재 상태 확인

all
    -> Servo 1~4 전체 상태 확인

save
    -> Calibration JSON 저장

x
    -> 현재 위치에서 즉시 Hold 명령

h
    -> 명령어 도움말

q
    -> 저장 후 종료

------------------------------------------------------------
[안전 설계]

Zero Position이 설정되지 않은 Servo는 이동하지 않는다.

Zero Position 설정 후에는 SO101 URDF의 Joint Limit을 계산하고,
그 범위를 벗어나는 Position 명령은 차단한다.

실제 안전 Min/Max를 저장한 이후에는
URDF 한계보다 실제 안전 한계를 우선 적용한다.

따라서 실제 기구 간섭이 URDF 한계보다 먼저 발생하는 경우
그 위치를 안전 한계로 저장하면 이후에는 더 이상
그 위치를 넘어가지 않는다.

------------------------------------------------------------
[JSON 저장 시점]

다음 명령은 Calibration 값을 변경한 직후
servo_calibration_result.json 파일을 즉시 덮어써서 저장한다.

z
    -> Zero Position 변경 + 즉시 저장

min
    -> Safe MIN 변경 + 즉시 저장

max
    -> Safe MAX 변경 + 즉시 저장

save
    -> 현재 Calibration 값 수동 저장

q
    -> 현재 Calibration 값을 한 번 더 저장한 뒤 종료

반대로 다음 명령은 모터만 조작하거나 상태만 확인하며
Calibration 값 자체는 변경하지 않는다.

1 / 2 / 3 / 4
i / o
step
speed
0
s
all
x
"""

import sys
import os
import math
import json
import time
from datetime import datetime


# ============================================================
# 1. STServo Python SDK 경로
# ============================================================

sdk_path = os.path.abspath(
    "./STServo_Python/stservo-env/scservo_sdk"
)

if sdk_path not in sys.path:
    sys.path.append(sdk_path)


# ============================================================
# 2. STServo SDK
# ============================================================

from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import *


# ============================================================
# 3. Serial 통신 설정
# ============================================================

DEVICENAME = "/dev/ttyACM0"
BAUDRATE = 1000000


# ============================================================
# 4. STS Position 기준
# ============================================================
#
# STS:
#
# 0 ~ 4095
# 4096 step = 360 degree
#
# 따라서 약:
#
# 1 step = 0.08789 degree

STS_POSITION_MIN = 0
STS_POSITION_MAX = 4095

STS_POSITION_RESOLUTION = 4096

POSITION_PER_RAD = (
    STS_POSITION_RESOLUTION
    / (2.0 * math.pi)
)

RAD_PER_POSITION = (
    2.0 * math.pi
    / STS_POSITION_RESOLUTION
)


# ============================================================
# 5. Servo Calibration 설정
# ============================================================

SERVO_CONFIG = {

    1: {
        "joint": "shoulder_lift",

        "urdf_min_angle_rad": -1.74533,
        "urdf_max_angle_rad": 1.74533,

        # 실제 Direction 테스트 결과
        "direction": +1,

        # 실제 로봇에서 확인한 물리적 움직임
        "raw_position_increase_motion": "팔 끝단이 아래 방향으로 이동",
        "raw_position_decrease_motion": "팔 끝단이 위 방향으로 이동",
        "direction_reference": "로봇 정면/측면에서 shoulder_lift 움직임 기준",

        "zero_position": None,

        "position_at_urdf_min_angle": None,
        "position_at_urdf_max_angle": None,

        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,

        "max_speed": None,
    },

    2: {
        "joint": "elbow_flex",

        "urdf_min_angle_rad": -1.69,
        "urdf_max_angle_rad": 1.69,

        "direction": +1,

        # 실제 로봇에서 확인한 물리적 움직임
        "raw_position_increase_motion": "팔꿈치 이후 링크와 끝단이 아래 방향으로 이동",
        "raw_position_decrease_motion": "팔꿈치 이후 링크와 끝단이 위 방향으로 이동",
        "direction_reference": "elbow_flex 관절 이후 링크 움직임 기준",

        "zero_position": None,

        "position_at_urdf_min_angle": None,
        "position_at_urdf_max_angle": None,

        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,

        "max_speed": None,
    },

    3: {
        "joint": "wrist_flex",

        "urdf_min_angle_rad": -1.65806,
        "urdf_max_angle_rad": 1.65806,

        "direction": +1,

        # 실제 로봇에서 확인한 물리적 움직임
        "raw_position_increase_motion": "손목 끝단이 아래 방향으로 이동",
        "raw_position_decrease_motion": "손목 끝단이 위 방향으로 이동",
        "direction_reference": "wrist_flex 굽힘/펴짐 움직임 기준",

        "zero_position": None,

        "position_at_urdf_min_angle": None,
        "position_at_urdf_max_angle": None,

        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,

        "max_speed": None,
    },

    4: {
        "joint": "wrist_roll",

        "urdf_min_angle_rad": -2.74385,
        "urdf_max_angle_rad": 2.84121,

        # 최종 직접 실측 결과
        # 관찰 기준: 모니터가 위치한 정면에서 로봇팔을 바라보는 기준
        # raw Position 증가 -> CW
        # raw Position 감소 -> CCW
        #
        # direction = -1 이므로
        # URDF + -> raw Position 감소 -> CCW
        # URDF - -> raw Position 증가 -> CW
        "direction": -1,

        # wrist_roll은 보는 방향에 따라 CW/CCW가 달라지므로
        # 반드시 실제 측정에 사용한 관찰 기준을 함께 저장한다.
        "raw_position_increase_motion": "CW",
        "raw_position_decrease_motion": "CCW",
        "direction_reference": "모니터가 위치한 정면에서 로봇팔을 바라보는 기준",

        "zero_position": None,

        "position_at_urdf_min_angle": None,
        "position_at_urdf_max_angle": None,

        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,

        "max_speed": None,
    },
}


SERVO_IDS = [1, 2, 3, 4]


# ============================================================
# 6. STS 상태 레지스터
# ============================================================

ADDR_PRESENT_LOAD = 60
ADDR_PRESENT_VOLTAGE = 62
ADDR_PRESENT_TEMPERATURE = 63
ADDR_MOVING = 66
ADDR_PRESENT_CURRENT = 69


# ============================================================
# 7. 기본 수동 조작 설정
# ============================================================

DEFAULT_STEP = 20

DEFAULT_SPEED = 100
DEFAULT_ACC = 10


manual_step = DEFAULT_STEP
manual_speed = DEFAULT_SPEED
manual_acc = DEFAULT_ACC


# ============================================================
# 8. Calibration 저장 파일
# ============================================================

CALIBRATION_FILE = (
    "servo_calibration_result.json"
)


# ============================================================
# 9. 초기 상태 저장
# ============================================================

initial_states = {}


# ============================================================
# 10. STServo 통신 객체
# ============================================================

portHandler = PortHandler(
    DEVICENAME
)

packetHandler = sms_sts(
    portHandler
)


# ============================================================
# 11. Angle -> STS Position
# ============================================================

def angle_to_position(
    zero_position,
    direction,
    angle_rad
):

    position = (
        zero_position
        + direction
        * angle_rad
        * POSITION_PER_RAD
    )

    return int(
        round(position)
    )


# ============================================================
# 12. STS Position -> Joint Angle
# ============================================================

def position_to_angle(
    position,
    zero_position,
    direction
):

    return (
        (position - zero_position)
        * direction
        * RAD_PER_POSITION
    )


# ============================================================
# 13. URDF Position Limit 계산
# ============================================================

def calculate_urdf_limits(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    zero = config[
        "zero_position"
    ]


    if zero is None:

        return False


    direction = config[
        "direction"
    ]


    # --------------------------------------------------------
    # URDF Min Angle이 실제 STS에서는 몇 Position인지 계산
    # --------------------------------------------------------

    min_position = (
        angle_to_position(
            zero,
            direction,
            config[
                "urdf_min_angle_rad"
            ]
        )
    )


    # --------------------------------------------------------
    # URDF Max Angle
    # --------------------------------------------------------

    max_position = (
        angle_to_position(
            zero,
            direction,
            config[
                "urdf_max_angle_rad"
            ]
        )
    )


    # --------------------------------------------------------
    # STS 자체 범위 보호
    # --------------------------------------------------------

    min_position = max(
        STS_POSITION_MIN,
        min(
            STS_POSITION_MAX,
            min_position
        )
    )


    max_position = max(
        STS_POSITION_MIN,
        min(
            STS_POSITION_MAX,
            max_position
        )
    )


    config[
        "position_at_urdf_min_angle"
    ] = min_position


    config[
        "position_at_urdf_max_angle"
    ] = max_position


    return True


# ============================================================
# 14. Servo 상태 읽기
# ============================================================

def read_servo_state(
    servo_id
):

    state = {}


    # --------------------------------------------------------
    # Position
    # --------------------------------------------------------

    position, result, error = (
        packetHandler.ReadPos(
            servo_id
        )
    )


    if (
        result != COMM_SUCCESS
        or error != 0
    ):

        return None


    state[
        "position"
    ] = position


    # --------------------------------------------------------
    # Speed
    # --------------------------------------------------------

    speed, result, error = (
        packetHandler.ReadSpeed(
            servo_id
        )
    )


    if (
        result == COMM_SUCCESS
        and error == 0
    ):

        state[
            "speed"
        ] = speed

    else:

        state[
            "speed"
        ] = None


    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    load_raw, result, error = (
        packetHandler.read2ByteTxRx(
            servo_id,
            ADDR_PRESENT_LOAD
        )
    )


    if (
        result == COMM_SUCCESS
        and error == 0
    ):

        load_value = (
            load_raw & 0x03FF
        )


        if load_raw & 0x0400:

            load_value = (
                -load_value
            )


        state[
            "load"
        ] = load_value


        state[
            "load_percent"
        ] = (
            abs(load_value)
            / 1000.0
            * 100.0
        )


    else:

        state[
            "load"
        ] = None

        state[
            "load_percent"
        ] = None


    # --------------------------------------------------------
    # Voltage
    # --------------------------------------------------------

    voltage_raw, result, error = (
        packetHandler.read1ByteTxRx(
            servo_id,
            ADDR_PRESENT_VOLTAGE
        )
    )


    if (
        result == COMM_SUCCESS
        and error == 0
    ):

        state[
            "voltage"
        ] = (
            voltage_raw
            * 0.1
        )


    else:

        state[
            "voltage"
        ] = None


    # --------------------------------------------------------
    # Temperature
    # --------------------------------------------------------

    temperature, result, error = (
        packetHandler.read1ByteTxRx(
            servo_id,
            ADDR_PRESENT_TEMPERATURE
        )
    )


    if (
        result == COMM_SUCCESS
        and error == 0
    ):

        state[
            "temperature"
        ] = temperature


    else:

        state[
            "temperature"
        ] = None


    # --------------------------------------------------------
    # Current
    # --------------------------------------------------------

    current_raw, result, error = (
        packetHandler.read2ByteTxRx(
            servo_id,
            ADDR_PRESENT_CURRENT
        )
    )


    if (
        result == COMM_SUCCESS
        and error == 0
    ):

        state[
            "current_raw"
        ] = current_raw


        # 기존 테스트에서 사용했던 환산값 유지
        state[
            "current_ma"
        ] = (
            current_raw
            * 6.5
        )


    else:

        state[
            "current_raw"
        ] = None

        state[
            "current_ma"
        ] = None


    # --------------------------------------------------------
    # Moving
    # --------------------------------------------------------

    moving, result, error = (
        packetHandler.read1ByteTxRx(
            servo_id,
            ADDR_MOVING
        )
    )


    if (
        result == COMM_SUCCESS
        and error == 0
    ):

        state[
            "moving"
        ] = moving


    else:

        state[
            "moving"
        ] = None


    return state


# ============================================================
# 15. Servo 이동 명령
# ============================================================

def move_servo(
    servo_id,
    target_position
):

    global manual_speed
    global manual_acc


    target_position = int(
        target_position
    )


    # --------------------------------------------------------
    # STS 자체 Position 범위 검사
    # --------------------------------------------------------

    if not (
        STS_POSITION_MIN
        <= target_position
        <= STS_POSITION_MAX
    ):

        print(
            "[BLOCK] STS Position 범위를 "
            "벗어난 명령입니다."
        )

        return False


    result, error = (
        packetHandler.WritePosEx(
            servo_id,
            target_position,
            manual_speed,
            manual_acc
        )
    )


    if result != COMM_SUCCESS:

        print(
            f"[ERROR] 이동 명령 실패: "
            f"{packetHandler.getTxRxResult(result)}"
        )

        return False


    if error != 0:

        print(
            f"[ERROR] Servo Error: "
            f"{packetHandler.getRxPacketError(error)}"
        )

        return False


    return True


# ============================================================
# 16. 현재 적용할 안전 범위 계산
# ============================================================
#
# 안전 한계를 아직 직접 저장하지 않았다면
# URDF Limit을 사용한다.
#
# 안전 한계를 직접 저장했다면
# 그 값을 URDF Limit보다 우선 사용한다.

def get_active_position_limits(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    urdf_min_side = config[
        "position_at_urdf_min_angle"
    ]

    urdf_max_side = config[
        "position_at_urdf_max_angle"
    ]


    if (
        urdf_min_side is None
        or urdf_max_side is None
    ):

        return None


    # --------------------------------------------------------
    # 사용자가 직접 확인한 안전 한계가 있으면 사용
    # --------------------------------------------------------

    min_side = config[
        "safe_position_at_min_angle"
    ]


    max_side = config[
        "safe_position_at_max_angle"
    ]


    if min_side is None:

        min_side = (
            urdf_min_side
        )


    if max_side is None:

        max_side = (
            urdf_max_side
        )


    # --------------------------------------------------------
    # ID4처럼 Direction=-1이면
    #
    # URDF Min 방향 Position 숫자가
    # 더 클 수 있기 때문에
    # 최종적으로 숫자 범위를 다시 계산한다.
    # --------------------------------------------------------

    numeric_min = min(
        min_side,
        max_side
    )


    numeric_max = max(
        min_side,
        max_side
    )


    return (
        numeric_min,
        numeric_max
    )


# ============================================================
# 17. 이동 목표값 안전 검사
# ============================================================

def check_target_position(
    servo_id,
    target_position
):

    config = SERVO_CONFIG[
        servo_id
    ]


    # --------------------------------------------------------
    # Zero를 정하지 않은 상태에서는
    # 안전 범위를 계산할 수 없으므로 이동하지 않는다.
    # --------------------------------------------------------

    if config[
        "zero_position"
    ] is None:

        print()
        print(
            "[BLOCK] Zero Position이 "
            "설정되지 않았습니다."
        )

        print(
            "먼저 관절을 0 rad 자세로 맞춘 뒤 "
            "'z'를 입력하세요."
        )

        return False


    limits = (
        get_active_position_limits(
            servo_id
        )
    )


    if limits is None:

        print(
            "[BLOCK] Joint Limit 계산이 "
            "완료되지 않았습니다."
        )

        return False


    numeric_min, numeric_max = (
        limits
    )


    if target_position < numeric_min:

        print()
        print(
            "[BLOCK] 안전 최소 Position을 "
            "벗어나는 명령입니다."
        )

        print(
            f"현재 허용 범위: "
            f"{numeric_min} ~ {numeric_max}"
        )

        return False


    if target_position > numeric_max:

        print()
        print(
            "[BLOCK] 안전 최대 Position을 "
            "벗어나는 명령입니다."
        )

        print(
            f"현재 허용 범위: "
            f"{numeric_min} ~ {numeric_max}"
        )

        return False


    return True


# ============================================================
# 18. Servo 상태 출력
# ============================================================

def print_servo_status(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    state = read_servo_state(
        servo_id
    )


    print()
    print(
        "=================================================="
    )

    print(
        f" Servo ID {servo_id} "
        f"- {config['joint']}"
    )

    print(
        "=================================================="
    )


    if state is None:

        print(
            "[ERROR] Servo 상태 읽기 실패"
        )

        return


    position = state[
        "position"
    ]


    print(
        f"Position       : "
        f"{position}"
    )


    # --------------------------------------------------------
    # Zero 기준 Joint Angle
    # --------------------------------------------------------

    zero = config[
        "zero_position"
    ]


    if zero is not None:

        angle_rad = (
            position_to_angle(
                position,
                zero,
                config[
                    "direction"
                ]
            )
        )


        angle_deg = math.degrees(
            angle_rad
        )


        print(
            f"Joint Angle    : "
            f"{angle_deg:+.2f} deg"
        )


    else:

        print(
            "Joint Angle    : "
            "Zero 미설정"
        )


    print(
        f"Speed          : "
        f"{state['speed']}"
    )


    if state[
        "load"
    ] is not None:

        print(
            f"Load           : "
            f"{state['load']} "
            f"({state['load_percent']:.1f} %)"
        )


    else:

        print(
            "Load           : -"
        )


    if state[
        "voltage"
    ] is not None:

        print(
            f"Voltage        : "
            f"{state['voltage']:.1f} V"
        )


    else:

        print(
            "Voltage        : -"
        )


    print(
        f"Temperature    : "
        f"{state['temperature']} °C"
    )


    if state[
        "current_raw"
    ] is not None:

        print(
            f"Current        : "
            f"{state['current_raw']} raw "
            f"({state['current_ma']:.1f} mA)"
        )


    else:

        print(
            "Current        : -"
        )


    moving_text = (
        "STOPPED"
        if state[
            "moving"
        ] == 0
        else "MOVING"
    )


    print(
        f"Moving         : "
        f"{moving_text}"
    )


    print(
        "--------------------------------------------------"
    )


    print(
        f"Zero Position  : "
        f"{config['zero_position']}"
    )


    print(
        f"Direction      : "
        f"{config['direction']:+d}"
    )


    print(
        f"URDF Angle     : "
        f"{math.degrees(config['urdf_min_angle_rad']):.2f}° "
        f"~ "
        f"{math.degrees(config['urdf_max_angle_rad']):.2f}°"
    )


    print(
        f"URDF Min Pos   : "
        f"{config['position_at_urdf_min_angle']}"
    )


    print(
        f"URDF Max Pos   : "
        f"{config['position_at_urdf_max_angle']}"
    )


    print(
        f"Safe Min Side  : "
        f"{config['safe_position_at_min_angle']}"
    )


    print(
        f"Safe Max Side  : "
        f"{config['safe_position_at_max_angle']}"
    )


    limits = (
        get_active_position_limits(
            servo_id
        )
    )


    if limits is not None:

        print(
            f"Active Position Range : "
            f"{limits[0]} ~ {limits[1]}"
        )


    print(
        "=================================================="
    )


# ============================================================
# 19. 전체 Servo 상태
# ============================================================

def print_all_status():

    print()
    print(
        "=============================================================="
    )

    print(
        "                    ALL SERVO STATUS"
    )

    print(
        "=============================================================="
    )


    for servo_id in SERVO_IDS:

        config = SERVO_CONFIG[
            servo_id
        ]


        state = read_servo_state(
            servo_id
        )


        if state is None:

            print(
                f"ID {servo_id} "
                f"{config['joint']:<15} "
                f": OFFLINE"
            )

            continue


        position = state[
            "position"
        ]


        if config[
            "zero_position"
        ] is not None:

            angle = math.degrees(
                position_to_angle(
                    position,
                    config[
                        "zero_position"
                    ],
                    config[
                        "direction"
                    ]
                )
            )


            angle_text = (
                f"{angle:+7.2f}°"
            )


        else:

            angle_text = (
                "   N/A  "
            )


        print(
            f"ID {servo_id} "
            f"{config['joint']:<15} "
            f"Pos={position:<4} "
            f"Angle={angle_text} "
            f"Load={state['load']} "
            f"Temp={state['temperature']}°C"
        )


    print(
        "=============================================================="
    )


# ============================================================
# 20. 현재 위치를 Zero로 설정
# ============================================================
#
# z 명령에서 사용한다.
#
# 사용자가 y로 확인하면:
# 1. 현재 Position을 새로운 Zero Position으로 설정
# 2. 새로운 Zero 기준으로 URDF Min/Max Position 재계산
# 3. servo_calibration_result.json 파일에 즉시 저장
#
# 주의:
# z를 단순히 누르는 것만으로는 저장되지 않고,
# 확인 질문에서 y를 입력했을 때 실제 변경/저장이 이루어진다.

def set_zero_position(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    state = read_servo_state(
        servo_id
    )


    if state is None:

        print(
            "[ERROR] Position을 읽지 못했습니다."
        )

        return


    current_position = state[
        "position"
    ]


    print()
    print(
        f"[ZERO] Servo ID {servo_id} "
        f"({config['joint']})"
    )

    print(
        f"현재 Position : "
        f"{current_position}"
    )


    answer = input(
        "현재 자세가 정말 URDF 0 rad 자세입니까? "
        "[y/N]: "
    ).strip().lower()


    if answer != "y":

        print(
            "[INFO] Zero 설정 취소"
        )

        return


    config[
        "zero_position"
    ] = current_position


    calculate_urdf_limits(
        servo_id
    )


    print()
    print(
        f"[OK] Zero Position = "
        f"{current_position}"
    )


    print(
        f"[CALC] URDF Min Position = "
        f"{config['position_at_urdf_min_angle']}"
    )


    print(
        f"[CALC] URDF Max Position = "
        f"{config['position_at_urdf_max_angle']}"
    )


    save_calibration_file()


# ============================================================
# 21. URDF 방향 기준 수동 이동
# ============================================================
#
# direction_sign:
#
# +1 -> URDF +각도 방향
# -1 -> URDF -각도 방향
#
# 예:
#
# wrist_roll direction=-1
#
# 최종 실측 기준(모니터가 위치한 정면에서 관찰):
#   raw Position 증가 = CW
#   raw Position 감소 = CCW
#
# 따라서:
#   URDF + -> raw Position 감소 -> CCW
#   URDF - -> raw Position 증가 -> CW
#
# 주의: 이 i/o 수동조작은 URDF +/- 기준이며,
# 팀원용 패키지의 TEAM +/- 기준과는 별개이다.

def manual_joint_move(
    servo_id,
    direction_sign
):

    global manual_step


    config = SERVO_CONFIG[
        servo_id
    ]


    state = read_servo_state(
        servo_id
    )


    if state is None:

        print(
            "[ERROR] 현재 Servo 상태를 "
            "읽을 수 없습니다."
        )

        return


    current_position = state[
        "position"
    ]


    # --------------------------------------------------------
    # URDF 방향을 STS Position 방향으로 변환
    # --------------------------------------------------------

    raw_delta = (
        config[
            "direction"
        ]
        * direction_sign
        * manual_step
    )


    target_position = (
        current_position
        + raw_delta
    )


    if not check_target_position(
        servo_id,
        target_position
    ):

        return


    current_angle = math.degrees(
        position_to_angle(
            current_position,
            config[
                "zero_position"
            ],
            config[
                "direction"
            ]
        )
    )


    target_angle = math.degrees(
        position_to_angle(
            target_position,
            config[
                "zero_position"
            ],
            config[
                "direction"
            ]
        )
    )


    direction_text = (
        "URDF +"
        if direction_sign > 0
        else "URDF -"
    )


    print()
    print(
        f"[MOVE] {config['joint']} "
        f"{direction_text}"
    )

    print(
        f"Position : "
        f"{current_position} "
        f"-> "
        f"{target_position}"
    )

    print(
        f"Angle    : "
        f"{current_angle:+.2f}° "
        f"-> "
        f"{target_angle:+.2f}°"
    )


    if move_servo(
        servo_id,
        target_position
    ):

        time.sleep(
            0.15
        )


        new_state = read_servo_state(
            servo_id
        )


        if new_state is not None:

            print(
                f"[OK] Current Position = "
                f"{new_state['position']}"
            )


# ============================================================
# 22. Zero로 복귀
# ============================================================

def move_to_zero(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    zero = config[
        "zero_position"
    ]


    if zero is None:

        print(
            "[BLOCK] Zero Position이 없습니다."
        )

        return


    print()
    print(
        f"[ZERO RETURN] "
        f"{config['joint']} -> {zero}"
    )


    if move_servo(
        servo_id,
        zero
    ):

        print(
            "[OK] Zero 이동 명령 전송 완료"
        )


# ============================================================
# 23. 현재 위치 Hold
# ============================================================
#
# 예상치 못한 움직임이 있을 경우
# 현재 Position을 다시 목표값으로 보내
# 현재 위치 유지 명령을 보낸다.

def hold_current_position(
    servo_id
):

    state = read_servo_state(
        servo_id
    )


    if state is None:

        return


    current = state[
        "position"
    ]


    move_servo(
        servo_id,
        current
    )


    print(
        f"[HOLD] Servo ID {servo_id} "
        f"현재 Position {current} 유지"
    )


# ============================================================
# 24. 현재 위치를 URDF Min 방향 안전 한계로 저장
# ============================================================
#
# min 명령에서 사용한다.
# 확인 질문에서 y를 입력하면 현재 Position을 Safe MIN으로
# 변경하고 JSON 파일에 즉시 저장한다.

def save_safe_min(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    if config[
        "zero_position"
    ] is None:

        print(
            "[BLOCK] 먼저 Zero를 설정하세요."
        )

        return


    state = read_servo_state(
        servo_id
    )


    if state is None:

        return


    current = state[
        "position"
    ]


    angle = math.degrees(
        position_to_angle(
            current,
            config[
                "zero_position"
            ],
            config[
                "direction"
            ]
        )
    )


    print()
    print(
        f"현재 Position : {current}"
    )

    print(
        f"현재 Joint Angle : {angle:+.2f}°"
    )


    if angle > 0:

        print(
            "[WARNING] 현재 위치는 "
            "URDF +Angle 쪽입니다."
        )

        print(
            "MIN 방향 한계를 저장하려는 것이 "
            "맞는지 다시 확인하세요."
        )


    answer = input(
        "현재 위치를 URDF MIN 방향 "
        "안전 한계로 저장할까요? [y/N]: "
    ).strip().lower()


    if answer != "y":

        return


    config[
        "safe_position_at_min_angle"
    ] = current


    save_calibration_file()


    print(
        f"[OK] Safe MIN Side = "
        f"{current} 저장"
    )


# ============================================================
# 25. 현재 위치를 URDF Max 방향 안전 한계로 저장
# ============================================================
#
# max 명령에서 사용한다.
# 확인 질문에서 y를 입력하면 현재 Position을 Safe MAX로
# 변경하고 JSON 파일에 즉시 저장한다.

def save_safe_max(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    if config[
        "zero_position"
    ] is None:

        print(
            "[BLOCK] 먼저 Zero를 설정하세요."
        )

        return


    state = read_servo_state(
        servo_id
    )


    if state is None:

        return


    current = state[
        "position"
    ]


    angle = math.degrees(
        position_to_angle(
            current,
            config[
                "zero_position"
            ],
            config[
                "direction"
            ]
        )
    )


    print()
    print(
        f"현재 Position : {current}"
    )

    print(
        f"현재 Joint Angle : {angle:+.2f}°"
    )


    if angle < 0:

        print(
            "[WARNING] 현재 위치는 "
            "URDF -Angle 쪽입니다."
        )

        print(
            "MAX 방향 한계를 저장하려는 것이 "
            "맞는지 다시 확인하세요."
        )


    answer = input(
        "현재 위치를 URDF MAX 방향 "
        "안전 한계로 저장할까요? [y/N]: "
    ).strip().lower()


    if answer != "y":

        return


    config[
        "safe_position_at_max_angle"
    ] = current


    save_calibration_file()


    print(
        f"[OK] Safe MAX Side = "
        f"{current} 저장"
    )


# ============================================================
# 26. Calibration 저장
# ============================================================

def save_calibration_file():

    result = {

        "saved_at":
            datetime.now().isoformat(),

        "device":
            DEVICENAME,

        "baudrate":
            BAUDRATE,

        "servos": {}
    }


    for servo_id in SERVO_IDS:

        config = SERVO_CONFIG[
            servo_id
        ]


        result[
            "servos"
        ][
            str(servo_id)
        ] = {

            "servo_id":
                servo_id,

            "joint":
                config[
                    "joint"
                ],

            "direction":
                config[
                    "direction"
                ],

            # 사람이 JSON만 보더라도 실제 움직임 방향을
            # 이해할 수 있도록 설명용 메타데이터를 함께 저장한다.
            "raw_position_increase_motion":
                config[
                    "raw_position_increase_motion"
                ],

            "raw_position_decrease_motion":
                config[
                    "raw_position_decrease_motion"
                ],

            "direction_reference":
                config[
                    "direction_reference"
                ],

            "zero_position":
                config[
                    "zero_position"
                ],

            "urdf_min_angle_rad":
                config[
                    "urdf_min_angle_rad"
                ],

            "urdf_max_angle_rad":
                config[
                    "urdf_max_angle_rad"
                ],

            "position_at_urdf_min_angle":
                config[
                    "position_at_urdf_min_angle"
                ],

            "position_at_urdf_max_angle":
                config[
                    "position_at_urdf_max_angle"
                ],

            "safe_position_at_min_angle":
                config[
                    "safe_position_at_min_angle"
                ],

            "safe_position_at_max_angle":
                config[
                    "safe_position_at_max_angle"
                ],

            "max_speed":
                config[
                    "max_speed"
                ],
        }


    with open(
        CALIBRATION_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=4
        )


# ============================================================
# 27. 기존 Calibration 파일 불러오기
# ============================================================
#
# 프로그램을 종료했다 다시 실행해도
# 이전에 저장한 Zero / Safe Limit을 재사용할 수 있다.

def load_calibration_file():

    if not os.path.exists(
        CALIBRATION_FILE
    ):

        print(
            "[INFO] 기존 Calibration 파일 없음"
        )

        return


    try:

        with open(
            CALIBRATION_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )


        servos = data.get(
            "servos",
            {}
        )


        for servo_id in SERVO_IDS:

            saved = servos.get(
                str(servo_id)
            )


            if not saved:

                continue


            config = SERVO_CONFIG[
                servo_id
            ]


            config[
                "zero_position"
            ] = saved.get(
                "zero_position"
            )


            config[
                "safe_position_at_min_angle"
            ] = saved.get(
                "safe_position_at_min_angle"
            )


            config[
                "safe_position_at_max_angle"
            ] = saved.get(
                "safe_position_at_max_angle"
            )


            config[
                "max_speed"
            ] = saved.get(
                "max_speed"
            )


            if config[
                "zero_position"
            ] is not None:

                calculate_urdf_limits(
                    servo_id
                )


        print(
            f"[OK] 기존 Calibration 불러오기: "
            f"{CALIBRATION_FILE}"
        )


    except Exception as error:

        print(
            f"[WARNING] Calibration 파일 "
            f"읽기 실패: {error}"
        )


# ============================================================
# 28. 명령어 도움말
# ============================================================

def print_help():

    print()
    print(
        "=================================================="
    )

    print(
        "               MANUAL SERVO CONTROL"
    )

    print(
        "=================================================="
    )

    print(
        "1 / 2 / 3 / 4"
        "     : Servo 선택"
    )

    print(
        "i"
        "               : URDF +방향으로 Step 이동"
    )

    print(
        "o"
        "               : URDF -방향으로 Step 이동"
    )

    print(
        "step 20"
        "         : 이동 Step 변경"
    )

    print(
        "speed 100"
        "       : 이동 Speed 변경"
    )

    print(
        "z"
        "               : 현재 위치를 Zero로 저장"
    )

    print(
        "0"
        "               : Zero Position으로 복귀"
    )

    print(
        "min"
        "             : 현재 위치를 MIN 안전 한계 저장"
    )

    print(
        "max"
        "             : 현재 위치를 MAX 안전 한계 저장"
    )

    print(
        "s"
        "               : 선택 Servo 상태"
    )

    print(
        "all"
        "             : 전체 Servo 상태"
    )

    print(
        "x"
        "               : 현재 위치 Hold"
    )

    print(
        "save"
        "            : Calibration 저장"
    )

    print(
        "h"
        "               : 도움말"
    )

    print(
        "q"
        "               : 저장 후 종료"
    )

    print(
        "=================================================="
    )


# ============================================================
# 29. Serial Port Open
# ============================================================

if not portHandler.openPort():

    print(
        f"[ERROR] 포트를 열 수 없습니다: "
        f"{DEVICENAME}"
    )

    sys.exit(1)


print(
    f"[OK] 포트 연결 성공: "
    f"{DEVICENAME}"
)


if not portHandler.setBaudRate(
    BAUDRATE
):

    print(
        f"[ERROR] Baudrate 설정 실패: "
        f"{BAUDRATE}"
    )

    portHandler.closePort()

    sys.exit(1)


print(
    f"[OK] Baudrate 설정 성공: "
    f"{BAUDRATE}"
)


# ============================================================
# 30. 기존 Calibration 불러오기
# ============================================================

load_calibration_file()


# ============================================================
# 31. Servo 1~4 통신 확인
# ============================================================

print()

for servo_id in SERVO_IDS:

    config = SERVO_CONFIG[
        servo_id
    ]


    model_number, result, error = (
        packetHandler.ping(
            servo_id
        )
    )


    if (
        result != COMM_SUCCESS
        or error != 0
    ):

        print(
            f"[WARNING] ID {servo_id} "
            f"({config['joint']}) 응답 없음"
        )

        continue


    state = read_servo_state(
        servo_id
    )


    if state is None:

        print(
            f"[WARNING] ID {servo_id} "
            "상태 읽기 실패"
        )

        continue


    state[
        "model_number"
    ] = model_number


    initial_states[
        servo_id
    ] = state


    print(
        f"[OK] ID {servo_id} "
        f"({config['joint']}) "
        f"Position={state['position']}"
    )


# ============================================================
# 32. Terminal Manual Control
# ============================================================

selected_servo_id = 1


print_help()


try:

    while True:

        config = SERVO_CONFIG[
            selected_servo_id
        ]


        print()

        command = input(
            f"[ID {selected_servo_id} "
            f"{config['joint']} | "
            f"Step={manual_step} | "
            f"Speed={manual_speed}] > "
        ).strip().lower()


        # ----------------------------------------------------
        # 빈 입력
        # ----------------------------------------------------

        if not command:

            continue


        # ----------------------------------------------------
        # Servo 선택
        # ----------------------------------------------------

        if command in [
            "1",
            "2",
            "3",
            "4"
        ]:

            selected_servo_id = int(
                command
            )


            print_servo_status(
                selected_servo_id
            )

            continue


        # ----------------------------------------------------
        # i : URDF +방향으로 이동
        # ----------------------------------------------------

        if command == "i":

            manual_joint_move(
                selected_servo_id,
                +1
            )

            continue


        # ----------------------------------------------------
        # o : URDF -방향으로 이동
        # ----------------------------------------------------

        if command == "o":

            manual_joint_move(
                selected_servo_id,
                -1
            )

            continue


        # ----------------------------------------------------
        # Zero 설정
        # ----------------------------------------------------

        if command == "z":

            set_zero_position(
                selected_servo_id
            )

            continue


        # ----------------------------------------------------
        # Zero 복귀
        # ----------------------------------------------------

        if command == "0":

            move_to_zero(
                selected_servo_id
            )

            continue


        # ----------------------------------------------------
        # MIN 안전 한계 저장
        # ----------------------------------------------------

        if command == "min":

            save_safe_min(
                selected_servo_id
            )

            continue


        # ----------------------------------------------------
        # MAX 안전 한계 저장
        # ----------------------------------------------------

        if command == "max":

            save_safe_max(
                selected_servo_id
            )

            continue


        # ----------------------------------------------------
        # 상태
        # ----------------------------------------------------

        if command == "s":

            print_servo_status(
                selected_servo_id
            )

            continue


        # ----------------------------------------------------
        # 전체 상태
        # ----------------------------------------------------

        if command == "all":

            print_all_status()

            continue


        # ----------------------------------------------------
        # 현재 Position Hold
        # ----------------------------------------------------

        if command == "x":

            hold_current_position(
                selected_servo_id
            )

            continue


        # ----------------------------------------------------
        # Step 변경
        #
        # 예:
        # step 100
        # ----------------------------------------------------

        if command.startswith(
            "step "
        ):

            try:

                value = int(
                    command.split()[1]
                )


                if not (
                    1 <= value <= 500
                ):

                    print(
                        "[ERROR] Step은 "
                        "1 ~ 500 범위로 설정하세요."
                    )

                    continue


                manual_step = value


                print(
                    f"[OK] Step = "
                    f"{manual_step}"
                )


            except Exception:

                print(
                    "[ERROR] 예: step 20"
                )


            continue


        # ----------------------------------------------------
        # Speed 변경
        #
        # 예:
        # speed 100
        # ----------------------------------------------------

        if command.startswith(
            "speed "
        ):

            try:

                value = int(
                    command.split()[1]
                )


                if not (
                    1 <= value <= 2000
                ):

                    print(
                        "[ERROR] Speed는 "
                        "1 ~ 2000 범위로 설정하세요."
                    )

                    continue


                manual_speed = value


                print(
                    f"[OK] Speed = "
                    f"{manual_speed}"
                )


            except Exception:

                print(
                    "[ERROR] 예: speed 100"
                )


            continue


        # ----------------------------------------------------
        # 저장
        # ----------------------------------------------------

        if command == "save":

            save_calibration_file()


            print(
                f"[OK] 저장 완료: "
                f"{CALIBRATION_FILE}"
            )

            continue


        # ----------------------------------------------------
        # 도움말
        # ----------------------------------------------------

        if command in [
            "h",
            "help"
        ]:

            print_help()

            continue


        # ----------------------------------------------------
        # 종료
        # ----------------------------------------------------

        if command in [
            "q",
            "quit",
            "exit"
        ]:

            save_calibration_file()

            print(
                f"[OK] Calibration 저장: "
                f"{CALIBRATION_FILE}"
            )

            break


        # ----------------------------------------------------
        # 잘못된 명령어
        # ----------------------------------------------------

        print(
            "[ERROR] 알 수 없는 명령어입니다."
        )

        print(
            "'h'를 입력하면 도움말을 볼 수 있습니다."
        )


# ============================================================
# 33. Ctrl+C 처리
# ============================================================

except KeyboardInterrupt:

    print()
    print(
        "[WARNING] Ctrl+C 감지"
    )


    try:

        hold_current_position(
            selected_servo_id
        )

    except Exception:

        pass


    try:

        save_calibration_file()

    except Exception:

        pass


# ============================================================
# 34. Serial Port 종료
# ============================================================

finally:

    portHandler.closePort()

    print(
        "[OK] 포트를 정상적으로 닫았습니다."
    )