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
- Torque Enable 주소에 0을 Sync Write하여 여러 Servo Torque를 한 패킷으로 OFF한다.
- 이는 현재 위치 Hold가 아니라 Servo가 힘을 주지 않도록 Torque를 해제하는 동작이다.
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
    sys.path.append(SDK_PATH)


# 현재 프로젝트에서 기존부터 사용한 SDK import 방식 유지
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


class ServoDriver:
    """STServo 통신 전담 Driver."""

    def __init__(self, device, baudrate):
        self.device = device
        self.baudrate = int(baudrate)

        self.port_handler = PortHandler(self.device)
        self.packet_handler = sms_sts(self.port_handler)

        # 여러 Thread에서 제어/상태 읽기/E-Stop을 동시에 호출할 경우
        # 하나의 Serial Port 패킷이 서로 섞이지 않도록 보호한다.
        self._io_lock = threading.RLock()

        self.is_open = False
        self.open()

    # ========================================================
    # Port Open / Close
    # ========================================================

    def open(self):
        with self._io_lock:
            if self.is_open:
                return True

            if not self.port_handler.openPort():
                raise RuntimeError(
                    f"Servo Port Open 실패: {self.device}"
                )

            if not self.port_handler.setBaudRate(self.baudrate):
                self.port_handler.closePort()
                raise RuntimeError(
                    f"Servo Baudrate 설정 실패: {self.baudrate}"
                )

            self.is_open = True
            return True

    def close(self):
        with self._io_lock:
            if self.is_open:
                self.port_handler.closePort()
                self.is_open = False

    # ========================================================
    # Ping
    # ========================================================

    def ping(self, servo_id):
        with self._io_lock:
            model_number, result, error = self.packet_handler.ping(
                int(servo_id)
            )

        success = result == COMM_SUCCESS and error == 0

        return {
            "success": success,
            "model_number": model_number if success else None,
            "result": result,
            "error": error,
        }

    # ========================================================
    # 단일 Servo 위치 이동
    # ========================================================

    def write_position(self, servo_id, position, speed, acc):
        with self._io_lock:
            result, error = self.packet_handler.WritePosEx(
                int(servo_id),
                int(position),
                int(speed),
                int(acc),
            )

        return result == COMM_SUCCESS and error == 0

    # ========================================================
    # 여러 Servo 위치 동기 이동
    # ========================================================
    # SyncWritePosEx()로 각 Servo의 Position/Speed/Acc를 먼저 버퍼에 넣고,
    # groupSyncWrite.txPacket() 한 번으로 전송한다.

    def sync_write_positions(self, commands):
        group_sync_write = self.packet_handler.groupSyncWrite

        with self._io_lock:
            group_sync_write.clearParam()

            try:
                for servo_id, command in commands.items():
                    added = self.packet_handler.SyncWritePosEx(
                        int(servo_id),
                        int(command["position"]),
                        int(command["speed"]),
                        int(command["acc"]),
                    )

                    if not added:
                        return False

                result = group_sync_write.txPacket()
                return result == COMM_SUCCESS

            finally:
                group_sync_write.clearParam()

    # ========================================================
    # Torque 제어
    # ========================================================

    def set_torque(self, servo_id, enabled):
        """
        단일 Servo Torque ON/OFF.

        현재 공개 Controller API에서는 E-Stop의 OFF 동작만 사용한다.
        """
        value = TORQUE_ON if enabled else TORQUE_OFF

        with self._io_lock:
            result, error = self.packet_handler.write1ByteTxRx(
                int(servo_id),
                ADDR_TORQUE_ENABLE,
                value,
            )

        return result == COMM_SUCCESS and error == 0

    def disable_torque_all_sync(self, servo_ids):
        """
        Emergency Stop용 전체 Torque OFF.

        각 Servo를 순서대로 write1ByteTxRx()하는 대신,
        Protocol의 syncWriteTxOnly()를 이용해 Torque Enable 주소(40)에
        0을 한 패킷으로 전송한다.

        Sync Write는 개별 Servo의 응답 패킷을 기다리지 않으므로
        반환값은 '송신 자체가 성공했는지'를 의미한다.
        실제 Torque 상태 확인이 필요하면 이후 별도로 읽어야 한다.
        """
        servo_ids = [int(servo_id) for servo_id in servo_ids]

        if not servo_ids:
            return False

        # Sync Write parameter 형식:
        # [ID1, DATA1, ID2, DATA2, ...]
        params = []
        for servo_id in servo_ids:
            params.extend([servo_id, TORQUE_OFF])

        with self._io_lock:
            result = self.packet_handler.syncWriteTxOnly(
                ADDR_TORQUE_ENABLE,
                1,                  # Torque Enable은 1 byte
                params,
                len(params),
            )

        return result == COMM_SUCCESS

    # ========================================================
    # Position / Speed 읽기
    # ========================================================

    def read_position(self, servo_id):
        with self._io_lock:
            position, result, error = self.packet_handler.ReadPos(
                int(servo_id)
            )

        if result != COMM_SUCCESS or error != 0:
            return None

        return int(position)

    def read_speed(self, servo_id):
        with self._io_lock:
            speed, result, error = self.packet_handler.ReadSpeed(
                int(servo_id)
            )

        if result != COMM_SUCCESS or error != 0:
            return None

        return int(speed)

    # ========================================================
    # Servo 상태 읽기
    # ========================================================

    def read_state(self, servo_id):
        servo_id = int(servo_id)

        # 한 Servo의 상태 묶음을 읽는 동안 다른 Thread의 패킷과 섞이지 않도록
        # 전체 읽기 구간을 하나의 RLock으로 보호한다.
        with self._io_lock:
            position, result, error = self.packet_handler.ReadPos(servo_id)
            if result != COMM_SUCCESS or error != 0:
                return None
            position = int(position)

            speed, result, error = self.packet_handler.ReadSpeed(servo_id)
            if result != COMM_SUCCESS or error != 0:
                speed = None
            else:
                speed = int(speed)

            load_raw, result, error = self.packet_handler.read2ByteTxRx(
                servo_id,
                ADDR_PRESENT_LOAD,
            )
            if result == COMM_SUCCESS and error == 0:
                load_value = load_raw & 0x03FF
                if load_raw & 0x0400:
                    load_value = -load_value
                load_percent = abs(load_value) / 1000.0 * 100.0
            else:
                load_value = None
                load_percent = None

            voltage_raw, result, error = self.packet_handler.read1ByteTxRx(
                servo_id,
                ADDR_PRESENT_VOLTAGE,
            )
            voltage = (
                voltage_raw * 0.1
                if result == COMM_SUCCESS and error == 0
                else None
            )

            temperature, result, error = self.packet_handler.read1ByteTxRx(
                servo_id,
                ADDR_PRESENT_TEMPERATURE,
            )
            if result != COMM_SUCCESS or error != 0:
                temperature = None

            # 전류는 mA 변환계수를 아직 최종 데이터시트 기준으로 확정하지 않았으므로
            # 현재 패키지에서는 raw 값 그대로 제공한다.
            current_raw, result, error = self.packet_handler.read2ByteTxRx(
                servo_id,
                ADDR_PRESENT_CURRENT,
            )
            if result != COMM_SUCCESS or error != 0:
                current_raw = None

            moving, result, error = self.packet_handler.read1ByteTxRx(
                servo_id,
                ADDR_MOVING,
            )
            if result != COMM_SUCCESS or error != 0:
                moving = None

        return {
            "position": position,
            "speed": speed,
            "load": load_value,
            "load_percent": load_percent,
            "voltage": voltage,
            "temperature": temperature,
            "current_raw": current_raw,
            "moving": moving,
        }
