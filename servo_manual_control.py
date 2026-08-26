#!/usr/bin/env python

"""
servo_manual_control.py

[역할]
Raspberry Pi 터미널에서 STS Servo 4개를 직접 수동 조작하기 위한
"수동제어 전용" 프로그램.

이 프로그램은 Calibration 결과를 읽어 활용하지만,
servo_calibration_result.json 파일을 절대 수정하지 않는다.

------------------------------------------------------------
[사용 Joint / Direction]

Servo ID 1 -> shoulder_lift -> direction = +1
Servo ID 2 -> elbow_flex    -> direction = +1
Servo ID 3 -> wrist_flex    -> direction = +1
Servo ID 4 -> wrist_roll    -> direction = -1

direction = +1
    STS Position 증가 방향 = URDF Joint +방향

direction = -1
    STS Position 감소 방향 = URDF Joint +방향

따라서 사용자는 Servo별 raw Position 방향을 계산할 필요 없이
항상 다음 명령을 사용하면 된다.

i
    -> URDF +방향

o
    -> URDF -방향

------------------------------------------------------------
[Calibration 완료 Servo]

JSON에 아래 값이 모두 저장되어 있으면 SAFE MODE로 동작한다.

- zero_position
- safe_position_at_min_angle
- safe_position_at_max_angle

SAFE MODE에서는:
- 저장된 Safe MIN / MAX 범위를 절대 넘어가지 않는다.
- 현재 Joint Angle을 Zero 기준으로 표시한다.
- 0 명령으로 Zero Position 복귀가 가능하다.

------------------------------------------------------------
[Calibration 미완료 Servo]

Zero 또는 Safe MIN/MAX가 아직 없는 Servo도 조작 가능하다.

RAW MODE에서는:
- STS 기본 Position 범위 0 ~ 4095 안에서 이동 가능
- 저장된 Safe MIN/MAX 보호는 아직 사용할 수 없음
- 해당 Servo의 첫 이동 전에 경고 메시지와 사용자 확인을 받음
- Zero가 없어도 'tz' 명령으로 현재 위치를 임시 Zero로 지정 가능
- 임시 Zero를 기준으로 Joint Angle 표시 및 0 복귀 가능
- 임시 Zero는 프로그램 종료 시 사라지며 JSON에는 저장되지 않음

즉 RAW MODE는 Calibration 전 모터 동작/방향 확인용이다.

※ Calibration이 완료되지 않은 상태에서는 실제 로봇 구조의
   안전 한계가 적용되지 않으므로 작은 Step과 낮은 Speed를 권장한다.

------------------------------------------------------------
[터미널 명령]

1 / 2 / 3 / 4
    -> 조작할 Servo 선택

i
    -> URDF +방향으로 Step 이동

o
    -> URDF -방향으로 Step 이동

step 20
    -> 이동 Step 변경

speed 100
    -> 이동 Speed 변경

acc 10
    -> 이동 Acc 변경

tz
    -> 현재 위치를 임시 Zero Position으로 설정
       (메모리에만 저장, JSON에는 저장하지 않음)

0
    -> 현재 사용할 Zero Position으로 복귀
       - 임시 Zero가 있으면 임시 Zero 사용
       - 없으면 JSON에 저장된 Zero 사용

s
    -> 현재 선택 Servo 상태

all
    -> Servo 1~4 전체 상태

x
    -> 현재 Position Hold

h
    -> 도움말

q
    -> 종료

------------------------------------------------------------
[이 프로그램에서 하지 않는 것]

z
min
max
save

Calibration 값 수정/저장은 servo_calibration.py에서만 수행한다.

수동제어에서 Zero가 임시로 필요하면 'tz'를 사용한다.
'tz'는 현재 실행 중인 프로그램 메모리에서만 사용되며
servo_calibration_result.json에는 기록되지 않는다.

이 파일은 servo_calibration_result.json을 읽기("r")만 하며,
JSON 저장 함수 자체가 없다.
"""

import sys
import os
import math
import json
import time


# ============================================================
# 1. STServo Python SDK 경로 설정
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
# 4. Calibration 파일
# ============================================================

CALIBRATION_FILE = "servo_calibration_result.json"


# ============================================================
# 5. Servo 기본 설정
# ============================================================

SERVO_CONFIG = {

    1: {
        "joint": "shoulder_lift",
        "direction": +1,
        "zero_position": None,
        "temporary_zero_position": None,
        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,
    },

    2: {
        "joint": "elbow_flex",
        "direction": +1,
        "zero_position": None,
        "temporary_zero_position": None,
        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,
    },

    3: {
        "joint": "wrist_flex",
        "direction": +1,
        "zero_position": None,
        "temporary_zero_position": None,
        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,
    },

    4: {
        "joint": "wrist_roll",
        "direction": -1,
        "zero_position": None,
        "temporary_zero_position": None,
        "safe_position_at_min_angle": None,
        "safe_position_at_max_angle": None,
    },
}


SERVO_IDS = [1, 2, 3, 4]


# ============================================================
# 6. STS Position 기준
# ============================================================

STS_POSITION_MIN = 0
STS_POSITION_MAX = 4095

STS_POSITION_RESOLUTION = 4096

RAD_PER_POSITION = (
    2.0 * math.pi
    / STS_POSITION_RESOLUTION
)


# ============================================================
# 7. STS 상태 레지스터
# ============================================================

ADDR_PRESENT_LOAD = 60
ADDR_PRESENT_VOLTAGE = 62
ADDR_PRESENT_TEMPERATURE = 63
ADDR_MOVING = 66
ADDR_PRESENT_CURRENT = 69


# ============================================================
# 8. 수동조작 기본값
# ============================================================

DEFAULT_STEP = 20
DEFAULT_SPEED = 100
DEFAULT_ACC = 10

manual_step = DEFAULT_STEP
manual_speed = DEFAULT_SPEED
manual_acc = DEFAULT_ACC


# ============================================================
# 9. 이동 완료 확인 설정
# ============================================================

MOVE_TIMEOUT_SEC = 5.0
POSITION_TOLERANCE = 5


# ============================================================
# 10. RAW MODE 경고 확인 상태
# ============================================================

raw_mode_confirmed = {
    servo_id: False
    for servo_id in SERVO_IDS
}


# ============================================================
# 11. 통신 객체 생성
# ============================================================

portHandler = PortHandler(
    DEVICENAME
)

packetHandler = sms_sts(
    portHandler
)


# ============================================================
# 12. Calibration JSON 불러오기
# ============================================================

def load_calibration_file():

    if not os.path.exists(
        CALIBRATION_FILE
    ):

        print(
            f"[INFO] Calibration 파일 없음: "
            f"{CALIBRATION_FILE}"
        )

        print(
            "[INFO] 모든 Servo를 RAW MODE로 "
            "수동제어할 수 있습니다."
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


        saved_servos = data.get(
            "servos",
            {}
        )


        for servo_id in SERVO_IDS:

            saved = saved_servos.get(
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


        print(
            f"[OK] Calibration 읽기 완료: "
            f"{CALIBRATION_FILE}"
        )

        print(
            "[INFO] JSON은 읽기 전용으로 사용합니다."
        )


    except Exception as error:

        print(
            f"[WARNING] Calibration JSON 읽기 실패: "
            f"{error}"
        )

        print(
            "[INFO] 저장값을 사용하지 않고 "
            "RAW MODE로 계속 실행합니다."
        )


# ============================================================
# 13. 현재 사용할 Zero Position 반환
# ============================================================

def get_active_zero_position(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    temporary_zero = config[
        "temporary_zero_position"
    ]


    if temporary_zero is not None:

        return temporary_zero


    return config[
        "zero_position"
    ]


# ============================================================
# 14. 현재 위치를 임시 Zero로 설정
# ============================================================

def set_temporary_zero(
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
            "[ERROR] 현재 Position을 읽을 수 없습니다."
        )

        return


    current_position = state[
        "position"
    ]


    print()
    print(
        "=================================================="
    )

    print(
        f"[TEMP ZERO] Servo ID {servo_id} "
        f"({config['joint']})"
    )

    print(
        "=================================================="
    )

    print(
        f"현재 Position : {current_position}"
    )

    print()
    print(
        "이 Zero는 현재 Manual Control 실행 중에만 사용됩니다."
    )

    print(
        "servo_calibration_result.json에는 저장되지 않습니다."
    )


    answer = input(
        "현재 위치를 임시 Zero로 설정할까요? [y/N]: "
    ).strip().lower()


    if answer != "y":

        print(
            "[INFO] 임시 Zero 설정 취소"
        )

        return


    config[
        "temporary_zero_position"
    ] = current_position


    print()
    print(
        f"[OK] Temporary Zero = "
        f"{current_position}"
    )

    print(
        "[INFO] JSON에는 저장되지 않았습니다."
    )


# ============================================================
# 15. Servo 제어 모드 판단
# ============================================================

def get_control_mode(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    if (
        config[
            "zero_position"
        ] is not None
        and
        config[
            "safe_position_at_min_angle"
        ] is not None
        and
        config[
            "safe_position_at_max_angle"
        ] is not None
    ):

        return "SAFE"


    return "RAW"


# ============================================================
# 16. Position -> URDF Joint Angle
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
# 17. Servo 상태 읽기
# ============================================================

def read_servo_state(
    servo_id
):

    state = {}


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


    speed, result, error = (
        packetHandler.ReadSpeed(
            servo_id
        )
    )


    state[
        "speed"
    ] = (
        speed
        if result == COMM_SUCCESS
        and error == 0
        else None
    )


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

            load_value = -load_value


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


    voltage_raw, result, error = (
        packetHandler.read1ByteTxRx(
            servo_id,
            ADDR_PRESENT_VOLTAGE
        )
    )


    state[
        "voltage"
    ] = (
        voltage_raw * 0.1
        if result == COMM_SUCCESS
        and error == 0
        else None
    )


    temperature, result, error = (
        packetHandler.read1ByteTxRx(
            servo_id,
            ADDR_PRESENT_TEMPERATURE
        )
    )


    state[
        "temperature"
    ] = (
        temperature
        if result == COMM_SUCCESS
        and error == 0
        else None
    )


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

        state[
            "current_ma"
        ] = (
            current_raw * 6.5
        )


    else:

        state[
            "current_raw"
        ] = None

        state[
            "current_ma"
        ] = None


    moving, result, error = (
        packetHandler.read1ByteTxRx(
            servo_id,
            ADDR_MOVING
        )
    )


    state[
        "moving"
    ] = (
        moving
        if result == COMM_SUCCESS
        and error == 0
        else None
    )


    return state


# ============================================================
# 18. SAFE MODE Position 범위
# ============================================================

def get_safe_position_range(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    if get_control_mode(
        servo_id
    ) != "SAFE":

        return None


    min_side = config[
        "safe_position_at_min_angle"
    ]

    max_side = config[
        "safe_position_at_max_angle"
    ]


    return (
        min(
            min_side,
            max_side
        ),
        max(
            min_side,
            max_side
        )
    )


# ============================================================
# 19. RAW MODE 첫 이동 확인
# ============================================================

def confirm_raw_mode(
    servo_id
):

    if raw_mode_confirmed[
        servo_id
    ]:

        return True


    config = SERVO_CONFIG[
        servo_id
    ]


    print()
    print(
        "=================================================="
    )

    print(
        "[WARNING] Calibration 미완료 Servo"
    )

    print(
        "=================================================="
    )

    print(
        f"Servo ID : {servo_id}"
    )

    print(
        f"Joint    : {config['joint']}"
    )

    print()
    print(
        "이 Servo는 Safe MIN/MAX가 아직 설정되지 않았습니다."
    )

    print(
        "따라서 저장된 실제 기구 안전범위 보호 없이 "
        "STS 기본 범위 안에서만 제어합니다."
    )

    print()
    print(
        f"현재 Step  : {manual_step}"
    )

    print(
        f"현재 Speed : {manual_speed}"
    )

    print(
        f"현재 Acc   : {manual_acc}"
    )


    answer = input(
        "RAW MODE 수동제어를 계속할까요? [y/N]: "
    ).strip().lower()


    if answer != "y":

        print(
            "[INFO] 이동 취소"
        )

        return False


    raw_mode_confirmed[
        servo_id
    ] = True


    print(
        f"[OK] ID {servo_id} RAW MODE 제어 허용"
    )


    return True


# ============================================================
# 20. 이동 목표 안전 검사
# ============================================================

def check_target_position(
    servo_id,
    target_position
):

    if not (
        STS_POSITION_MIN
        <= target_position
        <= STS_POSITION_MAX
    ):

        print()
        print(
            "[BLOCK] STS Position 범위를 "
            "벗어나는 명령입니다."
        )

        return False


    mode = get_control_mode(
        servo_id
    )


    if mode == "RAW":

        return confirm_raw_mode(
            servo_id
        )


    safe_range = get_safe_position_range(
        servo_id
    )


    numeric_min, numeric_max = (
        safe_range
    )


    if not (
        numeric_min
        <= target_position
        <= numeric_max
    ):

        print()
        print(
            "[BLOCK] 저장된 Safe Range를 "
            "벗어나는 명령입니다."
        )

        print(
            f"Target Position : "
            f"{target_position}"
        )

        print(
            f"Safe Range      : "
            f"{numeric_min} ~ {numeric_max}"
        )

        return False


    return True


# ============================================================
# 21. Servo 이동 명령
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


    if not check_target_position(
        servo_id,
        target_position
    ):

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
# 22. 이동 완료 확인
# ============================================================

def wait_until_servo_stops(
    servo_id,
    target_position,
    timeout=MOVE_TIMEOUT_SEC
):

    start_time = time.time()


    while (
        time.time() - start_time
        < timeout
    ):

        state = read_servo_state(
            servo_id
        )


        if state is None:

            return False


        position_error = abs(
            state[
                "position"
            ]
            - target_position
        )


        if (
            state[
                "moving"
            ] == 0
            and
            position_error
            <= POSITION_TOLERANCE
        ):

            return True


        time.sleep(
            0.05
        )


    print(
        "[WARNING] 이동 완료 확인 시간 초과"
    )

    return False


# ============================================================
# 23. URDF 방향 기준 수동 Step 이동
# ============================================================

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
            "[ERROR] Servo 상태를 읽을 수 없습니다."
        )

        return


    current_position = state[
        "position"
    ]


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


    mode = get_control_mode(
        servo_id
    )


    direction_text = (
        "URDF +"
        if direction_sign > 0
        else "URDF -"
    )


    print()
    print(
        f"[MOVE] ID {servo_id} "
        f"{config['joint']} | "
        f"{mode} MODE | "
        f"{direction_text}"
    )

    print(
        f"Position : "
        f"{current_position} "
        f"-> "
        f"{target_position}"
    )


    active_zero = get_active_zero_position(
        servo_id
    )


    if active_zero is not None:

        current_angle = math.degrees(
            position_to_angle(
                current_position,
                active_zero,
                config[
                    "direction"
                ]
            )
        )

        target_angle = math.degrees(
            position_to_angle(
                target_position,
                active_zero,
                config[
                    "direction"
                ]
            )
        )


        print(
            f"Angle    : "
            f"{current_angle:+.2f}° "
            f"-> "
            f"{target_angle:+.2f}°"
        )


    else:

        print(
            "Angle    : Zero 미설정"
        )


    if not move_servo(
        servo_id,
        target_position
    ):

        return


    wait_until_servo_stops(
        servo_id,
        target_position
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
# 24. Zero Position으로 복귀
# ============================================================

def move_to_zero(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]


    active_zero = get_active_zero_position(
        servo_id
    )


    if active_zero is None:

        print()
        print(
            "[BLOCK] 사용할 Zero Position이 없습니다."
        )

        print(
            "[INFO] Calibration Zero가 없으면 "
            "'tz'로 임시 Zero를 설정할 수 있습니다."
        )

        return


    zero_source = (
        "TEMP"
        if config[
            "temporary_zero_position"
        ] is not None
        else "SAVED"
    )


    print()
    print(
        f"[ZERO RETURN] ID {servo_id} "
        f"{config['joint']} -> "
        f"{active_zero} "
        f"({zero_source})"
    )


    if not move_servo(
        servo_id,
        active_zero
    ):

        return


    if wait_until_servo_stops(
        servo_id,
        active_zero
    ):

        print(
            "[OK] Zero Position 복귀 완료"
        )


# ============================================================
# 25. 현재 Position Hold
# ============================================================

def hold_current_position(
    servo_id
):

    state = read_servo_state(
        servo_id
    )


    if state is None:

        print(
            "[ERROR] 현재 Position을 읽을 수 없습니다."
        )

        return


    current_position = state[
        "position"
    ]


    result, error = (
        packetHandler.WritePosEx(
            servo_id,
            current_position,
            manual_speed,
            manual_acc
        )
    )


    if (
        result == COMM_SUCCESS
        and error == 0
    ):

        print(
            f"[HOLD] Servo ID {servo_id} "
            f"현재 Position "
            f"{current_position} 유지"
        )


    else:

        print(
            "[ERROR] Hold 명령 실패"
        )


# ============================================================
# 26. Servo 상세 상태 출력
# ============================================================

def print_servo_status(
    servo_id
):

    config = SERVO_CONFIG[
        servo_id
    ]

    mode = get_control_mode(
        servo_id
    )


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

        print(
            "=================================================="
        )

        return


    position = state[
        "position"
    ]


    print(
        f"Control Mode   : "
        f"{mode}"
    )

    print(
        f"Position       : "
        f"{position}"
    )


    active_zero = get_active_zero_position(
        servo_id
    )


    if active_zero is not None:

        angle_deg = math.degrees(
            position_to_angle(
                position,
                active_zero,
                config[
                    "direction"
                ]
            )
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


    if state[
        "temperature"
    ] is not None:

        print(
            f"Temperature    : "
            f"{state['temperature']} °C"
        )

    else:

        print(
            "Temperature    : -"
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


    if state[
        "moving"
    ] == 0:

        moving_text = "STOPPED"

    elif state[
        "moving"
    ] is None:

        moving_text = "-"

    else:

        moving_text = "MOVING"


    print(
        f"Moving         : "
        f"{moving_text}"
    )


    print(
        "--------------------------------------------------"
    )

    print(
        f"Direction      : "
        f"{config['direction']:+d}"
    )

    print(
        f"Saved Zero     : "
        f"{config['zero_position']}"
    )

    print(
        f"Temporary Zero : "
        f"{config['temporary_zero_position']}"
    )

    print(
        f"Active Zero    : "
        f"{get_active_zero_position(servo_id)}"
    )

    print(
        f"Safe MIN Side  : "
        f"{config['safe_position_at_min_angle']}"
    )

    print(
        f"Safe MAX Side  : "
        f"{config['safe_position_at_max_angle']}"
    )


    if mode == "SAFE":

        safe_range = get_safe_position_range(
            servo_id
        )


        print(
            f"Active Range   : "
            f"{safe_range[0]} "
            f"~ "
            f"{safe_range[1]}"
        )

        print(
            "Protection     : "
            "Calibration Safe Range"
        )


    else:

        print(
            f"Active Range   : "
            f"{STS_POSITION_MIN} "
            f"~ "
            f"{STS_POSITION_MAX}"
        )

        print(
            "Protection     : "
            "STS Raw Range Only"
        )


    print(
        "=================================================="
    )


# ============================================================
# 27. 전체 Servo 상태
# ============================================================

def print_all_status():

    print()
    print(
        "============================================================================"
    )

    print(
        "                           ALL SERVO STATUS"
    )

    print(
        "============================================================================"
    )


    for servo_id in SERVO_IDS:

        config = SERVO_CONFIG[
            servo_id
        ]

        mode = get_control_mode(
            servo_id
        )


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


        active_zero = get_active_zero_position(
            servo_id
        )


        if active_zero is not None:

            angle_deg = math.degrees(
                position_to_angle(
                    position,
                    active_zero,
                    config[
                        "direction"
                    ]
                )
            )

            angle_text = (
                f"{angle_deg:+7.2f}°"
            )

        else:

            angle_text = (
                "   N/A  "
            )


        if mode == "SAFE":

            safe_range = get_safe_position_range(
                servo_id
            )

            range_text = (
                f"{safe_range[0]}~"
                f"{safe_range[1]}"
            )

        else:

            range_text = (
                "0~4095"
            )


        print(
            f"ID {servo_id} "
            f"{config['joint']:<15} "
            f"Pos={position:<4} "
            f"Angle={angle_text} "
            f"Mode={mode:<4} "
            f"Range={range_text}"
        )


    print(
        "============================================================================"
    )


# ============================================================
# 28. 도움말
# ============================================================

def print_help():

    print()
    print(
        "=================================================="
    )

    print(
        "           SERVO MANUAL CONTROL"
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
        "acc 10"
        "           : 이동 Acc 변경"
    )

    print(
        "tz"
        "              : 현재 위치를 임시 Zero로 설정"
    )

    print(
        "0"
        "               : 현재 사용할 Zero로 복귀"
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
        "               : 현재 Position Hold"
    )

    print(
        "h"
        "               : 도움말"
    )

    print(
        "q"
        "               : 종료"
    )

    print()
    print(
        "[CONTROL MODE]"
    )

    print(
        "SAFE : Calibration Safe MIN/MAX 범위 적용"
    )

    print(
        "RAW  : Calibration 미완료, STS 0~4095 범위만 적용"
    )

    print()
    print(
        "[READ ONLY]"
    )

    print(
        "z / min / max / save 명령은 지원하지 않습니다."
    )

    print(
        "임시 Zero가 필요하면 'tz'를 사용하세요."
    )

    print(
        "Calibration 수정은 servo_calibration.py에서 "
        "진행하세요."
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
# 30. Calibration JSON Read Only Load
# ============================================================

load_calibration_file()


# ============================================================
# 31. Servo 통신 상태 확인
# ============================================================

print()
print(
    "[CHECK] Servo 통신 및 Control Mode"
)

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
            f"({config['joint']}) 상태 읽기 실패"
        )

        continue


    mode = get_control_mode(
        servo_id
    )


    print(
        f"[OK] ID {servo_id} "
        f"({config['joint']}) "
        f"Position={state['position']} | "
        f"{mode} MODE"
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


        mode = get_control_mode(
            selected_servo_id
        )


        print()


        command = input(
            f"[ID {selected_servo_id} "
            f"{config['joint']} | "
            f"{mode} | "
            f"Step={manual_step} | "
            f"Speed={manual_speed} | "
            f"Acc={manual_acc}] > "
        ).strip().lower()


        if not command:
            continue


        if command in (
            "1",
            "2",
            "3",
            "4"
        ):

            selected_servo_id = int(
                command
            )


            print_servo_status(
                selected_servo_id
            )

            continue


        if command == "i":

            manual_joint_move(
                selected_servo_id,
                +1
            )

            continue


        if command == "o":

            manual_joint_move(
                selected_servo_id,
                -1
            )

            continue


        if command == "tz":

            set_temporary_zero(
                selected_servo_id
            )

            continue


        if command == "0":

            move_to_zero(
                selected_servo_id
            )

            continue


        if command == "s":

            print_servo_status(
                selected_servo_id
            )

            continue


        if command == "all":

            print_all_status()

            continue


        if command == "x":

            hold_current_position(
                selected_servo_id
            )

            continue


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
                    "[ERROR] 사용 예: step 20"
                )


            continue


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
                    "[ERROR] 사용 예: speed 100"
                )


            continue


        if command.startswith(
            "acc "
        ):

            try:

                value = int(
                    command.split()[1]
                )


                if not (
                    1 <= value <= 255
                ):

                    print(
                        "[ERROR] Acc는 "
                        "1 ~ 255 범위로 설정하세요."
                    )

                    continue


                manual_acc = value


                print(
                    f"[OK] Acc = "
                    f"{manual_acc}"
                )


            except Exception:

                print(
                    "[ERROR] 사용 예: acc 10"
                )


            continue


        if command in (
            "z",
            "min",
            "max",
            "save"
        ):

            print()
            print(
                f"[BLOCK] '{command}' 명령은 "
                "Manual Control에서 사용할 수 없습니다."
            )

            print(
                "[INFO] Calibration 수정은 "
                "servo_calibration.py에서 진행하세요."
            )

            continue


        if command in (
            "h",
            "help"
        ):

            print_help()

            continue


        if command in (
            "q",
            "quit",
            "exit"
        ):

            print()
            print(
                "[INFO] Manual Control 종료"
            )

            print(
                "[INFO] Calibration JSON은 "
                "수정하지 않았습니다."
            )

            break


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


    print(
        "[INFO] Calibration JSON은 "
        "수정하지 않았습니다."
    )


# ============================================================
# 34. Serial Port 종료
# ============================================================

finally:

    portHandler.closePort()

    print(
        "[OK] 포트를 정상적으로 닫았습니다."
    )