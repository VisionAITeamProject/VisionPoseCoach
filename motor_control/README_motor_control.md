# motor_control 사용 가이드

`motor_control`은 **STServo 기반 로봇팔 모터를 쉽게 제어하기 위한 Python 패키지**입니다.

팀원은 Servo ID, raw Position, Zero Position, 방향 보정값, Safe Range, STServo SDK 구조를 직접 다룰 필요가 없습니다.
기본적으로 **Joint 이름 + 목표 각도 + 속도**만 지정하면 됩니다.

---

## 1. 가장 먼저 보는 사용 예시

```python
from motor_control import MotorController

arm = MotorController()

# shoulder_lift를 Zero 기준 +30도로 이동
arm.move_joint(
    "shoulder_lift",
    angle=30,
    speed=100
)

arm.close()
```

기본적으로 아래 3개만 지정하면 됩니다.

```text
Joint 이름
Angle
Speed
```

`acc`와 `wait`는 필요할 때만 선택적으로 사용할 수 있습니다.

---

## 2. 사용 가능한 Joint 이름

| Joint 이름 | + 방향 | - 방향 |
|---|---|---|
| `shoulder_lift` | 위 | 아래 |
| `elbow_flex` | 위 | 아래 |
| `wrist_flex` | 위 | 아래 |
| `wrist_roll` | CCW | CW |

> **중요**
>
> `wrist_roll`은 **+ = CCW(반시계 방향), - = CW(시계 방향)** 입니다.

---

## 3. 패키지 불러오기

```python
from motor_control import MotorController

arm = MotorController()
```

프로그램이 끝날 때는 포트를 닫아줍니다.

```python
arm.close()
```

또는 아래처럼 `with` 문을 사용하면 자동으로 종료할 수 있습니다.

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

# 4. Zero 기준 절대각도 제어

```python
arm.move_joint(
    joint_name,
    angle,
    speed
)
```

`move_joint()`는 **현재 모터 위치와 관계없이 Zero Position을 0도로 보고 최종 목표 각도를 지정하는 함수**입니다.

예를 들어 현재 `shoulder_lift`가 +10도에 있어도:

```python
arm.move_joint(
    "shoulder_lift",
    angle=30,
    speed=100
)
```

을 실행하면 최종 위치는 **Zero 기준 +30도**가 됩니다.

### 예시

```python
# 위쪽 30도
arm.move_joint(
    "shoulder_lift",
    30,
    100
)

# 아래쪽 20도
arm.move_joint(
    "shoulder_lift",
    -20,
    100
)

# wrist_roll CCW 30도
arm.move_joint(
    "wrist_roll",
    30,
    100
)

# wrist_roll CW 30도
arm.move_joint(
    "wrist_roll",
    -30,
    100
)
```

---

# 5. 현재 위치 기준 상대각도 제어

```python
arm.move_joint_relative(
    joint_name,
    delta_angle,
    speed
)
```

`move_joint_relative()`는 **현재 실제 위치에서 지정한 각도만큼 추가로 움직이는 함수**입니다.

예를 들어 `shoulder_lift`가 현재 +20도에 있을 때:

```python
arm.move_joint_relative(
    "shoulder_lift",
    delta_angle=10,
    speed=100
)
```

을 실행하면 최종 위치는 약 +30도가 됩니다.

### 방향 예시

```python
# 현재 위치에서 위로 10도 추가 이동
arm.move_joint_relative(
    "elbow_flex",
    10,
    100
)

# 현재 위치에서 아래로 10도 추가 이동
arm.move_joint_relative(
    "elbow_flex",
    -10,
    100
)

# 현재 위치에서 CCW로 15도 추가 이동
arm.move_joint_relative(
    "wrist_roll",
    15,
    100
)

# 현재 위치에서 CW로 15도 추가 이동
arm.move_joint_relative(
    "wrist_roll",
    -15,
    100
)
```

---

# 6. 여러 Joint 동시에 제어

여러 관절을 하나의 자세로 함께 움직이려면 `move_joints()`를 사용합니다.

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

동작 순서는 다음과 같습니다.

```text
모든 Joint의 목표값 계산
        ↓
Calibration 확인
        ↓
Safe Range 확인
        ↓
Speed 확인
        ↓
모든 값이 정상인지 확인
        ↓
SyncWrite로 한 번에 명령 전송
```

하나의 Joint라도 잘못된 값이 있으면 **전체 명령을 보내지 않습니다.**

---

# 7. Acceleration 사용

`acc`는 선택 인자입니다.

지정하지 않으면 기본값은:

```text
acc = 10
```

입니다.

따라서 일반적인 사용에서는 생략하면 됩니다.

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100
)
```

필요한 경우에만 직접 지정할 수 있습니다.

```python
arm.move_joint(
    "shoulder_lift",
    angle=30,
    speed=100,
    acc=20
)
```

`acc`가 높을수록 목표 속도까지 더 빠르게 가속하며, 낮을수록 움직임이 상대적으로 부드러워집니다.

---

# 8. wait 옵션

`wait`는 모터가 목표 위치에 도착할 때까지 함수가 기다릴지 결정합니다.

기본값:

```text
wait = True
```

## wait=True

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
이동 명령 전송
    ↓
모터 이동
    ↓
목표 위치 도착 확인
    ↓
함수 종료
```

다음 동작을 **이전 동작이 끝난 뒤 실행하고 싶을 때** 사용합니다.

## wait=False

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
    ↓
함수 즉시 종료
    ↓
모터는 계속 이동
```

따라서 모터가 아직 움직이고 있어도 다음 함수를 호출할 수 있습니다.

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

같은 Joint에 새로운 목표를 다시 보내는 것도 가능합니다.

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100,
    wait=False
)

# +30도에 도착하기 전에 새로운 목표를 보낼 수 있음
arm.move_joint(
    "shoulder_lift",
    -10,
    100,
    wait=False
)
```

---

# 9. Zero 위치로 이동

## 특정 Joint만 Zero로 이동

```python
arm.move_to_zero(
    "shoulder_lift",
    speed=100
)
```

다음 코드와 같은 의미입니다.

```python
arm.move_joint(
    "shoulder_lift",
    angle=0,
    speed=100
)
```

## 전체 Joint Zero 이동

```python
arm.move_all_to_zero(
    speed=100
)
```

Calibration이 완료된 모든 Joint를 Zero 위치로 동시에 이동시킵니다.

---

# 10. 현재 각도 읽기

```python
angle = arm.get_joint_angle(
    "shoulder_lift"
)

print(angle)
```

반환되는 각도는 raw Position이 아니라 **팀원용 각도 기준**입니다.

즉:

```text
shoulder_lift + = 위
elbow_flex    + = 위
wrist_flex    + = 위
wrist_roll    + = CCW
```

기준으로 반환됩니다.

---

# 11. Joint 상태 읽기

```python
state = arm.get_joint_state(
    "shoulder_lift"
)

print(state)
```

반환 예시:

```python
{
    "joint": "shoulder_lift",
    "angle": 28.7,
    "speed": 95,
    "load": 12,
    "load_percent": 1.2,
    "voltage": 12.3,
    "temperature": 31,
    "current_raw": 10,
    "moving": False
}
```

주요 항목:

| 항목 | 의미 |
|---|---|
| `joint` | Joint 이름 |
| `angle` | 현재 팀원 기준 각도 |
| `speed` | 현재 Servo Speed 값 |
| `load` | 현재 Load 값 |
| `load_percent` | Load 비율 |
| `voltage` | Servo 전압 |
| `temperature` | Servo 온도 |
| `current_raw` | Current raw 값 |
| `moving` | 현재 이동 중인지 여부 |

`current_raw`은 현재 **raw 값 그대로 제공**합니다.
정확한 mA 변환이 필요한 경우 별도 검증 후 사용해야 합니다.

---

# 12. 전체 Joint 상태 읽기

```python
states = arm.get_all_states()

print(states)
```

모든 Joint의 상태를 한 번에 Dictionary 형태로 반환합니다.

---

# 13. 현재 이동 중인지 확인

```python
moving = arm.is_moving(
    "wrist_flex"
)

if moving:
    print("이동 중")
else:
    print("정지 상태")
```

---

# 14. 센서 / AI 조건과 함께 사용하는 예시

`motor_control`은 조건 판단을 담당하지 않습니다.

각 팀원이 만든 센서, AI, 자세 판단 등의 결과에 따라 필요한 모터 명령을 호출하면 됩니다.

```python
from motor_control import MotorController

arm = MotorController()


if bad_posture:

    arm.move_joint(
        "shoulder_lift",
        angle=25,
        speed=100
    )


if need_small_adjustment:

    arm.move_joint_relative(
        "wrist_flex",
        delta_angle=5,
        speed=80,
        wait=False
    )
```

즉 전체 구조는 다음과 같습니다.

```text
센서 / AI / 조건 판단
        ↓
팀원 로직
        ↓
motor_control 함수 호출
        ↓
Joint / Angle / Speed
        ↓
Calibration 적용
        ↓
안전 검사
        ↓
Servo 제어
```

---

# 15. 안전 기능

`motor_control` 패키지는 팀원이 raw Servo 값을 직접 제어하지 않도록 설계되어 있습니다.

내부적으로 다음을 자동 처리합니다.

```text
Joint -> Servo ID 변환
Zero Position 적용
팀원용 방향 변환
Angle -> raw Position 변환
Safe Position 범위 검사
Servo별 max_speed 검사
Acc 검사
STServo 통신
```

## Safe Range 초과

안전범위를 벗어난 각도를 입력하면 해당 명령을 **차단**합니다.

```python
arm.move_joint(
    "shoulder_lift",
    150,
    100
)
```

Safe Range 밖이라면 한계각으로 강제로 이동시키지 않고 오류를 반환합니다.

## Calibration 미완료

팀원용 패키지에서는 Calibration이 완료되지 않은 Joint를 raw 모드로 움직이지 않습니다.

Calibration 전 수동 테스트는 별도의 개발용 파일:

```text
servo_manual_control.py
```

를 사용합니다.

---

# 16. Speed 관련 주의사항

각 Servo의 최대 허용 Speed는 Calibration 정보의:

```json
"max_speed"
```

값을 사용합니다.

요청한 Speed가 `max_speed`보다 크면 모터 명령을 차단합니다.

현재 `max_speed`가 아직 설정되지 않은 Servo는 팀원용 패키지에서 제어할 수 없습니다.

---

# 17. 자주 사용할 함수 요약

| 함수 | 용도 |
|---|---|
| `move_joint()` | Zero 기준 절대각도 이동 |
| `move_joint_relative()` | 현재 기준 상대각도 이동 |
| `move_joints()` | 여러 Joint 동시 이동 |
| `move_to_zero()` | 특정 Joint Zero 복귀 |
| `move_all_to_zero()` | 전체 Joint Zero 복귀 |
| `get_joint_angle()` | 현재 각도 확인 |
| `get_joint_state()` | 특정 Joint 상태 확인 |
| `get_all_states()` | 전체 Joint 상태 확인 |
| `is_moving()` | 이동 중 여부 확인 |
| `close()` | Servo 통신 종료 |

---

# 18. 가장 많이 사용할 형태

## 일반적인 절대 위치 이동

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100
)
```

## 현재 위치에서 조금만 이동

```python
arm.move_joint_relative(
    "shoulder_lift",
    5,
    100
)
```

## 기다리지 않고 명령만 전송

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100,
    wait=False
)
```

## Acc까지 직접 지정

```python
arm.move_joint(
    "shoulder_lift",
    30,
    100,
    acc=20
)
```

## 여러 관절 동시에 이동

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

---

# 19. 팀원이 몰라도 되는 내부 값

다음 값은 `motor_control` 내부에서 자동으로 처리하므로 일반 제어 코드에서 직접 사용할 필요가 없습니다.

```text
Servo ID
raw Position
Zero Position
direction
COMMAND_TO_URDF_DIRECTION
4096 step 변환
Safe Position
Serial Port
Baudrate
STServo WritePosEx
STServo SyncWrite
```

팀원은 가능한 한 아래 형태의 상위 API만 사용해주세요.

```python
arm.move_joint(...)
arm.move_joint_relative(...)
arm.move_joints(...)
```

---

# 20. 빠른 시작 예제

```python
from motor_control import MotorController


with MotorController() as arm:

    # shoulder 위로 20도
    arm.move_joint(
        "shoulder_lift",
        20,
        100
    )

    # elbow 현재 위치에서 아래로 10도
    arm.move_joint_relative(
        "elbow_flex",
        -10,
        100
    )

    # wrist_roll 현재 위치에서 CCW로 15도
    arm.move_joint_relative(
        "wrist_roll",
        15,
        100
    )

    # 현재 shoulder 각도 확인
    angle = arm.get_joint_angle(
        "shoulder_lift"
    )

    print(
        "shoulder_lift angle:",
        angle
    )
```

---

## 최종 핵심만 기억하기

```text
1. 기본 입력은 Joint + Angle + Speed

2. move_joint()
   -> Zero 기준 절대각도

3. move_joint_relative()
   -> 현재 기준 상대각도

4. + 방향
   shoulder_lift = 위
   elbow_flex    = 위
   wrist_flex    = 위
   wrist_roll    = CCW

5. acc 생략 시 10

6. wait 생략 시 True

7. 여러 Joint는 move_joints()

8. Safe Range / max_speed 초과 명령은 자동 차단

9. raw Position과 Servo ID는 직접 다룰 필요 없음
```
