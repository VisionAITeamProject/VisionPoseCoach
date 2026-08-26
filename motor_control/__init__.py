"""
motor_control

팀원은 내부 파일들을 직접 import하지 않고

    from motor_control import MotorController

형태로 사용한다.
"""

from .controller import MotorController


__all__ = [
    "MotorController",
]