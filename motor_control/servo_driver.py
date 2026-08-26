"""
motor_control/servo_driver.py

[역할]
STServo Python SDK와 직접 통신하는 저수준 Driver.

다른 팀원은 이 파일을 직접 사용할 필요가 없다.

------------------------------------------------------------
[담당 기능]

- Serial Port Open / Close
- Ping
- 단일 Servo Position 제어
- 여러 Servo SyncWrite
- Position 읽기
- Speed 읽기
- Load / Voltage / Temperature / Current / Moving 읽기

------------------------------------------------------------
[담당하지 않는 기능]

- Joint 방향 판단
- Zero 계산
- 각도 -> Position 계산
- Safe Range 판단

이 기능들은 calibration.py / controller.py가 담당한다.
"""

import sys


from .config import (
    SDK_PATH,
)


# ============================================================
# 1. STServo SDK 경로
# ============================================================

if SDK_PATH not in sys.path:

    sys.path.append(
        SDK_PATH
    )


# ============================================================
# 2. STServo SDK
# ============================================================

from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import COMM_SUCCESS


# ============================================================
# 3. STS 상태 레지스터
# ============================================================

ADDR_PRESENT_LOAD = 60
ADDR_PRESENT_VOLTAGE = 62
ADDR_PRESENT_TEMPERATURE = 63
ADDR_MOVING = 66
ADDR_PRESENT_CURRENT = 69


# ============================================================
# 4. Servo Driver
# ============================================================

class ServoDriver:

    def __init__(
        self,
        device,
        baudrate
    ):

        self.device = device

        self.baudrate = int(
            baudrate
        )


        self.port_handler = (
            PortHandler(
                self.device
            )
        )


        self.packet_handler = (
            sms_sts(
                self.port_handler
            )
        )


        self.is_open = False


        self.open()


    # ========================================================
    # 5. Port Open
    # ========================================================

    def open(self):

        if self.is_open:

            return True


        if not self.port_handler.openPort():

            raise RuntimeError(
                "Servo Port Open 실패: "
                f"{self.device}"
            )


        if not self.port_handler.setBaudRate(
            self.baudrate
        ):

            self.port_handler.closePort()


            raise RuntimeError(
                "Servo Baudrate 설정 실패: "
                f"{self.baudrate}"
            )


        self.is_open = True


        return True


    # ========================================================
    # 6. Port Close
    # ========================================================

    def close(self):

        if self.is_open:

            self.port_handler.closePort()

            self.is_open = False


    # ========================================================
    # 7. Ping
    # ========================================================

    def ping(
        self,
        servo_id
    ):

        model_number, result, error = (
            self.packet_handler.ping(
                int(
                    servo_id
                )
            )
        )


        success = (
            result == COMM_SUCCESS
            and error == 0
        )


        return {

            "success":
                success,

            "model_number":
                (
                    model_number

                    if success

                    else None
                ),

            "result":
                result,

            "error":
                error,
        }


    # ========================================================
    # 8. 단일 Servo 이동
    # ========================================================

    def write_position(
        self,
        servo_id,
        position,
        speed,
        acc
    ):

        result, error = (
            self.packet_handler.WritePosEx(

                int(
                    servo_id
                ),

                int(
                    position
                ),

                int(
                    speed
                ),

                int(
                    acc
                )
            )
        )


        return (
            result == COMM_SUCCESS
            and error == 0
        )


    # ========================================================
    # 9. 여러 Servo 동기 이동
    # ========================================================
    #
    # commands 예:
    #
    # {
    #
    #     1: {
    #         "position": 1500,
    #         "speed": 100,
    #         "acc": 10
    #     },
    #
    #     2: {
    #         "position": 2000,
    #         "speed": 100,
    #         "acc": 10
    #     }
    #
    # }
    #
    #
    # SyncWritePosEx()로 각 Servo의 값을
    # GroupSyncWrite에 먼저 추가한다.
    #
    # 이후 txPacket() 한 번으로 실제 통신 패킷을 전송한다.

    def sync_write_positions(
        self,
        commands
    ):

        group_sync_write = (
            self.packet_handler.groupSyncWrite
        )


        # 이전에 남아 있을 수 있는 Parameter 제거
        group_sync_write.clearParam()


        try:

            # ------------------------------------------------
            # 각 Servo Parameter 추가
            # ------------------------------------------------

            for (
                servo_id,
                command
            ) in commands.items():

                added = (
                    self.packet_handler.SyncWritePosEx(

                        int(
                            servo_id
                        ),

                        int(
                            command[
                                "position"
                            ]
                        ),

                        int(
                            command[
                                "speed"
                            ]
                        ),

                        int(
                            command[
                                "acc"
                            ]
                        )
                    )
                )


                if not added:

                    return False


            # ------------------------------------------------
            # 실제 동기 패킷 전송
            # ------------------------------------------------

            result = (
                group_sync_write.txPacket()
            )


            return (
                result == COMM_SUCCESS
            )


        finally:

            group_sync_write.clearParam()


    # ========================================================
    # 10. Position 읽기
    # ========================================================

    def read_position(
        self,
        servo_id
    ):

        position, result, error = (
            self.packet_handler.ReadPos(
                int(
                    servo_id
                )
            )
        )


        if (
            result != COMM_SUCCESS
            or error != 0
        ):

            return None


        return int(
            position
        )


    # ========================================================
    # 11. Speed 읽기
    # ========================================================

    def read_speed(
        self,
        servo_id
    ):

        speed, result, error = (
            self.packet_handler.ReadSpeed(
                int(
                    servo_id
                )
            )
        )


        if (
            result != COMM_SUCCESS
            or error != 0
        ):

            return None


        return int(
            speed
        )


    # ========================================================
    # 12. Servo 전체 상태 읽기
    # ========================================================

    def read_state(
        self,
        servo_id
    ):

        servo_id = int(
            servo_id
        )


        # ----------------------------------------------------
        # Position
        # ----------------------------------------------------

        position = (
            self.read_position(
                servo_id
            )
        )


        if position is None:

            return None


        # ----------------------------------------------------
        # Speed
        # ----------------------------------------------------

        speed = (
            self.read_speed(
                servo_id
            )
        )


        # ----------------------------------------------------
        # Load
        # ----------------------------------------------------

        load_raw, result, error = (
            self.packet_handler.read2ByteTxRx(

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


            load_percent = (
                abs(
                    load_value
                )
                / 1000.0
                * 100.0
            )


        else:

            load_value = None

            load_percent = None


        # ----------------------------------------------------
        # Voltage
        # ----------------------------------------------------

        voltage_raw, result, error = (
            self.packet_handler.read1ByteTxRx(

                servo_id,

                ADDR_PRESENT_VOLTAGE
            )
        )


        voltage = (

            voltage_raw
            * 0.1

            if (
                result == COMM_SUCCESS
                and error == 0
            )

            else None
        )


        # ----------------------------------------------------
        # Temperature
        # ----------------------------------------------------

        temperature, result, error = (
            self.packet_handler.read1ByteTxRx(

                servo_id,

                ADDR_PRESENT_TEMPERATURE
            )
        )


        if not (
            result == COMM_SUCCESS
            and error == 0
        ):

            temperature = None


        # ----------------------------------------------------
        # Current
        # ----------------------------------------------------
        #
        # mA 환산계수는 최종 데이터시트 기준을
        # 별도로 확정할 예정이므로
        # 현재 패키지에서는 raw 값 그대로 반환한다.

        current_raw, result, error = (
            self.packet_handler.read2ByteTxRx(

                servo_id,

                ADDR_PRESENT_CURRENT
            )
        )


        if not (
            result == COMM_SUCCESS
            and error == 0
        ):

            current_raw = None


        # ----------------------------------------------------
        # Moving
        # ----------------------------------------------------

        moving, result, error = (
            self.packet_handler.read1ByteTxRx(

                servo_id,

                ADDR_MOVING
            )
        )


        if not (
            result == COMM_SUCCESS
            and error == 0
        ):

            moving = None


        # ----------------------------------------------------
        # 결과
        # ----------------------------------------------------

        return {

            "position":
                position,

            "speed":
                speed,

            "load":
                load_value,

            "load_percent":
                load_percent,

            "voltage":
                voltage,

            "temperature":
                temperature,

            "current_raw":
                current_raw,

            "moving":
                moving,
        }