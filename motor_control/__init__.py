"""
motor_control

팀원은 내부 구현 파일을 직접 import하지 않고 아래처럼 사용한다.

    from motor_control import MotorController
"""

from .controller import MotorController

__all__ = ["MotorController"]
