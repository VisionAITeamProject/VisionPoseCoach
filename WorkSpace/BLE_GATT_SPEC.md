# VisionPoseCoach BLE GATT Provisioning Spec

This document defines the implemented Raspberry Pi BLE provisioning contract.
The `/provisioning/ble/*` FastAPI endpoints remain HTTP mock/debug APIs only. Real advertising and GATT are provided by `network/ble_gatt_server.py` and `tools/run_ble_gatt_server.py`.

## Current State

- `network/ble_provisioning_manager.py` validates payloads, owns provisioning state, and calls the shared `WiFiManager`; FastAPI also uses it for its HTTP mock.
- `network/ble_gatt_server.py` always registers the real BlueZ GATT application through the system D-Bus. Advertising can use BlueZ D-Bus or `btmgmt`.
- `/provisioning/ble/*` is not real BLE.
- The HTTP mock exists so the Flutter app and FastAPI server can test the provisioning flow without BLE hardware.
- The real BlueZ implementation exists in code, but advertisement registration still requires Raspberry Pi hardware verification even when pytest passes.
- The Flutter app must scan by the Provisioning Service UUID and write WiFi credentials through a GATT characteristic.
- The payload received over BLE must ultimately call `WiFiManager.configure_wifi(ssid, password)`.
- Passwords must never be included in responses, logs, status payloads, or debug output.

## Device

- Device Name (Hello / Device Info): `VisionPoseCoach-Pi`
- Advertisement Local Name: `VPC-Pi` by default. The `btmgmt` backend temporarily sets the adapter name and uses `add-adv -n` so iPhone scanners display it.
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
| WiFi Scan Characteristic | `9f4c0005-7d9a-4b57-9d9f-000000000005` | Read, Write, Notify |
| Network Info Characteristic | `9f4c0006-7d9a-4b57-9d9f-000000000006` | Read, Notify |

## Network Info

Read returns the current endpoint and a successful Configure sends it after the `WIFI_CONNECTED` Status notification:

```json
{"ip":"10.10.141.34","host":"raspi5-009.local","port":8000,"interface":"wlan0"}
```

Real mode obtains only `wlan0` with `nmcli -g IP4.ADDRESS device show wlan0`, removes CIDR, rejects IPv6, and retries up to five times at 0.4-second intervals without blocking the D-Bus loop. Hostname is normalized to one `.local` suffix. `VPC_FASTAPI_PORT` selects the port and defaults to 8000. Mock mode uses `192.168.0.50` / `visionposecoach-mock.local`; dry-run keeps `ip=null` and uses the OS mDNS hostname. A successful Wi-Fi connection remains successful if DHCP is delayed beyond retries; Network Info then contains `ip=null` and can be read again. On Wi-Fi failure no Network Info notification is sent, preventing a stale IP from being treated as the failed attempt's result.

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

WiFi Scan characteristic: `9f4c0005-7d9a-4b57-9d9f-000000000005` (`Read`, `Write`, `Notify`). Subscribe first, then write one `{"type":"scan_wifi","request_id":"scan-001"}` request. The server sends multiple compact `started`, `begin`, `net`, and `end` notifications carrying the same `request_id`; errors use `{"t":"error","r":"scan-001","c":"scan_failed"}` (or `scan_busy`). See `docs/FLUTTER_BLE_INTEGRATION.md` for the complete field contract.

1. Scan for the local name `VPC-Pi`.
2. Connect and discover the provisioning service.
3. Verify the Provisioning Service UUID during GATT Service Discovery.
4. Read Hello / Device Info and verify the full device name.
5. Subscribe to Status and Network Info notifications, then read Status once.
6. UTF-8 encode the configure JSON and write it to WiFi Configure.
7. Wait for `WIFI_CONFIGURING`, `WIFI_CONNECTED`, then Network Info; on failure display `last_error` and allow retry.
8. If Network Info Notify was missed, Read it. Verify `http://ip:port/health` (or use `host` when IP is null).
9. Disconnect BLE only after Network Info and `/health` succeed.
10. Use HTTP/WebSocket/MJPG over Wi-Fi for all measurement traffic.

## Write Size Limitation

The server accepts one complete UTF-8 JSON write of at most 512 bytes. Application-level chunk reassembly is not implemented. Flutter should use a write-with-response/long-write facility when its platform MTU requires it; otherwise keep SSID, client ID, and password compact. A partial JSON write is rejected without retaining credentials.

## Implementation Notes

1. Keep the full device name `VisionPoseCoach-Pi` in Hello / Device Info and use the shorter advertisement name `VPC-Pi`.
2. Advertise the unchanged Provisioning Service UUID through the selected `auto`, `dbus`, or `btmgmt` backend.
3. Expose Hello / Device Info as read-only and accept only `configure_wifi` JSON on the configure characteristic.
4. Reuse `BLEProvisioningManager.handle_gatt_configure(payload)` for validation and state handling.
5. Route WiFi credentials to `WiFiManager.configure_wifi(ssid, password)`.
6. Notify the Status Characteristic when provisioning state changes.
7. After WiFi configuration, notify Status `WIFI_CONNECTED`, then Network Info, and check `/health` before BLE disconnect.

Run the peripheral with explicit names when needed:

```bash
VPC_WIFI_MODE=mock python tools/run_ble_gatt_server.py --debug --device-name VisionPoseCoach-Pi --advertise-name VPC-Pi --advertising-backend auto --advertising-instance 1
```

Advertising backend behavior:

- `auto` (default): try D-Bus advertising first. If BlueZ returns `org.bluez.Error.Failed`, start `btmgmt` advertising on the same `hciN` adapter.
- `dbus`: use only `org.bluez.LEAdvertisingManager1`; no `btmgmt` fallback.
- `btmgmt`: keep GATT Application registration on D-Bus. Read and save the adapter name, temporarily set it to `advertise_name`, then run `btmgmt add-adv -c -g -n -u <service_uuid> <instance>`.
- A successful `btmgmt` instance number is retained and removed with `btmgmt rm-adv` during Ctrl+C, SIGTERM, startup failure cleanup, or normal shutdown.
- After advertisement removal, restore the saved adapter name when possible. Restoration failure is logged but does not prevent server shutdown.
- `btmgmt` requires sufficient Bluetooth management privileges, so the Raspberry Pi command normally runs under `sudo`.

Direct Raspberry Pi fallback example:

```bash
sudo -E env VPC_WIFI_MODE=real VPC_FASTAPI_PORT=8000 \
  /home/willtek/VisionPoseCoach/.venv/bin/python \
  tools/run_ble_gatt_server.py \
  --debug \
  --advertising-backend btmgmt \
  --advertising-instance 1
```

For nRF Connect: connect to VisionPoseCoach, enable Notify on `0003` and `0006`, write credentials to `0002`, verify `WIFI_CONFIGURING` → `WIFI_CONNECTED` → Network Info, Read `0006` again, then run `curl http://<ip>:8000/health`. This hardware check is required in addition to unit tests.

Unit tests verify the advertisement property contract, but BlueZ registration behavior depends on the Raspberry Pi adapter, firmware, and BlueZ version. A successful `pytest` run does not replace an on-device scan/connect/read test.

## iOS Peripheral Identifier vs Service UUID

An iPhone BLE scanner may display a value such as `6698a28f-834f-4978-37f0-05b5e3ec3f7b`. This can be an iOS Peripheral Identifier assigned to distinguish the peripheral in that iOS environment. It is not the VisionPoseCoach Service UUID and must not replace the UUID constants in this document.

- iOS Peripheral Identifier: an iOS-side identifier for the BLE peripheral; it may differ by device or iOS environment.
- VisionPoseCoach Service UUID: `9f4c0001-7d9a-4b57-9d9f-000000000001`; verify it after connection through GATT Service Discovery.
