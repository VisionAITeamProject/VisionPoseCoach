# Motor Control Package 사용 가이드

이 문서는 `motor_control` 패키지를 사용하는 팀원을 위한 안내서입니다.

다른 팀원은 **Servo ID, raw Position, Zero Position, direction, STServo SDK 내부 구조를 알 필요 없이**
`Joint 이름 + 각도 + Speed`를 지정해서 로봇팔을 제어하면 됩니다.

---

## 1. 기본 Import

```python
from motor_control import MotorController

arm = MotorController()
```

사용이 끝나면:

```python
arm.close()
```

또는 `with` 문을 사용할 수 있습니다.

```python
from motor_control import MotorController

with MotorController() as arm:
    arm.move_joint(
        "shoulder_lift",
        angle=30,
        speed=100
    )
```

---

# 2. Joint 이름과 방향 기준

현재 프로젝트에서 사용하는 Joint는 다음 4개입니다.

| Joint 이름 | + 방향 | - 방향 |
|---|---|---|
| `shoulder_lift` | 위 | 아래 |
| `elbow_flex` | 위 | 아래 |
| `wrist_flex` | 위 | 아래 |
| `wrist_roll` | **CW (시계)** | **CCW (반시계)** |

> **중요:** `wrist_roll`은 최종 실물 확인 결과  
> `+ = CW`, `- = CCW` 기준입니다.
> 관찰 기준은 **모니터가 위치한 정면에서 로봇팔을 바라보는 기준**입니다.
> 실측 관계는 `RAW + = CW`, `URDF + = CCW`, `TEAM + = CW`입니다.

---

# 3. Zero 기준 절대각도 이동

## `move_joint()`

현재 위치와 상관없이 **Calibration Zero를 0°로 보고 목표 각도까지 이동**합니다.

```python
arm.move_joint(
    "shoulder_lift",
    angle=30,
    speed=100
)
```

의미:

```text
shoulder_lift
Zero 기준 +30°
→ 위 방향 30°
```

반대로:

```python
arm.move_joint(
    "shoulder_lift",
    angle=-20,
    speed=100
)
```

의미:

```text
Zero 기준 -20°
→ 아래 방향 20°
```

`wrist_roll` 예:

```python
arm.move_joint(
    "wrist_roll",
    angle=30,
    speed=100
)
```

→ Zero 기준 **CW 30°**

```python
arm.move_joint(
    "wrist_roll",
    angle=-30,
    speed=100
)
```

→ Zero 기준 **CCW 30°**

---

# 4. 현재 위치 기준 상대각도 이동

## `move_joint_relative()`

현재 Servo 위치를 기준으로 추가 이동량을 지정합니다.

```python
arm.move_joint_relative(
    "shoulder_lift",
    delta_angle=10,
    speed=100
)
```

예를 들어 현재 위치가 `+20°`라면:

```text
현재 +20°
+10° 상대이동
→ 최종 +30°
```

`wrist_roll` 예:

```python
arm.move_joint_relative(
    "wrist_roll",
    delta_angle=15,
    speed=100
)
```

→ 현재 위치에서 **CW 방향으로 15° 추가 이동**

```python
arm.move_joint_relative(
    "wrist_roll",
    delta_angle=-15,
    speed=100
)
```

→ 현재 위치에서 **CCW 방향으로 15° 추가 이동**

---

# 5. 여러 Joint 동시 이동

## `move_joints()`

여러 Servo를 가능한 한 동시에 시작시킵니다.

```python
arm.move_joints(
    {
        "shoulder_lift": 30,
        "elbow_flex": 20,
        "wrist_flex": -10,
        "wrist_roll": 15,
    },
    speed=100
)
```

동작 과정:

```text
모든 Joint Calibration 확인
        ↓
모든 Angle 안전범위 확인
        ↓
모든 Speed 확인
        ↓
전부 정상일 때만
        ↓
Sync Write로 동시 명령 전송
```

하나라도 잘못된 값이 있으면 **일부 모터만 움직이지 않고 전체 명령을 차단**합니다.

---

# 6. Speed

Speed는 필수 입력값입니다.

```python
arm.move_joint(
    "elbow_flex",
    angle=20,
    speed=100
)
```

각 Servo마다 Calibration JSON에 저장된 `max_speed` 이하의 값만 사용할 수 있습니다.

예:

```text
max_speed = 300
요청 speed = 200
→ 허용

max_speed = 300
요청 speed = 500
→ BLOCK
```

현재 `max_speed`가 아직 `null`인 Servo는 안전상 팀원용 패키지에서 이동이 차단됩니다.

---

# 7. Acceleration (`acc`)

`acc`는 **선택 인자**입니다.

생략하면 기본값:

```text
acc = 10
```

이 자동 적용됩니다.

일반적인 사용:

```python
arm.move_joint(
    "shoulder_lift",
    angle=30,
    speed=100
)
```

필요한 경우만 직접 지정합니다.

```python
arm.move_joint(
    "shoulder_lift",
    angle=30,
    speed=100,
    acc=20
)
```

개념적으로:

```text
Speed
→ 얼마나 빠르게 이동할지

Acc
→ 그 Speed까지 얼마나 빠르게 가속/감속할지
```

---

# 8. `wait=True / False`

기본값:

```python
wait=True
```

## `wait=True`

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100,
    wait=True
)
```

동작:

```text
이동 명령
→ 모터 이동
→ 목표 위치 도착 확인
→ 함수 종료
```

순차 동작을 만들 때 편합니다.

## `wait=False`

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100,
    wait=False
)
```

동작:

```text
이동 명령 전송
→ 즉시 함수 종료
→ Servo는 계속 이동 중
```

따라서 모터가 아직 목표 위치에 도착하지 않아도 다음 함수를 바로 호출할 수 있습니다.

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100,
    wait=False
)

arm.move_joint(
    "elbow_flex",
    20,
    100,
    wait=False
)
```

같은 Servo에 새로운 목표를 다시 보내는 것도 가능합니다.

---

# 9. Zero 위치로 이동

## 단일 Joint

```python
arm.move_to_zero(
    "shoulder_lift",
    speed=100
)
```

이는 아래와 같은 의미입니다.

```python
arm.move_joint(
    "shoulder_lift",
    angle=0,
    speed=100
)
```

## 전체 Joint

```python
arm.move_all_to_zero(
    speed=100
)
```

Calibration이 완료된 전체 Joint를 Zero 위치로 동시 이동시킵니다.

---

# 10. 현재 Joint 각도 읽기

```python
angle = arm.get_joint_angle(
    "shoulder_lift"
)

print(angle)
```

반환되는 값은 raw Position이 아니라 **팀원용 방향 기준 각도(deg)** 입니다.

`wrist_roll`도 동일하게:

```text
+값 = CW
-값 = CCW
```

기준으로 반환됩니다.

---

# 11. Servo 상태 읽기

## 단일 Joint

```python
state = arm.get_joint_state(
    "shoulder_lift"
)

print(state)
```

반환 예:

```python
{
    "joint": "shoulder_lift",
    "angle": 29.8,
    "speed": 95,
    "load": 24,
    "load_percent": 2.4,
    "voltage": 12.3,
    "temperature": 31,
    "current_raw": 15,
    "moving": False
}
```

현재 읽을 수 있는 주요 정보:

- 현재 Angle
- 현재 Speed
- Load
- Load 비율
- Voltage
- Temperature
- Current raw 값
- Moving 여부

> `current_raw`는 현재 raw 값 그대로 제공합니다.  
> 정확한 mA 환산은 최종 데이터시트 기준을 별도로 확정한 뒤 적용할 예정입니다.

## 전체 Joint 상태

```python
states = arm.get_all_states()
```

## 이동 중인지 확인

```python
moving = arm.is_moving(
    "shoulder_lift"
)
```

---

# 12. Safe Range 보호

각 Joint는 Calibration 과정에서 저장된 Safe Range 밖으로 이동할 수 없습니다.

예:

```python
arm.move_joint(
    "shoulder_lift",
    angle=150,
    speed=100
)
```

요청 각도가 실제 Safe Range를 초과하면 Servo에 이동 명령을 보내지 않습니다.

```text
잘못된 요청
→ 자동 Clamp ❌
→ 그대로 실행 ❌
→ 명령 BLOCK ✅
```

---

# 13. Calibration 미완료 Servo

팀원용 `motor_control` 패키지는 **Calibration 완료 Servo만 제어**합니다.

필요 정보:

```text
zero_position
safe_position_at_min_angle
safe_position_at_max_angle
max_speed
```

값이 없는 Servo는 이동 명령이 차단됩니다.

Calibration 전 테스트는 별도의:

```text
servo_manual_control.py
```

를 사용합니다.

---

# 14. Emergency Stop

## 비상정지 명령

모터가 물체에 끼이거나, 로봇팔이 예상하지 못한 방향으로 움직이거나,
Servo가 목표 위치로 가려고 계속 힘을 주는 위험 상황에서는:

```python
arm.emergency_stop()
```

을 호출합니다.

동작 과정:

```text
Emergency 상태 ON
        ↓
새로운 이동 명령 차단
        ↓
모든 Servo Torque OFF 동기 전송
        ↓
Servo가 목표 위치로 계속 힘을 주는 동작 중단
```

이 기능은 **현재 위치 Hold가 아닙니다.**

Servo의 Torque 자체를 해제합니다.

---

# 15. Emergency Stop 이후

E-Stop이 걸린 뒤에는 다음 이동 함수가 모두 차단됩니다.

```text
move_joint()
move_joint_relative()
move_joints()
move_to_zero()
move_all_to_zero()
```

예:

```python
arm.emergency_stop()

# 실행되지 않음
arm.move_joint(
    "shoulder_lift",
    0,
    100
)
```

Emergency 상태 확인:

```python
if arm.is_emergency_stopped():
    print("비상정지 상태")
```

---

# 16. E-Stop 후 상태 읽기는 가능

Emergency Stop이 발생해도 상태 확인 함수는 사용할 수 있습니다.

```python
state = arm.get_joint_state(
    "shoulder_lift"
)

states = arm.get_all_states()
```

비상정지 이후 현재 위치, Load, Temperature 등을 확인할 수 있도록 의도적으로 허용되어 있습니다.

---

# 17. 현재는 자동 복구 기능 없음

현재 패키지에는:

```python
arm.reset_emergency_stop()
```

기능을 제공하지 않습니다.

Torque OFF 이후 사람이 로봇팔을 직접 움직였을 수 있으므로,
안전 복구 절차를 실제 하드웨어에서 검증한 뒤 추가할 예정입니다.

---

# 18. Emergency Stop 주의사항

`emergency_stop()`은 **소프트웨어 Torque OFF 기능**입니다.

```text
Servo가 힘을 주는 것 차단 ✅
모터 전원 자체를 물리적으로 차단 ❌
```

전원을 완전히 끊는 물리적 E-Stop이 필요하다면 별도의 비상스위치, 릴레이, MOSFET 등의 하드웨어 전원 차단 구조가 필요합니다.

또한 Torque OFF가 되면 로봇팔이 더 이상 자세를 유지하지 않으므로 **중력으로 관절이 떨어질 수 있습니다.**

---

# 19. `close()`는 Emergency Stop이 아님

```python
arm.close()
```

는 Serial Port를 닫는 함수입니다.

```text
close()
→ 통신 종료

emergency_stop()
→ Servo Torque OFF + 이동 명령 차단
```

위험 상황에서는 `close()`가 아니라:

```python
arm.emergency_stop()
```

을 사용합니다.

---

# 20. 주요 함수 요약

| 함수 | 용도 |
|---|---|
| `move_joint()` | Zero 기준 절대각도 이동 |
| `move_joint_relative()` | 현재 위치 기준 상대이동 |
| `move_joints()` | 여러 Joint 동시 이동 |
| `move_to_zero()` | 한 Joint Zero 복귀 |
| `move_all_to_zero()` | 전체 Joint Zero 복귀 |
| `get_joint_angle()` | 현재 각도 읽기 |
| `get_joint_state()` | 한 Joint 상태 읽기 |
| `get_all_states()` | 전체 상태 읽기 |
| `is_moving()` | 이동 여부 확인 |
| `emergency_stop()` | **전체 Servo Torque OFF 비상정지** |
| `is_emergency_stopped()` | E-Stop 상태 확인 |
| `close()` | Serial Port 종료 |

---

# 21. 기본 사용 예제

```python
from motor_control import MotorController


arm = MotorController()


try:

    # shoulder 위쪽 30°
    arm.move_joint(
        "shoulder_lift",
        30,
        100
    )


    # 현재 위치에서 elbow 위쪽 10° 추가
    arm.move_joint_relative(
        "elbow_flex",
        10,
        100
    )


    # 여러 Joint 동시 이동
    arm.move_joints(
        {
            "shoulder_lift": 20,
            "elbow_flex": 15,
            "wrist_flex": -10,
            "wrist_roll": 20,   # + = CW
        },
        speed=100
    )


    # 현재 상태 확인
    print(
        arm.get_all_states()
    )


except KeyboardInterrupt:

    # 개발 중 Ctrl+C 발생 시 Torque OFF
    arm.emergency_stop()


finally:

    arm.close()
```

---

# 22. 팀원이 알 필요 없는 내부 처리

다음 내용은 `motor_control` 패키지가 내부에서 자동 처리합니다.

```text
Servo ID
STS raw Position
4096 Position / 360°
Zero Position
Calibration direction
팀원용 command direction
URDF 방향
Safe Position
Serial Port
Baudrate
STServo SDK
Sync Write
Torque Enable Register
```

일반적인 팀원 코드는 아래 세 값을 중심으로 작성하면 됩니다.

```text
Joint
Angle
Speed
```

필요한 경우에만:

```text
Acc
wait
```

를 추가하면 됩니다.
