"""
motor_control/controller.py

[파이프라인에서의 역할]
다른 팀원이 실제 AI/센서/조건 로직에서 사용하는 상위 Motor API이다.

팀원이 기본적으로 지정하는 값:
- joint_name
- angle 또는 delta_angle
- speed

선택 인자:
- acc (기본 10)
- wait (기본 True)
- timeout

[팀원용 방향]
- shoulder_lift : + = 위,  - = 아래
- elbow_flex    : + = 위,  - = 아래
- wrist_flex    : + = 위,  - = 아래
- wrist_roll    : + = CW,  - = CCW

[Emergency Stop]
emergency_stop()이 호출되면:
1. 소프트웨어 Emergency latch를 즉시 ON한다.
2. 모든 Servo Torque를 Sync Write로 OFF한다.
3. 이후 모든 이동 API를 차단한다.

중요:
이 E-Stop은 '소프트웨어 Torque OFF' 기능이다.
전원 자체를 물리적으로 끊는 하드웨어 비상정지와 동일하지 않다.
"""

import threading
import time

from .config import (
    DEFAULT_ACC,
    DEFAULT_WAIT,
    DEFAULT_TIMEOUT_SEC,
    POSITION_TOLERANCE,
    POLL_INTERVAL_SEC,
)
from .calibration import CalibrationManager, CalibrationError
from .servo_driver import ServoDriver


class MotorController:
    """팀원용 상위 모터 제어 API."""

    def __init__(self, calibration_file=None):
        # ----------------------------------------------------
        # Calibration Load
        # ----------------------------------------------------
        if calibration_file is None:
            self.calibration = CalibrationManager()
        else:
            self.calibration = CalibrationManager(calibration_file)

        # ----------------------------------------------------
        # STServo Driver
        # ----------------------------------------------------
        self.driver = ServoDriver(
            device=self.calibration.device,
            baudrate=self.calibration.baudrate,
        )

        # ----------------------------------------------------
        # Emergency Stop latch
        # ----------------------------------------------------
        # threading.Event를 사용해 다른 Thread에서 E-Stop을 호출해도
        # 이동 함수가 같은 상태를 안전하게 확인할 수 있게 한다.
        self._emergency_event = threading.Event()

        # 이동 명령 송신과 E-Stop Torque OFF 송신이 서로 경합하지 않도록 보호한다.
        # wait 구간에서는 이 Lock을 잡지 않으므로, 이동 중 다른 Thread의 E-Stop 호출은 가능하다.
        self._command_lock = threading.RLock()

    # ========================================================
    # 공통 Error / Emergency 검사
    # ========================================================

    @staticmethod
    def _print_error(error):
        print(f"[MOTOR ERROR] {error}")

    def _check_emergency_state(self):
        if self._emergency_event.is_set():
            self._print_error(
                "Emergency Stop 상태입니다. "
                "모든 모터 이동 명령이 차단되어 있습니다."
            )
            return False

        return True

    def is_emergency_stopped(self):
        """현재 Emergency Stop latch 상태를 반환한다."""
        return self._emergency_event.is_set()

    # ========================================================
    # Emergency Stop
    # ========================================================

    def emergency_stop(self):
        """
        모든 Servo Torque를 OFF하고 이후 모든 이동 명령을 차단한다.

        사용 목적:
        - 모터/로봇팔 끼임
        - 예상치 못한 동작
        - 모터가 목표 위치로 가려고 계속 힘을 주는 상황

        주의:
        Torque OFF 순간 로봇팔이 중력으로 떨어질 수 있다.
        """
        # Torque OFF 전부터 새로운 이동 명령을 막는다.
        self._emergency_event.set()

        servo_ids = sorted(self.calibration.servos_by_id.keys())

        try:
            with self._command_lock:
                success = self.driver.disable_torque_all_sync(servo_ids)
        except Exception as error:
            # 통신 예외가 발생해도 Emergency latch는 절대 자동 해제하지 않는다.
            self._print_error(
                f"Emergency Stop Torque OFF 전송 중 오류: {error}"
            )
            return False

        if not success:
            # 송신 실패여도 latch는 유지한다.
            self._print_error(
                "Emergency Stop Torque OFF 패킷 전송에 실패했습니다. "
                "Emergency 상태는 계속 유지됩니다."
            )
            return False

        print(
            "[EMERGENCY STOP] 모든 Servo에 Torque OFF 명령을 전송했습니다. "
            "이후 이동 명령은 차단됩니다."
        )
        return True

    # ========================================================
    # 1. Zero 기준 절대각도 제어
    # ========================================================

    def move_joint(
        self,
        joint_name,
        angle,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC,
    ):
        """
        Zero Position을 0°로 보고 최종 목표 각도로 이동한다.

        예:
            move_joint("shoulder_lift", 30, 100)
            -> 현재 위치와 관계없이 팀원 기준 +30° 위치로 이동

            move_joint("wrist_roll", 30, 100)
            -> CW +30° 위치로 이동
        """
        if not self._check_emergency_state():
            return False

        try:
            speed = self.calibration.validate_speed(joint_name, speed)
            acc = self.calibration.validate_acc(acc)
            target_position = self.calibration.command_angle_to_position(
                joint_name,
                angle,
            )
            servo = self.calibration.get_joint(joint_name)
            servo_id = int(servo["servo_id"])

        except CalibrationError as error:
            self._print_error(error)
            return False

        # 검증 후 실제 쓰기 직전에도 E-Stop 상태를 한 번 더 확인한다.
        # 이 확인과 실제 송신을 같은 command lock 안에서 처리해
        # E-Stop 직후 새 Position 명령이 경합해서 들어가는 것을 막는다.
        with self._command_lock:
            if not self._check_emergency_state():
                return False

            success = self.driver.write_position(
                servo_id=servo_id,
                position=target_position,
                speed=speed,
                acc=acc,
            )

        if not success:
            self._print_error(f"{joint_name} 이동 명령 실패")
            return False

        if not wait:
            return True

        return self._wait_for_targets(
            {servo_id: target_position},
            timeout=timeout,
        )

    # ========================================================
    # 2. 현재 위치 기준 상대각도 제어
    # ========================================================

    def move_joint_relative(
        self,
        joint_name,
        delta_angle,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC,
    ):
        """
        현재 실제 위치를 기준으로 delta_angle만큼 추가 이동한다.

        예:
            현재 shoulder_lift = +20°
            delta_angle = +10°
            -> 최종 +30°

            wrist_roll delta_angle = +10°
            -> 현재 위치에서 CW로 10° 추가 이동
        """
        if not self._check_emergency_state():
            return False

        try:
            servo = self.calibration.require_position_calibrated(joint_name)
            servo_id = int(servo["servo_id"])

            current_position = self.driver.read_position(servo_id)
            if current_position is None:
                self._print_error(f"{joint_name} 현재 Position 읽기 실패")
                return False

            current_angle = self.calibration.position_to_command_angle(
                joint_name,
                current_position,
            )

            target_angle = current_angle + float(delta_angle)

        except (CalibrationError, TypeError, ValueError) as error:
            self._print_error(error)
            return False

        # 최종 목표각은 절대각도 함수에 넘겨 동일한 안전검사를 적용한다.
        return self.move_joint(
            joint_name=joint_name,
            angle=target_angle,
            speed=speed,
            acc=acc,
            wait=wait,
            timeout=timeout,
        )

    # ========================================================
    # 3. 여러 Joint 동시 제어
    # ========================================================

    def move_joints(
        self,
        targets,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC,
    ):
        """
        여러 Joint 목표를 모두 먼저 검증한 뒤 Sync Write로 같이 시작한다.

        targets 예:
            {
                "shoulder_lift": 30,
                "elbow_flex": 20,
                "wrist_flex": -10,
                "wrist_roll": 15,
            }

        하나라도 Calibration / Speed / Safe Range 검증에 실패하면
        실제 Servo에는 아무 명령도 보내지 않는다.
        """
        if not self._check_emergency_state():
            return False

        if not isinstance(targets, dict):
            self._print_error("targets는 dict여야 합니다.")
            return False

        if not targets:
            self._print_error("targets가 비어 있습니다.")
            return False

        sync_commands = {}
        wait_targets = {}

        try:
            acc = self.calibration.validate_acc(acc)

            for joint_name, angle in targets.items():
                joint_speed = self.calibration.validate_speed(
                    joint_name,
                    speed,
                )

                target_position = self.calibration.command_angle_to_position(
                    joint_name,
                    angle,
                )

                servo = self.calibration.get_joint(joint_name)
                servo_id = int(servo["servo_id"])

                sync_commands[servo_id] = {
                    "position": target_position,
                    "speed": joint_speed,
                    "acc": acc,
                }

                wait_targets[servo_id] = target_position

        except CalibrationError as error:
            self._print_error(error)
            return False

        # 모든 계산/검증이 끝난 직후에도 E-Stop 상태를 재확인한다.
        # 확인 + SyncWrite를 같은 command lock 안에서 처리한다.
        with self._command_lock:
            if not self._check_emergency_state():
                return False

            success = self.driver.sync_write_positions(sync_commands)

        if not success:
            self._print_error("여러 Joint 동기 이동 명령 실패")
            return False

        if not wait:
            return True

        return self._wait_for_targets(
            wait_targets,
            timeout=timeout,
        )

    # ========================================================
    # 4. Zero 이동
    # ========================================================

    def move_to_zero(
        self,
        joint_name,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC,
    ):
        return self.move_joint(
            joint_name=joint_name,
            angle=0.0,
            speed=speed,
            acc=acc,
            wait=wait,
            timeout=timeout,
        )

    def move_all_to_zero(
        self,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC,
    ):
        if not self._check_emergency_state():
            return False

        targets = {
            joint_name: 0.0
            for joint_name in self.calibration.servos_by_joint.keys()
        }

        return self.move_joints(
            targets=targets,
            speed=speed,
            acc=acc,
            wait=wait,
            timeout=timeout,
        )

    # ========================================================
    # 5. 현재 각도 / 상태 읽기
    # ========================================================
    # 상태 읽기는 E-Stop 상태에서도 허용한다.
    # 비상정지 후에도 현재 Position/온도 등을 확인할 수 있어야 하기 때문이다.

    def get_joint_angle(self, joint_name):
        try:
            servo = self.calibration.require_position_calibrated(joint_name)
            servo_id = int(servo["servo_id"])

            position = self.driver.read_position(servo_id)
            if position is None:
                self._print_error(f"{joint_name} Position 읽기 실패")
                return None

            return self.calibration.position_to_command_angle(
                joint_name,
                position,
            )

        except CalibrationError as error:
            self._print_error(error)
            return None

    def get_joint_state(self, joint_name):
        try:
            servo = self.calibration.require_position_calibrated(joint_name)
            servo_id = int(servo["servo_id"])

            state = self.driver.read_state(servo_id)
            if state is None:
                self._print_error(f"{joint_name} 상태 읽기 실패")
                return None

            angle = self.calibration.position_to_command_angle(
                joint_name,
                state["position"],
            )

            return {
                "joint": joint_name,
                "angle": angle,
                "speed": state["speed"],
                "load": state["load"],
                "load_percent": state["load_percent"],
                "voltage": state["voltage"],
                "temperature": state["temperature"],
                "current_raw": state["current_raw"],
                "moving": (
                    None
                    if state["moving"] is None
                    else bool(state["moving"])
                ),
            }

        except CalibrationError as error:
            self._print_error(error)
            return None

    def get_all_states(self):
        return {
            joint_name: self.get_joint_state(joint_name)
            for joint_name in self.calibration.servos_by_joint.keys()
        }

    def is_moving(self, joint_name):
        state = self.get_joint_state(joint_name)
        if state is None:
            return None
        return state["moving"]

    # ========================================================
    # 6. wait=True 목표 도착 대기
    # ========================================================

    def _wait_for_targets(self, targets_by_servo_id, timeout):
        start_time = time.monotonic()

        while time.monotonic() - start_time < float(timeout):
            # 다른 Thread에서 emergency_stop()이 호출되면 즉시 wait를 끝낸다.
            if self._emergency_event.is_set():
                self._print_error(
                    "Emergency Stop이 발생하여 목표 도착 대기를 중단합니다."
                )
                return False

            all_arrived = True

            for servo_id, target_position in targets_by_servo_id.items():
                state = self.driver.read_state(servo_id)

                if state is None:
                    self._print_error(
                        f"Servo ID {servo_id} 상태 읽기 실패"
                    )
                    return False

                position_error = abs(
                    state["position"] - target_position
                )
                moving = state["moving"]

                if not (
                    moving == 0
                    and position_error <= POSITION_TOLERANCE
                ):
                    all_arrived = False

            if all_arrived:
                return True

            time.sleep(POLL_INTERVAL_SEC)

        self._print_error(f"목표 도착 Timeout: {timeout} sec")
        return False

    # ========================================================
    # 7. 종료
    # ========================================================

    def close(self):
        """
        Serial Port를 닫는다.

        주의:
        close()는 Emergency Stop이 아니며 Torque를 자동으로 OFF하지 않는다.
        """
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
