"""
motor_control/controller.py

[역할]
다른 팀원들이 실제 제어 로직에서 사용하는 상위 Motor API.

팀원이 기본적으로 알아야 하는 값:

1. Joint 이름
2. Angle
3. Speed

선택적으로 사용할 수 있는 값:

4. Acc
5. wait

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

------------------------------------------------------------
[절대각도]

move_joint()

Zero Position을 0°로 보고
최종 목표 각도를 지정한다.

------------------------------------------------------------
[상대각도]

move_joint_relative()

현재 실제 위치를 기준으로
추가 이동할 각도를 지정한다.

------------------------------------------------------------
[여러 관절]

move_joints()

여러 Servo의 명령값을 모두 먼저 검사한 뒤
SyncWrite를 통해 가능한 한 동시에 시작한다.
"""

import time


from .config import (
    DEFAULT_ACC,
    DEFAULT_WAIT,
    DEFAULT_TIMEOUT_SEC,
    POSITION_TOLERANCE,
    POLL_INTERVAL_SEC,
)


from .calibration import (
    CalibrationManager,
    CalibrationError,
)


from .servo_driver import (
    ServoDriver,
)


# ============================================================
# 1. Motor Controller
# ============================================================

class MotorController:

    def __init__(
        self,
        calibration_file=None
    ):

        # ----------------------------------------------------
        # Calibration Manager
        # ----------------------------------------------------

        if calibration_file is None:

            self.calibration = (
                CalibrationManager()
            )


        else:

            self.calibration = (
                CalibrationManager(
                    calibration_file
                )
            )


        # ----------------------------------------------------
        # Servo Driver
        # ----------------------------------------------------
        #
        # Serial device / baudrate는
        # Calibration JSON 값을 사용한다.

        self.driver = (
            ServoDriver(

                device=
                    self.calibration.device,

                baudrate=
                    self.calibration.baudrate
            )
        )


    # ========================================================
    # 2. Error 출력
    # ========================================================

    @staticmethod
    def _print_error(
        error
    ):

        print(
            f"[MOTOR ERROR] {error}"
        )


    # ========================================================
    # 3. Zero 기준 절대각도 제어
    # ========================================================
    #
    # 예:
    #
    # arm.move_joint(
    #     "shoulder_lift",
    #     angle=30,
    #     speed=100
    # )
    #
    # 현재 위치와 관계없이
    # Zero 기준 팀원용 +30° 위치로 이동.
    #
    #
    # wrist_roll:
    #
    # angle=+30
    # -> CCW
    #
    # angle=-30
    # -> CW

    def move_joint(
        self,
        joint_name,
        angle,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC
    ):

        try:

            # ------------------------------------------------
            # Speed 검사
            # ------------------------------------------------

            speed = (
                self.calibration.validate_speed(

                    joint_name,

                    speed
                )
            )


            # ------------------------------------------------
            # Acc 검사
            # ------------------------------------------------

            acc = (
                self.calibration.validate_acc(
                    acc
                )
            )


            # ------------------------------------------------
            # 팀원용 각도 -> STS Position
            #
            # 이 과정에서 Safe Range도 검사한다.
            # ------------------------------------------------

            target_position = (
                self.calibration.command_angle_to_position(

                    joint_name,

                    angle
                )
            )


            # ------------------------------------------------
            # Servo ID
            # ------------------------------------------------

            servo = (
                self.calibration.get_joint(
                    joint_name
                )
            )


            servo_id = int(
                servo[
                    "servo_id"
                ]
            )


        except CalibrationError as error:

            self._print_error(
                error
            )

            return False


        # ----------------------------------------------------
        # 실제 Servo 이동
        # ----------------------------------------------------

        success = (
            self.driver.write_position(

                servo_id=
                    servo_id,

                position=
                    target_position,

                speed=
                    speed,

                acc=
                    acc
            )
        )


        if not success:

            self._print_error(
                f"{joint_name} 이동 명령 실패"
            )

            return False


        # ----------------------------------------------------
        # wait=False
        #
        # 명령만 전송하고 즉시 반환한다.
        #
        # 모터가 이동 중이어도
        # 다른 함수 호출 또는 같은 Servo에
        # 새로운 목표 명령을 보낼 수 있다.
        # ----------------------------------------------------

        if not wait:

            return True


        # ----------------------------------------------------
        # wait=True
        #
        # 목표 위치 도착 후 반환
        # ----------------------------------------------------

        return self._wait_for_targets(

            {
                servo_id:
                    target_position
            },

            timeout=
                timeout
        )


    # ========================================================
    # 4. 현재 위치 기준 상대각도 제어
    # ========================================================
    #
    # 현재 실제 Position을 읽은 뒤
    # 팀원용 각도로 변환하고
    # delta_angle을 더한다.
    #
    #
    # 예:
    #
    # 현재 shoulder_lift = +20°
    #
    # delta_angle = +10°
    #
    # -> 최종 +30°
    #
    #
    # wrist_roll:
    #
    # delta_angle = +10°
    #
    # -> 현재 위치에서 CCW로 10° 추가 이동.

    def move_joint_relative(
        self,
        joint_name,
        delta_angle,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC
    ):

        try:

            # ------------------------------------------------
            # Calibration 확인
            # ------------------------------------------------

            servo = (
                self.calibration.require_position_calibrated(
                    joint_name
                )
            )


            servo_id = int(
                servo[
                    "servo_id"
                ]
            )


            # ------------------------------------------------
            # 현재 Position 읽기
            # ------------------------------------------------

            current_position = (
                self.driver.read_position(
                    servo_id
                )
            )


            if current_position is None:

                self._print_error(
                    f"{joint_name} "
                    "현재 Position 읽기 실패"
                )

                return False


            # ------------------------------------------------
            # 현재 raw Position
            # -> 현재 팀원용 각도
            # ------------------------------------------------

            current_angle = (
                self.calibration.position_to_command_angle(

                    joint_name,

                    current_position
                )
            )


            # ------------------------------------------------
            # 상대각도 적용
            # ------------------------------------------------

            target_angle = (
                current_angle
                + float(
                    delta_angle
                )
            )


        except (
            CalibrationError,
            TypeError,
            ValueError
        ) as error:

            self._print_error(
                error
            )

            return False


        # ----------------------------------------------------
        # 최종 목표각을 절대각도 함수에 전달
        #
        # 따라서 Speed / Safe Range / Acc 검사는
        # move_joint에서 동일하게 적용된다.
        # ----------------------------------------------------

        return self.move_joint(

            joint_name=
                joint_name,

            angle=
                target_angle,

            speed=
                speed,

            acc=
                acc,

            wait=
                wait,

            timeout=
                timeout
        )


    # ========================================================
    # 5. 여러 Joint 동시 제어
    # ========================================================
    #
    # 예:
    #
    # arm.move_joints(
    #
    #     {
    #         "shoulder_lift": 30,
    #         "elbow_flex": 20,
    #         "wrist_flex": -10,
    #         "wrist_roll": 15,
    #     },
    #
    #     speed=100
    # )
    #
    #
    # 중요:
    #
    # 모든 Joint의
    #
    # - Calibration
    # - Speed
    # - Angle
    # - Safe Range
    #
    # 를 먼저 검사한다.
    #
    # 하나라도 문제가 있으면
    # 아무 Servo에도 명령을 보내지 않는다.
    #
    # 전부 정상일 때만 SyncWrite 실행.

    def move_joints(
        self,
        targets,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC
    ):

        if not isinstance(
            targets,
            dict
        ):

            self._print_error(
                "targets는 dict여야 합니다."
            )

            return False


        if not targets:

            self._print_error(
                "targets가 비어 있습니다."
            )

            return False


        sync_commands = {}

        wait_targets = {}


        try:

            # ------------------------------------------------
            # 공통 Acc 검사
            # ------------------------------------------------

            acc = (
                self.calibration.validate_acc(
                    acc
                )
            )


            # ------------------------------------------------
            # 모든 Joint 검증
            # ------------------------------------------------

            for (
                joint_name,
                angle
            ) in targets.items():

                # Speed
                joint_speed = (
                    self.calibration.validate_speed(

                        joint_name,

                        speed
                    )
                )


                # Angle -> Position
                #
                # Safe Range 검사 포함
                target_position = (
                    self.calibration.command_angle_to_position(

                        joint_name,

                        angle
                    )
                )


                servo = (
                    self.calibration.get_joint(
                        joint_name
                    )
                )


                servo_id = int(
                    servo[
                        "servo_id"
                    ]
                )


                # SyncWrite에 전달할 명령
                sync_commands[
                    servo_id
                ] = {

                    "position":
                        target_position,

                    "speed":
                        joint_speed,

                    "acc":
                        acc,
                }


                # wait=True일 때 확인할 목표
                wait_targets[
                    servo_id
                ] = target_position


        except CalibrationError as error:

            # ------------------------------------------------
            # 이 시점까지는 실제 모터 명령을
            # 하나도 전송하지 않았다.
            # ------------------------------------------------

            self._print_error(
                error
            )

            return False


        # ----------------------------------------------------
        # 모든 Joint 검증 완료
        #
        # 한 패킷으로 SyncWrite
        # ----------------------------------------------------

        success = (
            self.driver.sync_write_positions(
                sync_commands
            )
        )


        if not success:

            self._print_error(
                "여러 Joint 동기 이동 명령 실패"
            )

            return False


        if not wait:

            return True


        return self._wait_for_targets(

            wait_targets,

            timeout=
                timeout
        )


    # ========================================================
    # 6. 단일 Joint Zero 복귀
    # ========================================================

    def move_to_zero(
        self,
        joint_name,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC
    ):

        return self.move_joint(

            joint_name=
                joint_name,

            angle=
                0.0,

            speed=
                speed,

            acc=
                acc,

            wait=
                wait,

            timeout=
                timeout
        )


    # ========================================================
    # 7. 전체 Joint Zero 복귀
    # ========================================================
    #
    # 모든 Joint를 SyncWrite로 동시에 Zero로 이동.
    #
    # 하나라도 Calibration 또는 max_speed가 미완료이면
    # move_joints 단계에서 전체 명령을 차단한다.

    def move_all_to_zero(
        self,
        speed,
        acc=DEFAULT_ACC,
        wait=DEFAULT_WAIT,
        timeout=DEFAULT_TIMEOUT_SEC
    ):

        targets = {

            joint_name:
                0.0

            for joint_name
            in self.calibration.servos_by_joint.keys()
        }


        return self.move_joints(

            targets=
                targets,

            speed=
                speed,

            acc=
                acc,

            wait=
                wait,

            timeout=
                timeout
        )


    # ========================================================
    # 8. 현재 Joint Angle
    # ========================================================
    #
    # 반환값도 팀원용 방향 기준.
    #
    # shoulder / elbow / wrist_flex
    #
    # + = 위
    #
    #
    # wrist_roll
    #
    # + = CCW
    # - = CW

    def get_joint_angle(
        self,
        joint_name
    ):

        try:

            servo = (
                self.calibration.require_position_calibrated(
                    joint_name
                )
            )


            servo_id = int(
                servo[
                    "servo_id"
                ]
            )


            position = (
                self.driver.read_position(
                    servo_id
                )
            )


            if position is None:

                self._print_error(
                    f"{joint_name} "
                    "Position 읽기 실패"
                )

                return None


            return (
                self.calibration.position_to_command_angle(

                    joint_name,

                    position
                )
            )


        except CalibrationError as error:

            self._print_error(
                error
            )

            return None


    # ========================================================
    # 9. 단일 Joint 상태
    # ========================================================

    def get_joint_state(
        self,
        joint_name
    ):

        try:

            servo = (
                self.calibration.require_position_calibrated(
                    joint_name
                )
            )


            servo_id = int(
                servo[
                    "servo_id"
                ]
            )


            state = (
                self.driver.read_state(
                    servo_id
                )
            )


            if state is None:

                self._print_error(
                    f"{joint_name} "
                    "상태 읽기 실패"
                )

                return None


            # raw Position -> 팀원용 Angle
            angle = (
                self.calibration.position_to_command_angle(

                    joint_name,

                    state[
                        "position"
                    ]
                )
            )


            return {

                "joint":
                    joint_name,

                "angle":
                    angle,

                "speed":
                    state[
                        "speed"
                    ],

                "load":
                    state[
                        "load"
                    ],

                "load_percent":
                    state[
                        "load_percent"
                    ],

                "voltage":
                    state[
                        "voltage"
                    ],

                "temperature":
                    state[
                        "temperature"
                    ],

                "current_raw":
                    state[
                        "current_raw"
                    ],

                "moving":
                    (
                        None

                        if state[
                            "moving"
                        ] is None

                        else bool(
                            state[
                                "moving"
                            ]
                        )
                    ),
            }


        except CalibrationError as error:

            self._print_error(
                error
            )

            return None


    # ========================================================
    # 10. 전체 Joint 상태
    # ========================================================

    def get_all_states(
        self
    ):

        states = {}


        for joint_name in (
            self.calibration.servos_by_joint.keys()
        ):

            states[
                joint_name
            ] = (
                self.get_joint_state(
                    joint_name
                )
            )


        return states


    # ========================================================
    # 11. Moving 여부
    # ========================================================

    def is_moving(
        self,
        joint_name
    ):

        state = (
            self.get_joint_state(
                joint_name
            )
        )


        if state is None:

            return None


        return state[
            "moving"
        ]


    # ========================================================
    # 12. 목표 위치 도착 대기
    # ========================================================

    def _wait_for_targets(
        self,
        targets_by_servo_id,
        timeout
    ):

        start_time = (
            time.time()
        )


        while (
            time.time()
            - start_time
            < float(
                timeout
            )
        ):

            all_arrived = True


            for (
                servo_id,
                target_position
            ) in (
                targets_by_servo_id.items()
            ):

                state = (
                    self.driver.read_state(
                        servo_id
                    )
                )


                if state is None:

                    self._print_error(
                        f"Servo ID {servo_id} "
                        "상태 읽기 실패"
                    )

                    return False


                position_error = abs(

                    state[
                        "position"
                    ]

                    - target_position
                )


                moving = (
                    state[
                        "moving"
                    ]
                )


                if not (
                    moving == 0
                    and
                    position_error
                    <= POSITION_TOLERANCE
                ):

                    all_arrived = False


            if all_arrived:

                return True


            time.sleep(
                POLL_INTERVAL_SEC
            )


        self._print_error(
            f"목표 도착 Timeout: "
            f"{timeout} sec"
        )


        return False


    # ========================================================
    # 13. Port 종료
    # ========================================================

    def close(
        self
    ):

        self.driver.close()


    # ========================================================
    # 14. with 문 지원
    # ========================================================
    #
    # 사용 예:
    #
    # with MotorController() as arm:
    #
    #     arm.move_joint(...)
    #
    #
    # with 블록 종료 시 자동 close().

    def __enter__(
        self
    ):

        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback
    ):

        self.close()