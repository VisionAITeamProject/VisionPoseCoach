"""
motor_control/calibration.py

[파이프라인에서의 역할]
servo_calibration_result.json에 저장된 실제 하드웨어 Calibration 결과를 읽고,
팀원이 사용하는 각도와 STS raw Position 사이를 변환한다.

입력:
- Joint 이름
- 팀원용 각도(deg)
- Servo Calibration JSON

출력:
- Servo ID
- 안전 검증된 raw Position
- 팀원 기준 현재 각도

중요:
이 파일은 Calibration JSON을 읽기만 하며 수정하거나 저장하지 않는다.
팀원용 motor_control 패키지에서는 Calibration이 완료되지 않은 모터의 RAW 제어를 허용하지 않는다.
"""

import json
import os

from .config import (
    CALIBRATION_FILE,
    DEFAULT_DEVICE,
    DEFAULT_BAUDRATE,
    STS_POSITION_MIN,
    STS_POSITION_MAX,
    POSITION_PER_DEGREE,
    DEGREE_PER_POSITION,
    COMMAND_TO_URDF_DIRECTION,
    EXPECTED_RAW_SIGN_FOR_POSITIVE_COMMAND,
    MIN_ACC,
    MAX_ACC,
)


class CalibrationError(Exception):
    """Calibration/안전 검증 과정에서 발생한 오류."""


class CalibrationManager:
    """Calibration JSON 로드 및 각도/Position 변환 담당."""

    def __init__(self, calibration_file=CALIBRATION_FILE):
        self.calibration_file = calibration_file
        self.device = DEFAULT_DEVICE
        self.baudrate = DEFAULT_BAUDRATE
        self.servos_by_id = {}
        self.servos_by_joint = {}

        self._load()
        self._validate_direction_configuration()

    # ========================================================
    # Calibration JSON 읽기
    # ========================================================

    def _load(self):
        if not os.path.exists(self.calibration_file):
            raise CalibrationError(
                f"Calibration 파일이 없습니다: {self.calibration_file}"
            )

        try:
            with open(self.calibration_file, "r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception as error:
            raise CalibrationError(
                f"Calibration JSON 읽기 실패: {error}"
            ) from error

        self.device = data.get("device", DEFAULT_DEVICE)
        self.baudrate = int(data.get("baudrate", DEFAULT_BAUDRATE))

        saved_servos = data.get("servos", {})
        if not saved_servos:
            raise CalibrationError("Calibration JSON에 Servo 정보가 없습니다.")

        for servo_id_text, servo_data in saved_servos.items():
            try:
                servo_id = int(servo_id_text)
            except (TypeError, ValueError):
                continue

            joint = servo_data.get("joint")
            if not joint:
                continue

            servo = dict(servo_data)
            servo["servo_id"] = servo_id

            self.servos_by_id[servo_id] = servo
            self.servos_by_joint[joint] = servo

    # ========================================================
    # 방향 설정 자체 검증
    # ========================================================
    # 팀원 +각도에 대한 raw Position 변화 방향은
    # calibration_direction * command_direction 으로 결정된다.
    #
    # wrist_roll 최종 실측/팀원 기준:
    #   raw 증가              = CW
    #   raw 감소              = CCW
    #   calibration direction = -1   (URDF + -> raw 감소 -> CCW)
    #   command direction     = -1   (TEAM + -> URDF -)
    #   결과                  = +1
    # 즉 TEAM + -> raw 증가 -> 실제 CW.

    def _validate_direction_configuration(self):
        for joint, expected_raw_sign in (
            EXPECTED_RAW_SIGN_FOR_POSITIVE_COMMAND.items()
        ):
            servo = self.servos_by_joint.get(joint)
            if servo is None:
                raise CalibrationError(f"Joint 정보가 없습니다: {joint}")

            calibration_direction = servo.get("direction")
            command_direction = COMMAND_TO_URDF_DIRECTION.get(joint)

            if calibration_direction not in (-1, +1):
                raise CalibrationError(
                    f"{joint} calibration direction 값 오류: "
                    f"{calibration_direction}"
                )

            if command_direction not in (-1, +1):
                raise CalibrationError(
                    f"{joint} command direction 값 오류: {command_direction}"
                )

            actual_raw_sign = calibration_direction * command_direction

            if actual_raw_sign != expected_raw_sign:
                raise CalibrationError(
                    "[DIRECTION ERROR] "
                    f"{joint}: expected={expected_raw_sign:+d}, "
                    f"actual={actual_raw_sign:+d}"
                )

    # ========================================================
    # Joint 조회 / Calibration 완료 확인
    # ========================================================

    def get_joint(self, joint_name):
        servo = self.servos_by_joint.get(joint_name)

        if servo is None:
            available = ", ".join(self.servos_by_joint.keys())
            raise CalibrationError(
                f"알 수 없는 Joint: {joint_name}. 사용 가능: {available}"
            )

        return servo

    def require_position_calibrated(self, joint_name):
        """
        팀원용 각도제어에 반드시 필요한 Calibration 값이 있는지 검사한다.
        """
        servo = self.get_joint(joint_name)

        required = (
            "zero_position",
            "safe_position_at_min_angle",
            "safe_position_at_max_angle",
        )

        missing = [key for key in required if servo.get(key) is None]

        if missing:
            raise CalibrationError(
                f"{joint_name} Calibration 미완료: " + ", ".join(missing)
            )

        return servo

    # ========================================================
    # Speed / Acc 검증
    # ========================================================

    def validate_speed(self, joint_name, speed):
        servo = self.require_position_calibrated(joint_name)

        try:
            speed = int(speed)
        except (TypeError, ValueError):
            raise CalibrationError(f"Speed는 정수여야 합니다: {speed}")

        if speed <= 0:
            raise CalibrationError(f"Speed는 1 이상이어야 합니다: {speed}")

        max_speed = servo.get("max_speed")
        if max_speed is None:
            raise CalibrationError(
                f"{joint_name} max_speed가 아직 설정되지 않았습니다."
            )

        max_speed = int(max_speed)

        if speed > max_speed:
            raise CalibrationError(
                f"{joint_name} Speed 초과: 요청={speed}, 최대={max_speed}"
            )

        return speed

    @staticmethod
    def validate_acc(acc):
        try:
            acc = int(acc)
        except (TypeError, ValueError):
            raise CalibrationError(f"acc는 정수여야 합니다: {acc}")

        if not (MIN_ACC <= acc <= MAX_ACC):
            raise CalibrationError(
                f"acc 허용범위: {MIN_ACC} ~ {MAX_ACC}"
            )

        return acc

    # ========================================================
    # 팀원용 각도 -> raw Position
    # ========================================================

    def command_angle_to_position(self, joint_name, angle_deg):
        servo = self.require_position_calibrated(joint_name)

        try:
            angle_deg = float(angle_deg)
        except (TypeError, ValueError):
            raise CalibrationError(f"Angle은 숫자여야 합니다: {angle_deg}")

        zero_position = int(servo["zero_position"])
        calibration_direction = int(servo["direction"])
        command_direction = int(COMMAND_TO_URDF_DIRECTION[joint_name])

        # 팀원용 각도 -> URDF 각도
        urdf_angle_deg = angle_deg * command_direction

        # URDF 각도 -> STS raw Position
        target_position = int(
            round(
                zero_position
                + calibration_direction
                * urdf_angle_deg
                * POSITION_PER_DEGREE
            )
        )

        self.validate_target_position(joint_name, target_position)
        return target_position

    # ========================================================
    # raw Position -> 팀원용 각도
    # ========================================================

    def position_to_command_angle(self, joint_name, position):
        servo = self.require_position_calibrated(joint_name)

        position = int(position)
        zero_position = int(servo["zero_position"])
        calibration_direction = int(servo["direction"])
        command_direction = int(COMMAND_TO_URDF_DIRECTION[joint_name])

        # raw Position -> URDF 각도
        urdf_angle_deg = (
            (position - zero_position)
            * calibration_direction
            * DEGREE_PER_POSITION
        )

        # URDF 각도 -> 팀원용 각도
        command_angle_deg = urdf_angle_deg * command_direction
        return float(command_angle_deg)

    # ========================================================
    # Safe Range
    # ========================================================

    def get_safe_position_range(self, joint_name):
        servo = self.require_position_calibrated(joint_name)

        side_a = int(servo["safe_position_at_min_angle"])
        side_b = int(servo["safe_position_at_max_angle"])

        # direction=-1인 Joint도 있으므로 숫자 기준으로 다시 정렬한다.
        return min(side_a, side_b), max(side_a, side_b)

    def get_safe_angle_range(self, joint_name):
        servo = self.require_position_calibrated(joint_name)

        angle_a = self.position_to_command_angle(
            joint_name,
            servo["safe_position_at_min_angle"],
        )
        angle_b = self.position_to_command_angle(
            joint_name,
            servo["safe_position_at_max_angle"],
        )

        return min(angle_a, angle_b), max(angle_a, angle_b)

    def validate_target_position(self, joint_name, target_position):
        target_position = int(target_position)

        if not (STS_POSITION_MIN <= target_position <= STS_POSITION_MAX):
            raise CalibrationError(
                f"{joint_name} STS Position 범위 초과: {target_position}"
            )

        numeric_min, numeric_max = self.get_safe_position_range(joint_name)

        if not (numeric_min <= target_position <= numeric_max):
            angle_min, angle_max = self.get_safe_angle_range(joint_name)
            raise CalibrationError(
                f"{joint_name} 안전범위 초과. "
                f"허용 각도: {angle_min:.2f}° ~ {angle_max:.2f}°"
            )

        return True
