"""
motor_control/servo_driver.py

[파이프라인에서의 역할]
STServo Python SDK와 직접 통신하는 저수준 Driver이다.

입력:
- Servo ID
- raw Position
- Speed
- Acc
- Torque ON/OFF 값

출력:
- 통신 성공/실패
- Position / Speed / Load / Voltage / Temperature / Current / Moving

이 파일에서는 Joint 이름, Zero, 각도 방향, Safe Range를 판단하지 않는다.
그 책임은 calibration.py와 controller.py에 있다.

Emergency Stop:
- Torque Enable 주소에 0을 Sync Write하여
  여러 Servo Torque를 한 패킷으로 OFF한다.
- 이는 현재 위치 Hold가 아니라
  Servo가 힘을 주지 않도록 Torque를 해제하는 동작이다.
"""

import sys
import threading

from .config import (
    SDK_PATH,
    ADDR_TORQUE_ENABLE,
    TORQUE_OFF,
    TORQUE_ON,
)


# ============================================================
# 1. STServo SDK 경로
# ============================================================

if SDK_PATH not in sys.path:

    sys.path.append(
        SDK_PATH
    )


# 기존 프로젝트에서 사용 중인 SDK import 방식 유지
from port_handler import PortHandler
from sms_sts import sms_sts
from scservo_def import COMM_SUCCESS


# ============================================================
# 2. STS 상태 레지스터
# ============================================================

ADDR_PRESENT_LOAD = 60
ADDR_PRESENT_VOLTAGE = 62
ADDR_PRESENT_TEMPERATURE = 63
ADDR_MOVING = 66
ADDR_PRESENT_CURRENT = 69


# ============================================================
# 3. Servo Driver
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


        # ----------------------------------------------------
        # Serial 통신 Lock
        # ----------------------------------------------------
        #
        # 여러 Thread에서
        #
        # - 모터 제어
        # - 상태 읽기
        # - Emergency Stop
        #
        # 을 동시에 호출해도
        # Serial 패킷이 서로 섞이지 않게 한다.

        self._io_lock = (
            threading.RLock()
        )


        self.is_open = False


        self.open()


    # ========================================================
    # 4. Port Open
    # ========================================================

    def open(
        self
    ):

        with self._io_lock:

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
    # 5. Port Close
    # ========================================================

    def close(
        self
    ):

        with self._io_lock:

            if self.is_open:

                self.port_handler.closePort()

                self.is_open = False


    # ========================================================
    # 6. Ping
    # ========================================================

    def ping(
        self,
        servo_id
    ):

        with self._io_lock:

            (
                model_number,
                result,
                error
            ) = (
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
    # 7. 단일 Servo 이동
    # ========================================================

    def write_position(
        self,
        servo_id,
        position,
        speed,
        acc
    ):

        with self._io_lock:

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
    # 8. 여러 Servo 위치 동기 이동
    # ========================================================
    #
    # SyncWritePosEx()를 이용해
    # 각 Servo Parameter를 먼저 버퍼에 추가하고
    #
    # groupSyncWrite.txPacket()
    #
    # 한 번으로 전송한다.

    def sync_write_positions(
        self,
        commands
    ):

        group_sync_write = (
            self.packet_handler.groupSyncWrite
        )


        with self._io_lock:

            group_sync_write.clearParam()


            try:

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


                result = (
                    group_sync_write.txPacket()
                )


                return (
                    result
                    == COMM_SUCCESS
                )


            finally:

                group_sync_write.clearParam()


    # ========================================================
    # 9. 단일 Servo Torque 설정
    # ========================================================

    def set_torque(
        self,
        servo_id,
        enabled
    ):

        value = (
            TORQUE_ON
            if enabled
            else TORQUE_OFF
        )


        with self._io_lock:

            result, error = (
                self.packet_handler.write1ByteTxRx(

                    int(
                        servo_id
                    ),

                    ADDR_TORQUE_ENABLE,

                    value
                )
            )


        return (
            result == COMM_SUCCESS
            and error == 0
        )


    # ========================================================
    # 10. 전체 Servo Torque 동기 OFF
    # ========================================================
    #
    # Emergency Stop 전용.
    #
    # Servo 1 → Servo 2 → Servo 3 → Servo 4
    # 순서로 하나씩 끄는 것이 아니라
    #
    # Sync Write Parameter:
    #
    # [ID1, 0, ID2, 0, ID3, 0, ID4, 0]
    #
    # 을 만들어 Torque Enable 주소 40에
    # 한 번의 Sync Write 패킷으로 전송한다.
    #
    # 중요:
    # Sync Write는 각 Servo의 응답을 기다리지 않는다.
    # 따라서 반환값은 패킷 송신 성공 여부다.

    def disable_torque_all_sync(
        self,
        servo_ids
    ):

        servo_ids = [
            int(
                servo_id
            )

            for servo_id
            in servo_ids
        ]


        if not servo_ids:

            return False


        params = []


        for servo_id in servo_ids:

            params.extend(
                [
                    servo_id,
                    TORQUE_OFF,
                ]
            )


        with self._io_lock:

            result = (
                self.packet_handler.syncWriteTxOnly(

                    ADDR_TORQUE_ENABLE,

                    1,

                    params,

                    len(
                        params
                    )
                )
            )


        return (
            result
            == COMM_SUCCESS
        )


    # ========================================================
    # 11. Position 읽기
    # ========================================================

    def read_position(
        self,
        servo_id
    ):

        with self._io_lock:

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
    # 12. Speed 읽기
    # ========================================================

    def read_speed(
        self,
        servo_id
    ):

        with self._io_lock:

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
    # 13. Servo 전체 상태 읽기
    # ========================================================

    def read_state(
        self,
        servo_id
    ):

        servo_id = int(
            servo_id
        )


        # ----------------------------------------------------
        # 하나의 Servo 상태를 읽는 동안
        # 다른 Thread의 패킷이 사이에 끼지 않게 보호
        # ----------------------------------------------------

        with self._io_lock:

            # Position
            (
                position,
                result,
                error
            ) = (
                self.packet_handler.ReadPos(
                    servo_id
                )
            )


            if (
                result != COMM_SUCCESS
                or error != 0
            ):

                return None


            position = int(
                position
            )


            # Speed
            (
                speed,
                result,
                error
            ) = (
                self.packet_handler.ReadSpeed(
                    servo_id
                )
            )


            if (
                result != COMM_SUCCESS
                or error != 0
            ):

                speed = None

            else:

                speed = int(
                    speed
                )


            # Load
            (
                load_raw,
                result,
                error
            ) = (
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
                    load_raw
                    & 0x03FF
                )


                if (
                    load_raw
                    & 0x0400
                ):

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


            # Voltage
            (
                voltage_raw,
                result,
                error
            ) = (
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


            # Temperature
            (
                temperature,
                result,
                error
            ) = (
                self.packet_handler.read1ByteTxRx(

                    servo_id,

                    ADDR_PRESENT_TEMPERATURE
                )
            )


            if (
                result != COMM_SUCCESS
                or error != 0
            ):

                temperature = None


            # Current
            #
            # mA 변환계수는 아직 최종 데이터시트 기준으로
            # 확정하지 않았으므로 raw 값 그대로 반환.
            (
                current_raw,
                result,
                error
            ) = (
                self.packet_handler.read2ByteTxRx(

                    servo_id,

                    ADDR_PRESENT_CURRENT
                )
            )


            if (
                result != COMM_SUCCESS
                or error != 0
            ):

                current_raw = None


            # Moving
            (
                moving,
                result,
                error
            ) = (
                self.packet_handler.read1ByteTxRx(

                    servo_id,

                    ADDR_MOVING
                )
            )


            if (
                result != COMM_SUCCESS
                or error != 0
            ):

                moving = None


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