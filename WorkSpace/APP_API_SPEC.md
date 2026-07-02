# VisionPoseCoach 앱 API 명세

이 문서는 스마트폰 앱이 라즈베리파이 서버와 통신할 때 사용하는 HTTP API와 WebSocket JSON 계약을 정리합니다.

중요 원칙:
- 측정 세션의 주인은 스마트폰 앱이 아니라 라즈베리파이 서버입니다.
- 앱이 종료되거나 네트워크가 끊겨도 서버는 `duration_sec`가 끝날 때까지 측정을 유지합니다.
- 앱은 재실행/재접속 시 `GET /session/status`를 호출하고 `screen_hint`에 따라 화면을 복구합니다.
- BLE는 초기 기기 설정용 통로이며, 측정 중 실시간 데이터는 WiFi 기반 HTTP/WebSocket/MJPG를 사용합니다.
- 라즈베리파이 전원 ON 후 FastAPI 서버가 자동 실행되는 것을 전제로 앱은 먼저 `GET /health`를 호출합니다.
- 앱용 응답에는 raw feature, landmark, 이미지, 모델 raw output 같은 큰 데이터나 디버그 데이터를 넣지 않습니다.

## 1. HTTP API

### GET /health

서버와 장치 준비 상태를 확인합니다. 앱은 기본적으로 `app` 섹션만 읽으면 됩니다. `debug` 섹션은 개발자 확인용입니다.

```json
{
  "type": "health",
  "ok": true,
  "app": {
    "server_ready": true,
    "device_ready": true,
    "network_ready": true,
    "wifi_connected": false,
    "provisioning_required": true,
    "provisioning_state": "COMPLETED",
    "ble_available": false,
    "ble_advertising": false,
    "camera_ready": true,
    "vision_ready": true,
    "calibration_ready": true,
    "inference_ready": true,
    "session_running": false,
    "state": "IDLE",
    "screen_hint": "HOME",
    "message": "기기 준비됨"
  },
  "debug": {
    "network": {},
    "provisioning": {},
    "camera": {},
    "vision": {},
    "calibration": {},
    "inference": {},
    "logger": {},
    "measurement_loop": {}
  }
}
```

`network_ready`는 앱 통신에 필요한 네트워크 상태가 준비되었는지 나타냅니다. 현재 dry-run 개발 모드에서는 실제 WiFi 연결을 변경하지 않으므로 개발 편의를 위해 `true`가 될 수 있습니다. `wifi_connected`는 WiFi 연결 여부이고, `provisioning_required`는 앱에서 WiFi 설정 화면을 보여줘야 하는지 판단할 때 사용합니다.
`provisioning_state`는 앱의 기기 등록 진행 상태입니다. `ble_available`은 실제 BLE 사용 가능 여부이고, dry-run 모드에서는 `false`입니다. `ble_advertising`은 BLE advertising 상태이며 현재 단계에서는 실제 광고 없이 상태값만 바뀝니다. `pairing_code`는 앱용 `app` 섹션에 넣지 않고 provisioning 전용 응답 또는 개발 확인용 `debug.provisioning`에서만 확인합니다.

### GET /session/status

앱 실행 시, 측정 탭 진입 시, 네트워크 재연결 시 현재 세션 상태를 복구하기 위해 사용합니다. WebSocket 연결 직후 받는 `session_snapshot`과 `type`만 다르고 거의 같은 구조입니다.

```json
{
  "type": "session_status",
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

### GET /mjpg

측정 화면에서 카메라 프리뷰를 표시할 때 사용합니다.

### GET /network/status

현재 네트워크/WiFi 상태를 조회합니다.

```json
{
  "type": "network_status",
  "wifi": {
    "mode": "dry_run",
    "connected": false,
    "ssid": null,
    "local_ip": "192.168.0.10",
    "hostname": "raspberrypi",
    "provisioning_required": true,
    "last_configured_ssid": null,
    "last_error": null
  }
}
```

### GET /network/wifi/scan

WiFi 목록을 조회합니다. 현재 단계에서는 실제 WiFi 스캔을 수행하지 않고 빈 목록을 반환합니다. 실제 스캔은 라즈베리파이 배포 단계에서 구현 예정입니다.

```json
{
  "type": "wifi_scan",
  "mode": "dry_run",
  "networks": [],
  "message": "현재 단계에서는 실제 WiFi 스캔을 수행하지 않습니다."
}
```

### POST /network/wifi/configure

WiFi 설정 요청을 저장합니다. 현재 단계에서는 실제 시스템 WiFi 설정을 변경하지 않고 dry-run 상태로만 보관합니다. 응답에는 비밀번호를 절대 포함하지 않습니다.

요청:

```json
{
  "ssid": "MyWifi",
  "password": "mypassword123"
}
```

응답:

```json
{
  "type": "wifi_configure_result",
  "ok": true,
  "mode": "dry_run",
  "ssid": "MyWifi",
  "message": "WiFi 설정 요청을 저장했습니다. 실제 연결 변경은 배포 단계에서 구현됩니다."
}
```

### POST /network/wifi/forget

저장된 WiFi 설정 요청 상태를 초기화합니다.

```json
{
  "type": "wifi_forget_result",
  "ok": true,
  "message": "저장된 WiFi 설정 정보를 초기화했습니다."
}
```

### GET /provisioning/ble/status

BLE Provisioning 상태를 조회합니다. 현재 단계에서는 실제 Bluetooth 하드웨어 제어 없이 dry-run 상태만 반환합니다.

```json
{
  "type": "ble_status",
  "ble": {
    "mode": "dry_run",
    "available": false,
    "advertising": false,
    "device_name": "VisionPoseCoach-Pi",
    "pairing_code": "123456",
    "last_client_id": null,
    "last_message_type": null,
    "provisioning_completed": false,
    "last_error": null
  }
}
```

### POST /provisioning/ble/start

dry-run advertising 상태를 시작합니다. 실제 BLE advertising은 수행하지 않습니다.

```json
{
  "type": "ble_advertising_result",
  "ok": true,
  "ble": {
    "advertising": true
  },
  "message": "BLE advertising을 dry-run 상태로 시작했습니다."
}
```

### POST /provisioning/ble/stop

dry-run advertising 상태를 중지합니다.

### POST /provisioning/ble/message

실제 BLE characteristic write로 들어올 provisioning 메시지를 HTTP로 mock 처리합니다. 개발/테스트용 API이며, 제품 흐름에서는 추후 BLE characteristic write로 대체됩니다.

### POST /provisioning/ble/reset

BLE Provisioning 상태를 초기화합니다.

### GET /provisioning/status

앱이 기기 등록 진행 상황을 한 번에 확인할 때 사용합니다.

```json
{
  "type": "provisioning_status",
  "mode": "dry_run",
  "device_name": "VisionPoseCoach-Pi",
  "provisioning_state": "COMPLETED",
  "provisioning_completed": true,
  "ble": {
    "available": false,
    "advertising": false,
    "last_client_id": "phone-001",
    "last_message_type": "configure_wifi"
  },
  "wifi": {
    "connected": false,
    "ssid": null,
    "local_ip": "192.168.0.10",
    "hostname": "raspberrypi",
    "provisioning_required": true,
    "last_configured_ssid": "MyWifi",
    "last_error": null
  },
  "next_step": "CHECK_NETWORK_STATUS",
  "message": "WiFi 설정 요청이 처리되었습니다. /network/status 또는 /health로 연결 상태를 확인하세요."
}
```

dry-run에서 `COMPLETED`는 실제 WiFi 연결 성공을 의미하지 않습니다. 앱에서 보낸 WiFi 설정 요청이 서버의 `WiFiManager`까지 정상 전달되었음을 뜻합니다. 실제 연결 상태는 `/network/status` 또는 `/health`로 확인합니다.

### GET /session/latest-report

측정 종료 후 결과 화면에서 최신 세션 리포트를 조회할 때 사용합니다.

### GET /session/report/{session_id}

특정 세션의 리포트를 조회합니다.

### 개발자 테스트용 HTTP API

`/vision/once`, `/calibration/test`, `/inference/once`는 개발자 테스트용입니다. 앱 메인 플로우에서는 사용하지 않습니다.

## 2. screen_hint 매핑

앱은 `state`를 직접 해석하기보다 `screen_hint`를 우선 사용해 화면을 결정합니다.

| state | screen_hint | 앱 화면 |
| --- | --- | --- |
| `IDLE` | `HOME` | 홈/대시보드 |
| `PREPARE_POSTURE` | `PREPARE` | 준비 화면 |
| `WAITING_5S` | `PREPARE` | 준비 화면 |
| `CALIBRATING` | `PREPARE` | 준비 화면 |
| `INITIAL_MEASURING_30S` | `PREPARE` | 준비 화면 |
| `COUNTDOWN_3S` | `PREPARE` | 준비 화면 |
| `MEASURING` | `MEASUREMENT` | 측정 화면 |
| `STOPPED` | `RESULT` | 결과 화면 |
| `ERROR` | `ERROR` | 오류 화면 |

## 3. WebSocket

연결 주소:

```text
ws://<device-ip>:8000/ws
```

### 앱 → 서버 command

측정 시작:

```json
{
  "type": "command",
  "action": "start_session",
  "duration_sec": 1800
}
```

측정 종료:

```json
{
  "type": "command",
  "action": "stop_session"
}
```

하위 호환 형식:

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

## 4. 서버 → 앱 메시지

### session_snapshot

WebSocket 연결 직후 1회 전송됩니다. 앱 재접속 시 현재 상태를 복구하기 위해 사용합니다.

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

### status

준비 단계, 카운트다운, 종료 상태에서 사용합니다. `stage_remain_sec`는 현재 준비 단계 남은 시간이고, `remain_sec`는 본 측정 총 남은 시간입니다.

```json
{
  "type": "status",
  "session_id": "2026-06-25_102030",
  "is_running": true,
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

### measurement

`MEASURING` 상태에서 1초마다 전송됩니다. 표시용 결과는 `latest_result`로 감싸지 않고 평평한 필드로 보냅니다.

```json
{
  "type": "measurement",
  "session_id": "2026-06-25_102030",
  "is_running": true,
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

### error

명령 오류나 서버 내부 오류를 앱에 전달합니다.

```json
{
  "type": "error",
  "code": "INVALID_DURATION",
  "message": "측정 시간이 올바르지 않습니다.",
  "state": "IDLE",
  "screen_hint": "HOME"
}
```

대표 코드:
- `INVALID_DURATION`: `duration_sec`가 없거나 허용 범위를 벗어남
- `UNKNOWN_COMMAND`: 알 수 없는 command/action
- `SESSION_ALREADY_RUNNING`: 이미 측정 중인데 다시 시작 요청
- `NO_ACTIVE_SESSION`: 진행 중인 측정이 없는데 종료 요청
- `INTERNAL_ERROR`: 서버 내부 오류

## 5. BLE Provisioning 메시지 스펙

BLE Provisioning은 초기 설정에서 앱이 라즈베리파이를 발견하고 WiFi 정보를 전달하기 위한 통로입니다. 측정 화면에서는 BLE를 사용하지 않고 `/session/status`, `/mjpg`, `/ws`를 사용합니다.

Provisioning 상태값:

| provisioning_state | 의미 |
| --- | --- |
| `NOT_STARTED` | 기기 등록 흐름이 시작되지 않음 |
| `ADVERTISING` | 앱의 BLE 발견을 기다리는 중 |
| `CLIENT_CONNECTED` | 앱이 hello 메시지로 기기와 연결됨 |
| `WIFI_CONFIG_RECEIVED` | WiFi 설정 요청을 받음 |
| `WIFI_CONFIGURED` | WiFi 설정 요청 처리 완료 상태로 확장 가능 |
| `COMPLETED` | dry-run에서 WiFi 설정 요청 처리 완료 |
| `ERROR` | provisioning 처리 오류 |

`next_step` 값:

| next_step | 앱 동작 |
| --- | --- |
| `START_BLE_ADVERTISING` | 서버의 BLE advertising 시작을 유도 |
| `WAIT_FOR_APP` | 앱이 기기를 선택하고 hello를 보낼 때까지 대기 |
| `SEND_WIFI_CONFIG` | 앱에서 WiFi SSID/PW 입력 화면 표시 |
| `CHECK_NETWORK_STATUS` | `/network/status` 또는 `/health`로 연결 상태 확인 |
| `READY_TO_REGISTER` | 기기 등록 완료 처리 가능 |
| `ERROR` | WiFi 정보 재입력 또는 등록 재시도 |

### hello

앱 → 라즈베리파이:

```json
{
  "type": "hello",
  "client_id": "phone-001",
  "app_version": "0.1.0"
}
```

응답:

```json
{
  "type": "ble_provisioning_response",
  "ok": true,
  "message_type": "hello",
  "device_name": "VisionPoseCoach-Pi",
  "pairing_code": "123456",
  "provisioning_state": "CLIENT_CONNECTED",
  "provisioning_completed": false,
  "next_step": "SEND_WIFI_CONFIG",
  "message": "기기와 연결되었습니다. WiFi 정보를 전송해주세요."
}
```

### configure_wifi

앱 → 라즈베리파이:

```json
{
  "type": "configure_wifi",
  "client_id": "phone-001",
  "ssid": "MyWifi",
  "password": "mypassword123"
}
```

응답:

```json
{
  "type": "ble_provisioning_response",
  "ok": true,
  "message_type": "configure_wifi",
  "provisioning_state": "COMPLETED",
  "provisioning_completed": true,
  "next_step": "CHECK_NETWORK_STATUS",
  "message": "WiFi 설정 요청을 처리했습니다.",
  "wifi": {
    "mode": "dry_run",
    "connected": false,
    "ssid": null,
    "local_ip": "192.168.0.10",
    "hostname": "raspberrypi",
    "provisioning_required": true,
    "last_configured_ssid": "MyWifi",
    "last_error": null
  }
}
```

응답에는 `password`를 절대 포함하지 않습니다.

### status

앱 → 라즈베리파이:

```json
{
  "type": "status",
  "client_id": "phone-001"
}
```

응답:

```json
{
  "type": "ble_provisioning_response",
  "ok": true,
  "message_type": "status",
  "provisioning_state": "COMPLETED",
  "provisioning_completed": true,
  "next_step": "CHECK_NETWORK_STATUS",
  "ble": {},
  "wifi": {}
}
```

### reset

앱 → 라즈베리파이:

```json
{
  "type": "reset",
  "client_id": "phone-001"
}
```

응답:

```json
{
  "type": "ble_provisioning_response",
  "ok": true,
  "message_type": "reset",
  "provisioning_state": "NOT_STARTED",
  "provisioning_completed": false,
  "next_step": "START_BLE_ADVERTISING",
  "message": "Provisioning 상태를 초기화했습니다."
}
```

### unknown

알 수 없는 메시지:

```json
{
  "type": "ble_provisioning_response",
  "ok": false,
  "message_type": "unknown",
  "provisioning_state": "ERROR",
  "provisioning_completed": false,
  "next_step": "ERROR",
  "error_code": "UNKNOWN_PROVISIONING_MESSAGE",
  "message": "알 수 없는 BLE provisioning 메시지입니다."
}
```

## 6. 앱 실행 시 화면 결정 흐름

1. 저장된 기기 IP 또는 기기 정보 확인
2. `GET /health` 호출
3. `/health` 실패 시 "기기 전원이 꺼져 있거나 서버가 아직 시작 중"으로 안내하고 재시도 제공
4. `/health` 성공 후 `GET /session/status` 호출
5. `screen_hint` 확인
6. `HOME`이면 홈 화면 유지
7. `PREPARE`이면 준비 화면으로 이동
8. `MEASUREMENT`이면 측정 화면으로 이동
9. `RESULT`이면 결과 화면으로 이동하고 `/session/latest-report` 호출
10. `ERROR`이면 오류 화면으로 이동

## 7. 앱 기기 등록/WiFi 설정 흐름

### A. 최초 기기 등록

1. 앱에서 기기 추가 선택
2. BLE로 `VisionPoseCoach-Pi` 검색
3. 사용자가 기기 선택
4. 앱이 `hello` 메시지 전송
5. 서버 응답 `next_step=SEND_WIFI_CONFIG` 확인
6. `pairing_code` 확인
7. 앱에서 WiFi SSID/PW 입력 화면 표시
8. 앱이 `configure_wifi` 메시지 전송
9. 서버 응답 `provisioning_state=COMPLETED`, `next_step=CHECK_NETWORK_STATUS` 확인
10. 앱이 `/provisioning/status` 또는 `/network/status` 호출
11. `network_ready` 또는 `wifi_connected` 상태 확인
12. 기기 IP 저장
13. 홈 또는 측정 준비 화면으로 이동

이번 단계에서는 실제 BLE advertising, pairing, characteristic write와 실제 OS WiFi 변경을 구현하지 않습니다. FastAPI HTTP mock API로 `BLEProvisioningManager`와 `WiFiManager` 연동 구조를 먼저 검증합니다.

### B. 앱 재실행

1. 저장된 기기 IP 확인
2. `/health` 호출
3. `/health` 실패 시 기기 전원 또는 서버 시작 중 상태로 안내
4. `/health` 성공 후 `/session/status` 호출
5. `screen_hint`에 따라 `HOME`, `PREPARE`, `MEASUREMENT`, `RESULT`, `ERROR` 화면으로 이동

### C. 측정 중 앱 재실행

1. `/health` 성공 확인
2. `/session/status` 확인
3. `screen_hint=MEASUREMENT`이면 측정 화면 자동 복귀
4. `/mjpg`, `/ws` 재연결

### D. 등록 실패

1. `/provisioning/status` 또는 BLE response의 `next_step=ERROR` 확인
2. 앱에서 WiFi 정보 재입력 또는 기기 등록 재시도 제공

## 8. 측정 중 앱 재실행/재접속 복구 흐름

1. 앱 재실행
2. `GET /session/status` 호출
3. `is_running=true`, `screen_hint=MEASUREMENT`, `state=MEASURING` 확인
4. `elapsed_sec`, `duration_sec`, `remain_sec`, `latest_result`로 측정 화면 즉시 복구
5. `/mjpg` 재연결로 카메라 프리뷰 복구
6. `/ws` 재연결
7. `session_snapshot` 수신 후 현재 상태 재확인
8. 이후 `measurement` 메시지로 화면 갱신

## 9. 측정 시작/종료 흐름

측정 시작:
1. 앱이 `start_session` 명령 전송
2. 서버가 준비 상태로 전환
3. `status` 메시지로 준비 진행 상황 전달
4. `MEASURING` 진입 후 `measurement` 메시지 시작

측정 종료:
1. 앱이 `stop_session` 명령 전송하거나 `duration_sec` 종료
2. 서버가 `STOPPED` 상태로 전환
3. 앱은 `screen_hint=RESULT`에 따라 결과 화면으로 이동
4. `/session/latest-report`로 결과 조회

## 10. 앱용 응답에서 제외하는 필드

다음 필드는 `/session/status`, `session_snapshot`, `status`, `measurement`에 포함하지 않습니다.

- `pose_features`
- `face_features`
- `landmarks`
- `blendshapes`
- `raw_frame`
- `frame`
- `image_base64`
- `condition`
- `model_raw_output`
- 큰 debug dict
