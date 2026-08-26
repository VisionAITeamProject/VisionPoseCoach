"""
motor_control/calibration.py

[역할]
servo_calibration_result.json을 읽어서
팀원이 사용하는 각도와 실제 STS Position 사이의 변환을 담당한다.

이 파일에서는 Calibration JSON을 수정하지 않는다.
읽기 전용으로만 사용한다.

------------------------------------------------------------
[주요 기능]

1. Joint 이름 -> Servo ID / Calibration 정보 조회

2. 팀원용 각도 -> URDF 각도 변환

3. URDF 각도 -> STS raw Position 변환

4. STS Position -> 팀원용 각도 변환

5. 실제 Safe MIN / MAX 범위 검사

6. Servo별 max_speed 검사

7. 방향 설정 자체 검증

------------------------------------------------------------
[최종 팀원용 방향]

shoulder_lift
    + = 위
    - = 아래

elbow_flex
    + = 위
    - = 아래

wrist_flex
    + = 위
    - = 아래

wrist_roll
    + = CCW
    - = CW
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


# ============================================================
# 1. Calibration 관련 Error
# ============================================================

class CalibrationError(Exception):
    """
    Calibration 정보 부족,
    잘못된 각도/속도/가속도,
    안전범위 초과 등에 사용한다.
    """


# ============================================================
# 2. Calibration Manager
# ============================================================

class CalibrationManager:

    def __init__(
        self,
        calibration_file=CALIBRATION_FILE
    ):

        self.calibration_file = (
            calibration_file
        )

        self.device = (
            DEFAULT_DEVICE
        )

        self.baudrate = (
            DEFAULT_BAUDRATE
        )

        self.servos_by_id = {}

        self.servos_by_joint = {}


        # Calibration JSON 읽기
        self._load()


        # 방향 설정이 잘못되어 있으면
        # 실제 모터를 움직이기 전에 초기화 단계에서 차단
        self._validate_direction_configuration()


    # ========================================================
    # 3. Calibration JSON 읽기
    # ========================================================

    def _load(self):

        if not os.path.exists(
            self.calibration_file
        ):

            raise CalibrationError(
                "Calibration 파일이 없습니다: "
                f"{self.calibration_file}"
            )


        try:

            with open(
                self.calibration_file,
                "r",
                encoding="utf-8"
            ) as file:

                data = json.load(
                    file
                )


        except Exception as error:

            raise CalibrationError(
                "Calibration JSON 읽기 실패: "
                f"{error}"
            ) from error


        # ----------------------------------------------------
        # 통신 정보
        # ----------------------------------------------------

        self.device = data.get(
            "device",
            DEFAULT_DEVICE
        )


        self.baudrate = int(
            data.get(
                "baudrate",
                DEFAULT_BAUDRATE
            )
        )


        # ----------------------------------------------------
        # Servo 정보
        # ----------------------------------------------------

        saved_servos = data.get(
            "servos",
            {}
        )


        if not saved_servos:

            raise CalibrationError(
                "Calibration JSON에 "
                "Servo 정보가 없습니다."
            )


        # ----------------------------------------------------
        # ID 기준 Dictionary
        # Joint 이름 기준 Dictionary
        #
        # 두 가지 형태로 만들어 놓는다.
        # ----------------------------------------------------

        for (
            servo_id_text,
            servo_data
        ) in saved_servos.items():

            try:

                servo_id = int(
                    servo_id_text
                )

            except (
                TypeError,
                ValueError
            ):

                continue


            joint = servo_data.get(
                "joint"
            )


            if not joint:

                continue


            servo = dict(
                servo_data
            )


            servo[
                "servo_id"
            ] = servo_id


            self.servos_by_id[
                servo_id
            ] = servo


            self.servos_by_joint[
                joint
            ] = servo


    # ========================================================
    # 4. Direction 설정 검증
    # ========================================================
    #
    # 팀원 +각도를 줬을 때 raw Position 변화 방향:
    #
    # Calibration direction
    # ×
    # COMMAND_TO_URDF_DIRECTION
    #
    # 로 결정된다.
    #
    #
    # wrist_roll 예:
    #
    # Calibration direction = -1
    #
    # COMMAND_TO_URDF_DIRECTION = +1
    #
    # -1 × +1 = -1
    #
    # 즉:
    #
    # 팀원 +각도
    # -> raw Position 감소
    # -> 실제 CCW
    #
    # 우리가 확정한
    #
    # wrist_roll + = CCW
    #
    # 와 정확하게 일치한다.

    def _validate_direction_configuration(
        self
    ):

        for (
            joint,
            expected_raw_sign
        ) in (
            EXPECTED_RAW_SIGN_FOR_POSITIVE_COMMAND.items()
        ):

            servo = (
                self.servos_by_joint.get(
                    joint
                )
            )


            if servo is None:

                raise CalibrationError(
                    f"Joint 정보가 없습니다: "
                    f"{joint}"
                )


            calibration_direction = (
                servo.get(
                    "direction"
                )
            )


            command_direction = (
                COMMAND_TO_URDF_DIRECTION.get(
                    joint
                )
            )


            if calibration_direction not in (
                -1,
                +1
            ):

                raise CalibrationError(
                    f"{joint} direction 값 오류: "
                    f"{calibration_direction}"
                )


            if command_direction not in (
                -1,
                +1
            ):

                raise CalibrationError(
                    f"{joint} command direction 값 오류: "
                    f"{command_direction}"
                )


            actual_raw_sign = (
                calibration_direction
                * command_direction
            )


            if (
                actual_raw_sign
                != expected_raw_sign
            ):

                raise CalibrationError(
                    "[DIRECTION ERROR] "
                    f"{joint}: "
                    f"expected={expected_raw_sign:+d}, "
                    f"actual={actual_raw_sign:+d}"
                )


    # ========================================================
    # 5. Joint 이름으로 Servo 정보 조회
    # ========================================================

    def get_joint(
        self,
        joint_name
    ):

        servo = (
            self.servos_by_joint.get(
                joint_name
            )
        )


        if servo is None:

            available = ", ".join(
                self.servos_by_joint.keys()
            )


            raise CalibrationError(
                f"알 수 없는 Joint: "
                f"{joint_name}. "
                f"사용 가능: {available}"
            )


        return servo


    # ========================================================
    # 6. Position Calibration 완료 여부 확인
    # ========================================================
    #
    # 팀원용 motor_control 패키지에서는 RAW MODE를 허용하지 않는다.
    #
    # 반드시 아래 값이 있어야 한다.
    #
    # zero_position
    # safe_position_at_min_angle
    # safe_position_at_max_angle

    def require_position_calibrated(
        self,
        joint_name
    ):

        servo = self.get_joint(
            joint_name
        )


        required = (
            "zero_position",
            "safe_position_at_min_angle",
            "safe_position_at_max_angle",
        )


        missing = [

            key

            for key in required

            if servo.get(
                key
            ) is None
        ]


        if missing:

            raise CalibrationError(
                f"{joint_name} Calibration 미완료: "
                + ", ".join(
                    missing
                )
            )


        return servo


    # ========================================================
    # 7. Speed 검사
    # ========================================================
    #
    # 각 Servo의 max_speed는
    # servo_calibration_result.json에 저장한다.
    #
    # 아직 max_speed=null이면
    # 안전 속도 기준이 정해지지 않은 상태이므로 차단한다.

    def validate_speed(
        self,
        joint_name,
        speed
    ):

        servo = (
            self.require_position_calibrated(
                joint_name
            )
        )


        try:

            speed = int(
                speed
            )

        except (
            TypeError,
            ValueError
        ):

            raise CalibrationError(
                f"Speed는 정수여야 합니다: "
                f"{speed}"
            )


        if speed <= 0:

            raise CalibrationError(
                f"Speed는 1 이상이어야 합니다: "
                f"{speed}"
            )


        max_speed = servo.get(
            "max_speed"
        )


        if max_speed is None:

            raise CalibrationError(
                f"{joint_name} max_speed가 "
                "아직 설정되지 않았습니다."
            )


        max_speed = int(
            max_speed
        )


        if speed > max_speed:

            raise CalibrationError(
                f"{joint_name} Speed 초과: "
                f"요청={speed}, "
                f"최대={max_speed}"
            )


        return speed


    # ========================================================
    # 8. Acc 검사
    # ========================================================
    #
    # acc는 선택 인자.
    #
    # controller.py에서 생략하면 기본값 10이 들어온다.

    @staticmethod
    def validate_acc(
        acc
    ):

        try:

            acc = int(
                acc
            )

        except (
            TypeError,
            ValueError
        ):

            raise CalibrationError(
                f"acc는 정수여야 합니다: "
                f"{acc}"
            )


        if not (
            MIN_ACC
            <= acc
            <= MAX_ACC
        ):

            raise CalibrationError(
                f"acc 허용범위: "
                f"{MIN_ACC} ~ {MAX_ACC}"
            )


        return acc


    # ========================================================
    # 9. 팀원용 각도 -> STS Position
    # ========================================================
    #
    # Zero 기준 절대각도를 raw Position으로 변환한다.
    #
    #
    # shoulder_lift +30° 예:
    #
    # 팀원:
    # +30° = 위
    #
    # command direction = -1
    #
    # +30 team
    # -> -30 URDF
    #
    # calibration direction = +1
    #
    # raw Position 감소
    # -> 실제 위
    #
    #
    # wrist_roll +30° 예:
    #
    # 팀원:
    # +30° = CCW
    #
    # command direction = +1
    #
    # +30 team
    # -> +30 URDF
    #
    # calibration direction = -1
    #
    # raw Position 감소
    # -> 실제 CCW

    def command_angle_to_position(
        self,
        joint_name,
        angle_deg
    ):

        servo = (
            self.require_position_calibrated(
                joint_name
            )
        )


        try:

            angle_deg = float(
                angle_deg
            )

        except (
            TypeError,
            ValueError
        ):

            raise CalibrationError(
                f"Angle은 숫자여야 합니다: "
                f"{angle_deg}"
            )


        zero_position = int(
            servo[
                "zero_position"
            ]
        )


        calibration_direction = int(
            servo[
                "direction"
            ]
        )


        command_direction = int(
            COMMAND_TO_URDF_DIRECTION[
                joint_name
            ]
        )


        # ----------------------------------------------------
        # 팀원용 각도 -> URDF 각도
        # ----------------------------------------------------

        urdf_angle_deg = (
            angle_deg
            * command_direction
        )


        # ----------------------------------------------------
        # URDF 각도 -> STS raw Position
        # ----------------------------------------------------

        target_position = int(
            round(
                zero_position
                + calibration_direction
                * urdf_angle_deg
                * POSITION_PER_DEGREE
            )
        )


        # 실제 안전범위 검사
        self.validate_target_position(
            joint_name,
            target_position
        )


        return target_position


    # ========================================================
    # 10. STS Position -> 팀원용 각도
    # ========================================================

    def position_to_command_angle(
        self,
        joint_name,
        position
    ):

        servo = (
            self.require_position_calibrated(
                joint_name
            )
        )


        position = int(
            position
        )


        zero_position = int(
            servo[
                "zero_position"
            ]
        )


        calibration_direction = int(
            servo[
                "direction"
            ]
        )


        command_direction = int(
            COMMAND_TO_URDF_DIRECTION[
                joint_name
            ]
        )


        # ----------------------------------------------------
        # raw Position -> URDF 각도
        # ----------------------------------------------------

        urdf_angle_deg = (
            (position - zero_position)
            * calibration_direction
            * DEGREE_PER_POSITION
        )


        # ----------------------------------------------------
        # URDF 각도 -> 팀원용 각도
        # ----------------------------------------------------

        command_angle_deg = (
            urdf_angle_deg
            * command_direction
        )


        return float(
            command_angle_deg
        )


    # ========================================================
    # 11. 실제 Safe Position 범위
    # ========================================================

    def get_safe_position_range(
        self,
        joint_name
    ):

        servo = (
            self.require_position_calibrated(
                joint_name
            )
        )


        side_a = int(
            servo[
                "safe_position_at_min_angle"
            ]
        )


        side_b = int(
            servo[
                "safe_position_at_max_angle"
            ]
        )


        # direction=-1인 Joint도 있으므로
        # raw Position 숫자 기준으로 다시 정렬한다.

        return (
            min(
                side_a,
                side_b
            ),

            max(
                side_a,
                side_b
            )
        )


    # ========================================================
    # 12. 팀원 기준 Safe Angle 범위
    # ========================================================

    def get_safe_angle_range(
        self,
        joint_name
    ):

        servo = (
            self.require_position_calibrated(
                joint_name
            )
        )


        angle_a = (
            self.position_to_command_angle(
                joint_name,
                servo[
                    "safe_position_at_min_angle"
                ]
            )
        )


        angle_b = (
            self.position_to_command_angle(
                joint_name,
                servo[
                    "safe_position_at_max_angle"
                ]
            )
        )


        return (
            min(
                angle_a,
                angle_b
            ),

            max(
                angle_a,
                angle_b
            )
        )


    # ========================================================
    # 13. Target Position 안전 검사
    # ========================================================

    def validate_target_position(
        self,
        joint_name,
        target_position
    ):

        target_position = int(
            target_position
        )


        # ----------------------------------------------------
        # STS 자체 범위
        # ----------------------------------------------------

        if not (
            STS_POSITION_MIN
            <= target_position
            <= STS_POSITION_MAX
        ):

            raise CalibrationError(
                f"{joint_name} "
                f"STS Position 범위 초과: "
                f"{target_position}"
            )


        # ----------------------------------------------------
        # 실제 Calibration Safe Range
        # ----------------------------------------------------

        numeric_min, numeric_max = (
            self.get_safe_position_range(
                joint_name
            )
        )


        if not (
            numeric_min
            <= target_position
            <= numeric_max
        ):

            angle_min, angle_max = (
                self.get_safe_angle_range(
                    joint_name
                )
            )


            raise CalibrationError(
                f"{joint_name} 안전범위 초과. "
                f"허용 각도: "
                f"{angle_min:.2f}° "
                f"~ {angle_max:.2f}°"
            )


        return True