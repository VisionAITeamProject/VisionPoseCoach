# VisionPoseCoach Server Stage 1

This is the server skeleton for smartphone app integration.
It includes the FastAPI app, camera stream, session API, WebSocket session messages, and WiFi provisioning modes for app development and Raspberry Pi testing.

## Install

```bash
pip install -r requirements-server.txt
```

## Run

Run from the `WorkSpace` directory:

```bash
cd /home/pi/VisionPoseCoach/WorkSpace
python server_main.py
```

WiFi mode is selected with `VPC_WIFI_MODE`. The safe default is `dry_run`.

App UI development mock mode:

```bash
VPC_WIFI_MODE=mock python server_main.py
```

Raspberry Pi real WiFi mode:

```bash
VPC_WIFI_MODE=real python server_main.py
```

Before using `real` mode in the full server, you can run the focused Raspberry Pi verification script:

```bash
python tools/verify_real_wifi.py
python tools/verify_real_wifi.py --connect --ssid "MyWifi" --password "my-password"
```

The first command checks status and scans nearby WiFi networks only. It does not connect. The second command attempts a connection, and the script never prints the password.

Or:

```bash
python -m uvicorn server_main:app --host 0.0.0.0 --port 8000
```

If you use a virtual environment on Raspberry Pi:

```bash
cd /home/pi/VisionPoseCoach/WorkSpace
source .venv/bin/activate
python server_main.py
```

## Endpoints

- `GET /health`: server state and camera status
- `GET /mjpg`: MJPG stream; returns a dummy frame if a camera is not available
- `GET /session/status`: app-facing session snapshot
- `GET /session/latest-report`: latest finished session report
- `GET /session/report/{session_id}`: report lookup by session id
- `GET /network/status`: current network/WiFi status
- `GET /network/wifi/scan`: WiFi scan response for the selected mode
- `POST /network/wifi/configure`: configure WiFi for the selected mode
- `POST /network/wifi/forget`: clear the stored dry-run WiFi configuration request
- `GET /provisioning/ble/status`: current dry-run BLE provisioning status
- `GET /provisioning/status`: app-facing combined device registration status
- `POST /provisioning/ble/start`: mark dry-run BLE advertising as started
- `POST /provisioning/ble/stop`: mark dry-run BLE advertising as stopped
- `POST /provisioning/ble/message`: process a mock BLE provisioning message over HTTP
- `POST /provisioning/ble/reset`: reset dry-run BLE provisioning state
- `WS /ws`: accepts `start_session` and `stop_session`

WebSocket command examples:

```json
{"command": "start_session"}
```

```json
{"command": "stop_session"}
```

## Network / WiFi Development API

`network/wifi_manager.py` supports three modes. The mode is read from `VPC_WIFI_MODE`, with `dry_run` as the default.

Important legacy note:

- The FastAPI server uses `network/wifi_manager.py`.
- The root-level `wifi_manager.py` is a legacy/experimental file and is not used by the current server.
- The legacy file may contain real OS WiFi commands such as `nmcli` or `sudo nmcli`, so do not import or execute it from the current app integration path.
- Current real WiFi connection support is implemented in the `real` mode inside `network/wifi_manager.py`; it still needs validation on the target Raspberry Pi OS image with `nmcli`.

- `dry_run`: validates WiFi configuration requests and stores only safe state such as `last_configured_ssid`. No OS WiFi command is executed.
- `mock`: returns fake WiFi scan data and fake successful connection responses for Flutter UI development.
- `real`: uses `nmcli` on Raspberry Pi OS to scan, connect, and read WiFi status. This code path is implemented, but must be verified on the actual Raspberry Pi before treating it as production-ready.

Real mode uses these commands without `shell=True`:

```bash
nmcli -t -f SSID,SIGNAL,SECURITY device wifi list --rescan yes
nmcli device wifi connect "<SSID>" password "<PASSWORD>"
nmcli -t -f ACTIVE,SSID dev wifi
hostname -I
```

Current behavior:

- WiFi passwords are not returned by API responses and are not included in `/health` debug output.
- In dry-run mode, `/health.app.network_ready` may be `true` for development even when `wifi_connected=false`.
- If `nmcli` is missing or a command fails, the API returns `ok=false` with a friendly message and without exposing the password.
- `tools/verify_real_wifi.py` prints a NetworkManager/nmcli hint when `nmcli` is missing.

WiFi configure example:

```json
{
  "ssid": "MyWifi",
  "password": "mypassword123"
}
```

Expected dry-run response:

```json
{
  "type": "wifi_configure_result",
  "ok": true,
  "mode": "dry_run",
  "ssid": "MyWifi",
  "message": "WiFi 설정 요청을 저장했습니다. 실제 연결 변경은 배포 단계에서 구현됩니다."
}
```

API test examples:

```bash
curl http://localhost:8000/network/status

curl http://localhost:8000/network/wifi/scan

curl -X POST http://localhost:8000/network/wifi/configure \
  -H "Content-Type: application/json" \
  -d '{"ssid":"MyWifi","password":"my-password"}'
```

## BLE Provisioning Development API

`network/ble_provisioning_manager.py` mirrors the selected WiFi mode. BLE is only for initial device setup. Realtime measurement uses WiFi-based HTTP, WebSocket, and MJPG endpoints.

Important current-state note:

- `/provisioning/ble/*` endpoints are not real BLE. They remain mock/debug HTTP APIs.
- `network/ble_gatt_server.py` contains the real BlueZ D-Bus GATT application and advertisement implementation.
- Run the actual peripheral separately with `tools/run_ble_gatt_server.py`; Raspberry Pi hardware verification is still required.
- The Flutter app must find `VisionPoseCoach-Pi` through BLE scan and send SSID/password through a GATT characteristic write.
- BLE payloads must ultimately route to `WiFiManager.configure_wifi(ssid, password)`.
- The GATT contract is documented in `BLE_GATT_SPEC.md`.
- FastAPI and the GATT runner are separate processes. `/provisioning/ble/status` does not mirror the live GATT process state.

Current behavior:

- The code does not force Bluetooth or network system settings; operational commands are manual diagnostics only.
- `/provisioning/ble/message` remains an HTTP mock of the configure payload.
- FastAPI BLE status intentionally reports `implementation=http_mock`, `real_ble=false`, and `gatt_available=false`.
- The standalone GATT server registers the service and advertisement through BlueZ system D-Bus.
- The BLE manager receives `configure_wifi` messages and calls `WiFiManager.configure_wifi(ssid, password)`.
- WiFi passwords are not stored in BLE manager state and are not returned by responses or `/health` debug output.
- `dbus-next` is loaded only when the standalone server starts, so development imports work without BlueZ.

Provisioning state model:

- `NOT_STARTED`: registration has not started
- `ADVERTISING`: dry-run advertising is enabled and the server is waiting for the app
- `CLIENT_CONNECTED`: the app sent `hello`
- `WIFI_CONFIG_RECEIVED`: WiFi configuration was received
- `WIFI_CONFIGURED`: reserved for real WiFi configuration completion
- `COMPLETED`: dry-run WiFi configuration request was accepted by `WiFiManager`
- `ERROR`: provisioning failed

In dry-run mode, `COMPLETED` means the WiFi configuration request was processed by the server. It does not prove that Raspberry Pi joined the WiFi network.

### Raspberry Pi BLE verification checklist

Run mock WiFi mode first so BLE can be verified without changing the active network:

```bash
sudo systemctl status bluetooth
bluetoothctl show
rfkill list
nmcli device status
python -c "import dbus_next; print('dbus-next ok')"
VPC_WIFI_MODE=mock python tools/run_ble_gatt_server.py --debug
```

After scan, read, write, and notify work from a phone, test real WiFi deliberately:

```bash
nmcli device wifi list
VPC_WIFI_MODE=real python tools/run_ble_gatt_server.py --debug
```

`VPC_WIFI_MODE=real` changes the Raspberry Pi WiFi connection and may disconnect the current SSH session. If `VisionPoseCoach-Pi` is not visible, check `bluetooth.service`, `rfkill`, and `Powered: yes` in `bluetoothctl show`. If GATT registration fails, check the BlueZ version, adapter GATT/advertising support, system D-Bus policy, and `journalctl -u bluetooth`. If WiFi configuration fails, confirm the SSID with `nmcli device wifi list` and inspect NetworkManager status. Do not place a password in diagnostic commands, logs, screenshots, or issue reports.

Mock provisioning message example:

```json
{
  "type": "configure_wifi",
  "client_id": "phone-001",
  "ssid": "MyWifi",
  "password": "mypassword123"
}
```

Expected response:

```json
{
  "type": "ble_provisioning_response",
  "ok": true,
  "message_type": "configure_wifi",
  "message": "WiFi 설정 요청을 처리했습니다.",
  "wifi": {
    "mode": "dry_run",
    "connected": false,
    "ssid": null,
    "provisioning_required": true,
    "last_configured_ssid": "MyWifi",
    "last_error": null
  }
}
```

HTTP mock registration flow:

1. Start dry-run advertising.

```bash
POST /provisioning/ble/start
```

Expected: `next_step=WAIT_FOR_APP`, `ble.provisioning_state=ADVERTISING`.

2. Send hello through the mock BLE message API.

```json
{
  "type": "hello",
  "client_id": "phone-001",
  "app_version": "0.1.0"
}
```

Expected: `provisioning_state=CLIENT_CONNECTED`, `next_step=SEND_WIFI_CONFIG`.

3. Send WiFi configuration through the mock BLE message API.

```json
{
  "type": "configure_wifi",
  "client_id": "phone-001",
  "ssid": "MyWifi",
  "password": "mypassword123"
}
```

Expected: `provisioning_state=COMPLETED`, `next_step=CHECK_NETWORK_STATUS`. The response must not include `password`.

4. Check combined registration status.

```bash
GET /provisioning/status
```

Expected: `ble`, `wifi`, `provisioning_state`, and `next_step` are present.

5. Check network status.

```bash
GET /network/status
```

6. Check app health.

```bash
GET /health
```

Expected: `app.provisioning_state`, `app.ble_available`, and `app.ble_advertising` are present. Passwords must never appear in responses or logs.

## Raspberry Pi Auto Start Preparation

The app assumes the Raspberry Pi server is already running after boot. The recommended service entrypoint is:

```bash
cd /home/pi/VisionPoseCoach/WorkSpace
/home/pi/VisionPoseCoach/WorkSpace/.venv/bin/python server_main.py
```

This repository provides a systemd template and dry-run generation script. The script only renders a service file under `deploy/generated`; it does not install, enable, start, stop, or restart anything.

### systemd Service Template

Template path:

```text
deploy/vision-pose-coach.service.template
```

The template keeps Raspberry Pi specific values as placeholders:

- `{{USER}}`
- `{{PROJECT_DIR}}`
- `{{PYTHON_BIN}}`

### Configure Values

Copy and edit the example config on the Raspberry Pi:

```bash
cp deploy/systemd_config.example.env deploy/systemd_config.env
```

Example values:

```text
PROJECT_DIR=/home/pi/VisionPoseCoach/WorkSpace
PYTHON_BIN=/home/pi/VisionPoseCoach/WorkSpace/.venv/bin/python
SERVICE_USER=pi
SERVICE_NAME=vision-pose-coach.service
```

Do not put passwords or secrets in this file.

### Generate Service File

Dry-run render:

```bash
python deploy/install_systemd_service.py --config deploy/systemd_config.env --dry-run
```

Generated file:

```text
deploy/generated/vision-pose-coach.service
```

The script prints the manual commands to run later. It does not execute `sudo`, does not copy to `/etc/systemd/system`, and does not run `systemctl`.

### Actual Install Commands

After reviewing the generated service file on the Raspberry Pi, run these manually:

```bash
sudo cp deploy/generated/vision-pose-coach.service /etc/systemd/system/vision-pose-coach.service
sudo systemctl daemon-reload
sudo systemctl enable vision-pose-coach.service
sudo systemctl start vision-pose-coach.service
sudo systemctl status vision-pose-coach.service
```

### Status And Logs

Check service status:

```bash
systemctl status vision-pose-coach.service
```

Follow logs:

```bash
journalctl -u vision-pose-coach.service -f
```

Restart:

```bash
sudo systemctl restart vision-pose-coach.service
```

Stop:

```bash
sudo systemctl stop vision-pose-coach.service
```

Disable boot auto start:

```bash
sudo systemctl disable vision-pose-coach.service
```

### Health Check

Use the dependency-free health check script:

```bash
python deploy/check_server_health.py --url http://127.0.0.1:8000/health
```

If the server is not running yet, the script prints a friendly failure message instead of crashing.

### Troubleshooting

- Verify `PROJECT_DIR` points to the `WorkSpace` directory.
- Verify `PYTHON_BIN` points to a Python executable with `requirements-server.txt` installed.
- Run `python server_main.py` manually before installing the service.
- Use `journalctl -u vision-pose-coach.service -f` to inspect startup errors.
- If the camera is not available, `/health.debug.camera` can help confirm whether the server is using a dummy frame source.

## Test

Run lightweight payload checks from the `WorkSpace` directory:

```bash
python tests/verify_api_payloads.py
python tests/verify_wifi_manager.py
python tests/verify_ble_provisioning.py
python tests/verify_systemd_deploy.py
python -m py_compile core/session_controller.py network/api_server.py network/wifi_manager.py network/ble_provisioning_manager.py deploy/install_systemd_service.py deploy/check_server_health.py tests/test_app_api_spec.py tests/test_wifi_manager.py tests/test_ble_provisioning_manager.py tests/test_systemd_deploy.py tests/verify_api_payloads.py tests/verify_wifi_manager.py tests/verify_ble_provisioning.py tests/verify_systemd_deploy.py
```

If `pytest` is installed:

```bash
python -m pytest tests
```
