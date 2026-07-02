# VisionPoseCoach 앱 API 명세

이 문서는 스마트폰 앱이 라즈베리파이 서버와 통신할 때 사용하는 HTTP API와 WebSocket 스펙을 정리한 문서입니다.

## 1. 앱에서 사용하는 HTTP API

### 1) GET /health
- 앱이 서버/장치 준비 상태를 확인할 때 사용합니다.
- 앱은 기본적으로 app 섹션만 읽으면 됩니다.
- debug 섹션은 개발자 확인용입니다.

예시:
```json
{
  "type": "health",
  "ok": true,
  "app": {
    "server_ready": true,
    "device_ready": true,
    "camera_ready": true,
    "vision_ready": true,
    "calibration_ready": true,
    "inference_ready": true,
    "session_running": false,
    "state": "IDLE",
    "message": "기기 준비됨"
  },
  "debug": {
    "camera": {},
    "vision": {},
    "calibration": {},
    "inference": {},
    "logger": {},
    "measurement_loop": {}
  }
}
```

### 2) GET /session/status
- 앱 실행 시, 측정 탭 진입 시, 네트워크 재연결 시 현재 세션 복구를 위해 사용합니다.
- 이 응답 하나로 앱은 화면 전환 여부를 판단할 수 있습니다.

### 3) GET /mjpg
- 실시간 카메라 스트림을 표시할 때 사용합니다.

### 4) GET /session/latest-report
- 최신 세션 리포트를 조회합니다.

### 5) GET /session/report/{session_id}
- 특정 세션의 리포트를 조회합니다.

## 2. WebSocket 연결 주소
- 주소: ws://<device-ip>:8000/ws

## 3. 앱 → 서버 명령 JSON

### 측정 시작
```json
{
  "type": "command",
  "action": "start_session",
  "duration_sec": 1800
}
```

### 측정 종료
```json
{
  "type": "command",
  "action": "stop_session"
}
```

하위 호환으로 아래 형식도 계속 지원합니다.
```json
{
  "command": "start_session",
  "duration_sec": 1800
}
```

```json
{
  "command": "stop_session"
}
```

## 4. 서버 → 앱 메시지 JSON

### A. session_snapshot
- WebSocket 연결 직후 1회 전송됩니다.
- 앱 재접속 시 현재 상태 복구를 위해 사용합니다.

```json
{
  "type": "session_snapshot",
  "session_id": "2026-06-25_102030",
  "is_running": true,
  "state": "MEASURING",
  "message": "측정 중입니다.",
  "screen_hint": "MEASUREMENT",
  "stage_remain_sec": null,
  "elapsed_sec": 120,
  "duration_sec": 1800,
  "remain_sec": 1680,
  "stop_reason": null,
  "latest_result": {
    "posture_label": "Forward Head",
    "posture_confidence": 0.82,
    "fatigue_label": "Normal",
    "fatigue_probability": 0.21,
    "pose_detected": true,
    "face_detected": true,
    "error": null
  }
}
```

### B. status
- 준비 단계, 카운트다운, 종료 상태에서 사용합니다.

```json
{
  "type": "status",
  "session_id": "2026-06-25_102030",
  "state": "WAITING_5S",
  "message": "정자세를 유지해주세요.",
  "screen_hint": "PREPARE",
  "stage_remain_sec": 5,
  "elapsed_sec": 0,
  "duration_sec": 1800,
  "remain_sec": 1800,
  "stop_reason": null
}
```

### C. measurement
- MEASURING 상태에서 1초에 1번 전송됩니다.

```json
{
  "type": "measurement",
  "session_id": "2026-06-25_102030",
  "state": "MEASURING",
  "screen_hint": "MEASUREMENT",
  "elapsed_sec": 120,
  "duration_sec": 1800,
  "remain_sec": 1680,
  "posture_label": "Forward Head",
  "posture_confidence": 0.82,
  "fatigue_label": "Normal",
  "fatigue_probability": 0.21,
  "pose_detected": true,
  "face_detected": true,
  "error": null
}
```

### D. error
- 명령 오류나 서버 오류를 앱에 전달합니다.

```json
{
  "type": "error",
  "code": "INVALID_DURATION",
  "message": "측정 시간이 올바르지 않습니다.",
  "state": "IDLE",
  "screen_hint": "HOME"
}
```

## 5. screen_hint 기준 화면 전환 정책

- HOME: 측정 시작 전 홈/대시보드 화면
- PREPARE: 정자세 안내, 캘리브레이션, 초기 측정, 카운트다운 등 준비 화면
- MEASUREMENT: 본 측정 화면
- RESULT: 측정 결과 화면
- ERROR: 오류 화면

상태와 매핑:
- IDLE → HOME
- PREPARE_POSTURE → PREPARE
- WAITING_5S → PREPARE
- CALIBRATING → PREPARE
- INITIAL_MEASURING_30S → PREPARE
- COUNTDOWN_3S → PREPARE
- MEASURING → MEASUREMENT
- STOPPED → RESULT
- ERROR → ERROR

## 6. 측정 탭 진입 흐름
1. 저장된 기기 IP 또는 기기 정보 확인
2. GET /health 호출
3. GET /session/status 호출
4. screen_hint 확인
5. MEASUREMENT이면 측정 화면으로 이동
6. PREPARE이면 준비 화면으로 이동
7. RESULT이면 결과 화면으로 이동
8. HOME이면 홈 화면 유지
9. 측정 화면 진입 후 /mjpg와 /ws 연결

## 7. 측정 시작 흐름
1. 앱이 start_session 명령 전송
2. 서버가 준비 상태로 전환
3. status 메시지로 준비 진행 상황 전달
4. MEASURING 진입 시 measurement 메시지 시작

## 8. 앱 재실행/재접속 복구 흐름
1. 앱 재실행
2. GET /session/status 호출
3. is_running=true, state=MEASURING 확인
4. 측정 화면으로 자동 복귀
5. /mjpg 재연결
6. /ws 재연결
7. session_snapshot 수신 후 현재 상태 표시
8. 이후 measurement 메시지로 화면 갱신

## 9. 측정 종료 흐름
1. stop_session 명령 전송 또는 duration_sec 종료
2. STOPPED 상태 전환
3. RESULT 화면으로 전환
4. /session/latest-report로 결과 확인 가능

## 10. 리포트 조회 흐름
- GET /session/latest-report
- GET /session/report/{session_id}

## 11. 개발자 테스트용 API와 앱용 API 구분
- 앱 메인 플로우에서 사용하는 API: /health, /session/status, /mjpg, /ws, /session/latest-report, /session/report/{session_id}
- 개발자 테스트용 API: /vision/once, /calibration/test, /inference/once
- 개발자 테스트용 API는 앱의 메인 흐름에서는 사용하지 않습니다.

## 12. 앱용 응답에서 제외하는 필드
- pose_features
- face_features
- landmarks
- blendshapes
- raw frame
- condition
- 내부 model raw output
- 큰 debug dict

이 값들은 서버 내부/개발자 디버깅용이며 앱 응답에는 포함하지 않습니다.
