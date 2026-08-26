# motor_control E-Stop 추가 사용법

정상 사용:

```python
from motor_control import MotorController

arm = MotorController()
arm.move_joint("shoulder_lift", 30, 100)
```

모터가 끼이거나 예상치 못한 동작이 발생한 경우:

```python
arm.emergency_stop()
```

`emergency_stop()` 호출 시:

1. 패키지 Emergency latch가 즉시 ON됩니다.
2. Servo 1~4의 Torque Enable에 OFF 명령을 Sync Write로 전송합니다.
3. 이후 `move_joint()`, `move_joint_relative()`, `move_joints()`, `move_to_zero()`, `move_all_to_zero()`가 모두 차단됩니다.
4. 상태 읽기 함수는 계속 사용할 수 있습니다.

현재 버전에는 `reset_emergency_stop()`을 의도적으로 넣지 않았습니다. Torque OFF 이후 팔을 사람이 움직였을 가능성까지 고려하여, Torque ON 복구 절차는 실제 하드웨어에서 안전성을 확인한 다음 추가하는 것을 권장합니다.

> 주의: 이 기능은 소프트웨어 Torque OFF입니다. 전원을 물리적으로 차단하는 하드웨어 E-Stop과 동일하지 않습니다.
