# Flutter BLE Integration Guide

This repository currently has no Flutter project. This guide defines the client contract; it does not add a Flutter dependency to the server repository.

## GATT contract

| Item | Value / properties |
| --- | --- |
| Device name | `VisionPoseCoach-Pi` |
| Advertisement local name | `VPC-Pi` when included; it may be absent after BlueZ fallback |
| Service | `9f4c0001-7d9a-4b57-9d9f-000000000001` |
| WiFi Configure | `9f4c0002-7d9a-4b57-9d9f-000000000002` / Write |
| Status | `9f4c0003-7d9a-4b57-9d9f-000000000003` / Read, Notify |
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
2. Scan by service UUID. Use `VPC-Pi`, when visible, only as an additional hint rather than the primary filter.
3. Connect with a timeout and discover services.
4. Read Hello / Device Info and use its full `device_name` and `service_uuid` for final verification.
5. Subscribe to Status notifications, then perform one Status read.
6. Encode and write the configure JSON with response.
7. Decode status notifications until `WIFI_CONNECTED` or `FAILED`.
8. Disconnect BLE on either terminal state.
9. On success, discover/use the Pi IP and call `/network/status` or `/health` over WiFi.
10. Use HTTP/WebSocket/MJPG, not BLE, for measurement data.

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

  BluetoothDevice? _device;
  BluetoothCharacteristic? _configure;
  BluetoothCharacteristic? _status;
  StreamSubscription<List<int>>? _statusSubscription;

  Future<Map<String, dynamic>> connectAndVerify(BluetoothDevice device) async {
    await device.connect(timeout: const Duration(seconds: 12));
    _device = device;
    final services = await device.discoverServices();
    final service = services.firstWhere((s) => s.uuid == serviceUuid);
    BluetoothCharacteristic find(Guid id) =>
        service.characteristics.firstWhere((c) => c.uuid == id);
    _configure = find(configureUuid);
    _status = find(statusUuid);
    final hello = jsonDecode(utf8.decode(await find(helloUuid).read())) as Map<String, dynamic>;
    if (hello['device_name'] != 'VisionPoseCoach-Pi') {
      await disconnect();
      throw StateError('Unexpected BLE device');
    }
    await _status!.setNotifyValue(true);
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
    _statusSubscription = null;
    final device = _device;
    _device = null;
    if (device != null) await device.disconnect();
  }
}
```

Never print the configure payload or an exception object that embeds it. Keep the password only in the input form long enough to perform the write, then clear it.

## UI and retry behavior

Use explicit screens/states: scanning → device found → connecting → WiFi input → configuring → connected or failed. Apply scan/connect/write/status timeouts and always cancel subscriptions on retry. For `FAILED`, show only the server's safe `last_error`, allow corrected credentials, and reconnect/resubscribe if BLE disconnected. For ambiguous timeout, read Status once before retrying the write to avoid unnecessary duplicate network changes. After `WIFI_CONNECTED`, BLE success is not enough: show completion only after `/network/status` or `/health` succeeds over WiFi.
