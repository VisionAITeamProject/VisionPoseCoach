# Flutter BLE Integration Guide

This repository currently has no Flutter project. This guide defines the client contract; it does not add a Flutter dependency to the server repository.

## GATT contract

| Item | Value / properties |
| --- | --- |
| Device name | `VisionPoseCoach-Pi` |
| Advertisement local name | `VPC-Pi`; the tested btmgmt backend includes the adapter local name with `-n` |
| Service | `9f4c0001-7d9a-4b57-9d9f-000000000001` |
| WiFi Configure | `9f4c0002-7d9a-4b57-9d9f-000000000002` / Write |
| Status | `9f4c0003-7d9a-4b57-9d9f-000000000003` / Read, Notify |
| WiFi Scan | `9f4c0005-7d9a-4b57-9d9f-000000000005` / Read, Write, Notify |
| Network Info | `9f4c0006-7d9a-4b57-9d9f-000000000006` / Read, Notify |
| Hello / Device Info | `9f4c0004-7d9a-4b57-9d9f-000000000004` / Read only |

Hello is read-only. Do not send a hello JSON. Configure is one complete UTF-8 JSON write, currently limited to 512 bytes:

```json
{"type":"configure_wifi","client_id":"phone-001","ssid":"MyWifi","password":"my-password"}
```

Status never contains the password:

```json
{"mode":"real_ble","device_name":"VisionPoseCoach-Pi","state":"ADVERTISING","wifi_connected":false,"ssid":null,"last_error":null}
```

States are `IDLE`, `ADVERTISING`, `CONNECTED`, `WIFI_CONFIGURING`, `WIFI_CONNECTED`, and `FAILED`. In `dry_run`, a configuration request can be accepted while `wifi_connected=false`; only `real` or `mock` reports an actual/mock connected status.

## Package candidates

- `flutter_blue_plus`: broad Android/iOS support and scan/connect/discover/read/write/notify APIs.
- `flutter_reactive_ble`: stream-oriented API and explicit connection state handling.

Choose one in the Flutter repository after checking its current platform requirements. Do not install both for the same connection layer. The following sketch uses `flutter_blue_plus`-style APIs and may need small adjustments for the selected package version.

## Platform permissions

Android 12+ needs runtime `BLUETOOTH_SCAN` and `BLUETOOTH_CONNECT`; declare them in `AndroidManifest.xml`. Android 11 and earlier commonly require location permission for scanning. Follow the chosen package's current guidance for `usesPermissionFlags="neverForLocation"`, SDK levels, and runtime requests.

On iOS add `NSBluetoothAlwaysUsageDescription` to `Info.plist` (and the older peripheral usage key only if the deployment target/package requires it). Bluetooth must be powered on; handle denied/restricted authorization without repeatedly prompting.

## Client flow

1. Confirm Bluetooth permission and adapter state.
2. Find `VPC-Pi` in the BLE scan results.
3. Connect with a timeout and discover services.
4. Verify the VisionPoseCoach Service UUID during discovery, then read Hello / Device Info and use its full `device_name` and `service_uuid` for final verification.
5. Subscribe to Status (`0003`) and Network Info (`0006`) notifications, then read Status once.
6. Encode and write the configure JSON to Configure (`0002`) with response.
7. Receive `WIFI_CONFIGURING`, then `WIFI_CONNECTED`, then Network Info.
8. Call `http://ip:port/health` (fall back to `host` when `ip` is null).
9. Disconnect BLE only after Network Info is available and `/health` succeeds; then use HTTP/WebSocket/MJPG.

## Wi-Fi scan flow

Subscribe to notifications on WiFi Scan (`9f4c0005-7d9a-4b57-9d9f-000000000005`) **before** writing the request. Flutter writes exactly once for each refresh; the Raspberry Pi runs one scan and returns the result through multiple notifications. `request_id` identifies every event belonging to that refresh and should be newly generated for a later refresh.

Request (one Write):

```json
{"type":"scan_wifi","request_id":"scan-001"}
```

Response sequence (multiple Notify values):

```json
{"t":"started","r":"scan-001"}
{"t":"begin","r":"scan-001","n":1}
{"t":"net","r":"scan-001","i":0,"n":1,"s":"robotA5G","g":100,"e":"WPA2","p":1}
{"t":"end","r":"scan-001","n":1}
```

`p` is `1` when a password is required and `0` for an open network. Read returns only the latest event/current state, such as `{"t":"idle"}` or the last `end`; it never returns the whole network list. A second request while scanning returns `{"t":"error","r":"scan-002","c":"scan_busy"}`. A scan failure returns `scan_failed`. Requests made without enabling Notify are rejected safely and logged by the Raspberry Pi.

After the user selects an SSID, subscribe to Status and write the existing WiFi Configure characteristic once:

```json
{"type":"configure_wifi","client_id":"phone-001","ssid":"robotA5G","password":"user-entered-password"}
```

Continue reading/listening to Status (`9f4c0003-7d9a-4b57-9d9f-000000000003`) for `WIFI_CONFIGURING`, followed by `WIFI_CONNECTED` or `FAILED`.

The app must subscribe to both Status and Network Info Notify before writing. On `WIFI_CONNECTED`, wait for Network Info (or Read `0006` if Notify was missed), then call `/health`. Do not disconnect BLE merely because Status is connected. On `FAILED`, the server does not send Network Info, so a stale address is never presented as the result of a failed attempt. A repeated Configure write while active is rejected and never starts a second `nmcli` operation.

Network Info is compact UTF-8 JSON and never contains credentials:

```json
{"ip":"10.10.141.34","host":"raspi5-009.local","port":8000,"interface":"wlan0"}
```

Before Wi-Fi, or when DHCP has not assigned an address within the bounded retry, `ip` is `null`; `host`, `port`, and `interface` remain readable. Address selection order is: current BLE `ip`, current BLE `host`, a previously saved address, then another Network Info Read or reprovisioning. Prefer the current `ip` whenever present.

## Dart service sketch

```dart
import 'dart:async';
import 'dart:convert';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

class VisionPoseBleService {
  static final serviceUuid = Guid('9f4c0001-7d9a-4b57-9d9f-000000000001');
  static final configureUuid = Guid('9f4c0002-7d9a-4b57-9d9f-000000000002');
  static final statusUuid = Guid('9f4c0003-7d9a-4b57-9d9f-000000000003');
  static final helloUuid = Guid('9f4c0004-7d9a-4b57-9d9f-000000000004');
  static final networkInfoUuid = Guid('9f4c0006-7d9a-4b57-9d9f-000000000006');

  BluetoothDevice? _device;
  BluetoothCharacteristic? _configure;
  BluetoothCharacteristic? _status;
  BluetoothCharacteristic? _networkInfo;
  StreamSubscription<List<int>>? _statusSubscription;
  StreamSubscription<List<int>>? _networkInfoSubscription;

  Future<Map<String, dynamic>> connectAndVerify(BluetoothDevice device) async {
    await device.connect(timeout: const Duration(seconds: 12));
    _device = device;
    final services = await device.discoverServices();
    final service = services.firstWhere((s) => s.uuid == serviceUuid);
    BluetoothCharacteristic find(Guid id) =>
        service.characteristics.firstWhere((c) => c.uuid == id);
    _configure = find(configureUuid);
    _status = find(statusUuid);
    _networkInfo = find(networkInfoUuid);
    final hello = jsonDecode(utf8.decode(await find(helloUuid).read())) as Map<String, dynamic>;
    if (hello['device_name'] != 'VisionPoseCoach-Pi') {
      await disconnect();
      throw StateError('Unexpected BLE device');
    }
    await _status!.setNotifyValue(true);
    await _networkInfo!.setNotifyValue(true);
    _networkInfoSubscription = _networkInfo!.onValueReceived.listen((bytes) {
      final data = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
      final ip = data['ip'] as String?;
      final host = data['host'] as String?;
      final port = data['port'] as int? ?? 8000;
      // Prefer ip, fall back to host, and verify http://address:port/health.
    });
    return hello;
  }

  Stream<Map<String, dynamic>> statusStream() async* {
    final characteristic = _status ?? (throw StateError('Not connected'));
    yield jsonDecode(utf8.decode(await characteristic.read())) as Map<String, dynamic>;
    await for (final value in characteristic.lastValueStream) {
      if (value.isNotEmpty) yield jsonDecode(utf8.decode(value)) as Map<String, dynamic>;
    }
  }

  Future<void> configureWifi(String clientId, String ssid, String password) async {
    final characteristic = _configure ?? (throw StateError('Not connected'));
    final value = utf8.encode(jsonEncode({
      'type': 'configure_wifi', 'client_id': clientId, 'ssid': ssid, 'password': password,
    }));
    if (value.length > 512) throw ArgumentError('Provisioning payload is too large');
    await characteristic.write(value, withoutResponse: false);
  }

  Future<void> disconnect() async {
    await _statusSubscription?.cancel();
    await _networkInfoSubscription?.cancel();
    _statusSubscription = null;
    _networkInfoSubscription = null;
    final device = _device;
    _device = null;
    if (device != null) await device.disconnect();
  }
}
```

Never print the configure payload or an exception object that embeds it. Keep the password only in the input form long enough to perform the write, then clear it.

## UI and retry behavior

Use explicit screens/states: scanning → device found → connecting → WiFi input → configuring → connected or failed. Apply scan/connect/write/status timeouts and always cancel subscriptions on retry. For `FAILED`, show only the server's safe `last_error`, allow corrected credentials, and reconnect/resubscribe if BLE disconnected. For ambiguous timeout, read Status once before retrying the write to avoid unnecessary duplicate network changes. After `WIFI_CONNECTED`, BLE success is not enough: show completion only after `/network/status` or `/health` succeeds over WiFi.
