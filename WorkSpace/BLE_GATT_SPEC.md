# VisionPoseCoach BLE GATT Provisioning Spec

This document defines the implemented Raspberry Pi BLE provisioning contract.
The `/provisioning/ble/*` FastAPI endpoints remain HTTP mock/debug APIs only. Real advertising and GATT are provided by `network/ble_gatt_server.py` and `tools/run_ble_gatt_server.py`.

## Current State

- `network/ble_provisioning_manager.py` validates payloads, owns provisioning state, and calls the shared `WiFiManager`; FastAPI also uses it for its HTTP mock.
- `network/ble_gatt_server.py` registers a real BlueZ GATT application and LE advertisement through the system D-Bus.
- `/provisioning/ble/*` is not real BLE.
- The HTTP mock exists so the Flutter app and FastAPI server can test the provisioning flow without BLE hardware.
- The real BlueZ implementation exists in code, but advertisement registration still requires Raspberry Pi hardware verification even when pytest passes.
- The Flutter app must scan by the Provisioning Service UUID and write WiFi credentials through a GATT characteristic.
- The payload received over BLE must ultimately call `WiFiManager.configure_wifi(ssid, password)`.
- Passwords must never be included in responses, logs, status payloads, or debug output.

## Device

- Device Name (Hello / Device Info): `VisionPoseCoach-Pi`
- Advertisement Local Name: `VPC-Pi` by default; it may be absent when BlueZ requires the Service UUID-only fallback.
- Role: Raspberry Pi BLE peripheral / GATT server
- Client: Flutter mobile app BLE central

## UUIDs

Use these UUIDs as the initial implementation contract. They can be changed before release if the app and server are updated together.

| Item | UUID | Properties |
| --- | --- | --- |
| Provisioning Service | `9f4c0001-7d9a-4b57-9d9f-000000000001` | Primary service |
| WiFi Configure Characteristic | `9f4c0002-7d9a-4b57-9d9f-000000000002` | Write |
| Status Characteristic | `9f4c0003-7d9a-4b57-9d9f-000000000003` | Read, Notify |
| Hello / Device Info Characteristic | `9f4c0004-7d9a-4b57-9d9f-000000000004` | Read |

## Pi To App: Hello / Device Info

Hello / Device Info is read-only. The app does not write a hello JSON. Reading it returns compact UTF-8 JSON containing `type=device_info`, `device_name`, and `service_uuid`.

## App To Pi: WiFi Configure Payload

Write this JSON to the WiFi Configure Characteristic.

```json
{
  "type": "configure_wifi",
  "client_id": "phone-001",
  "ssid": "MyWifi",
  "password": "my-password"
}
```

Validation rules:

- `ssid` is required and must be 32 bytes or less.
- `password` is currently required by `WiFiManager` (8–63 characters) and must not be logged.
- The server must call `WiFiManager.configure_wifi(ssid, password)`.
- The server must mask or omit `password` before storing any state or returning any status.

## Pi To App: Status / Response Payload

Expose this through the Status Characteristic read/notify path.

```json
{
  "type": "ble_provisioning_response",
  "ok": true,
  "provisioning_state": "COMPLETED",
  "provisioning_completed": true,
  "next_step": "CHECK_NETWORK_STATUS"
}
```

Failure example:

```json
{
  "type": "ble_provisioning_response",
  "ok": false,
  "provisioning_state": "ERROR",
  "provisioning_completed": false,
  "next_step": "ERROR",
  "error_code": "WIFI_CONFIGURE_FAILED",
  "message": "WiFi 설정 요청 처리에 실패했습니다."
}
```

The response must not include `password`. The compact real-GATT status shape is:

```json
{"mode":"real_ble","device_name":"VisionPoseCoach-Pi","state":"ADVERTISING","wifi_connected":false,"ssid":null,"last_error":null}
```

Real GATT state values are `IDLE`, `ADVERTISING`, `CONNECTED`, `WIFI_CONFIGURING`, `WIFI_CONNECTED`, and `FAILED`.

## Flutter Flow

1. Scan for the Provisioning Service UUID. Treat the optional local name `VPC-Pi` only as a hint.
2. Connect and discover the provisioning service.
3. Read Hello / Device Info and verify the device name.
4. Subscribe to Status notifications, then read Status once.
5. UTF-8 encode the configure JSON and write it to WiFi Configure.
6. Wait for `WIFI_CONNECTED`; on failure display `last_error` and allow retry.
7. Disconnect BLE and verify `/network/status` or `/health` over Wi-Fi.
8. Use HTTP/WebSocket/MJPG over Wi-Fi for all measurement traffic.

## Write Size Limitation

The server accepts one complete UTF-8 JSON write of at most 512 bytes. Application-level chunk reassembly is not implemented. Flutter should use a write-with-response/long-write facility when its platform MTU requires it; otherwise keep SSID, client ID, and password compact. A partial JSON write is rejected without retaining credentials.

## Implementation Notes

1. Keep the full device name `VisionPoseCoach-Pi` in Hello / Device Info and use the shorter advertisement name `VPC-Pi`.
2. Advertise the Provisioning Service UUID with LocalName first; if BlueZ rejects those parameters, retry with the Service UUID only.
3. Expose Hello / Device Info as read-only and accept only `configure_wifi` JSON on the configure characteristic.
4. Reuse `BLEProvisioningManager.handle_gatt_configure(payload)` for validation and state handling.
5. Route WiFi credentials to `WiFiManager.configure_wifi(ssid, password)`.
6. Notify the Status Characteristic when provisioning state changes.
7. After WiFi configuration, the app should check `/network/status` or `/health` over WiFi.

Run the peripheral with explicit names when needed:

```bash
VPC_WIFI_MODE=mock python tools/run_ble_gatt_server.py --debug --device-name VisionPoseCoach-Pi --advertise-name VPC-Pi
```

Unit tests verify the advertisement property contract, but BlueZ registration behavior depends on the Raspberry Pi adapter, firmware, and BlueZ version. A successful `pytest` run does not replace an on-device scan/connect/read test.
