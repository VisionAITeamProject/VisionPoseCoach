# VisionPoseCoach BLE GATT Provisioning Spec

This document defines the next implementation target for real Raspberry Pi BLE provisioning.
The current `/provisioning/ble/*` FastAPI endpoints are HTTP mock/debug APIs only. They do not perform BLE advertising, pairing, or GATT characteristic reads/writes.

## Current State

- `network/ble_provisioning_manager.py` is an HTTP mock provisioning state manager.
- `/provisioning/ble/*` is not real BLE.
- The HTTP mock exists so the Flutter app and FastAPI server can test the provisioning flow before the BLE peripheral is implemented.
- In the real BLE stage, Raspberry Pi must advertise as a BLE peripheral.
- The Flutter app must scan for `VisionPoseCoach-Pi` and write WiFi credentials through a GATT characteristic.
- The payload received over BLE must ultimately call `WiFiManager.configure_wifi(ssid, password)`.
- Passwords must never be included in responses, logs, status payloads, or debug output.

## Device

- Device Name: `VisionPoseCoach-Pi`
- Role: Raspberry Pi BLE peripheral / GATT server
- Client: Flutter mobile app BLE central

## UUIDs

Use these UUIDs as the initial implementation contract. They can be changed before release if the app and server are updated together.

| Item | UUID | Properties |
| --- | --- | --- |
| Provisioning Service | `9f4c0001-7d9a-4b57-9d9f-000000000001` | Primary service |
| WiFi Configure Characteristic | `9f4c0002-7d9a-4b57-9d9f-000000000002` | Write |
| Status Characteristic | `9f4c0003-7d9a-4b57-9d9f-000000000003` | Read, Notify |
| Optional Pairing/Hello Characteristic | `9f4c0004-7d9a-4b57-9d9f-000000000004` | Write, Read |

## App To Pi: Hello Payload

```json
{
  "type": "hello",
  "client_id": "phone-001",
  "app_version": "0.1.0"
}
```

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
- `password` is required for secured networks and must not be logged.
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

The response must not include `password`.

## Implementation Notes

1. Start a BLE peripheral named `VisionPoseCoach-Pi`.
2. Advertise the Provisioning Service UUID.
3. Accept `hello` and `configure_wifi` JSON writes from the Flutter app.
4. Reuse the existing `BLEProvisioningManager.handle_provisioning_message(payload)` logic where possible.
5. Route WiFi credentials to `WiFiManager.configure_wifi(ssid, password)`.
6. Notify the Status Characteristic when provisioning state changes.
7. After WiFi configuration, the app should check `/network/status` or `/health` over WiFi.
