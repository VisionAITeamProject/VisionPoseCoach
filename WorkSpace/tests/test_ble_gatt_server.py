import asyncio
import importlib
import logging
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.ble_gatt_server import (
    ADVERTISE_NAME, DEVICE_NAME, HELLO_FLAGS, HELLO_UUID, MAX_WRITE_BYTES,
    SERVICE_UUID, STATUS_UUID, WIFI_CONFIG_UUID, WIFI_SCAN_FLAGS, WIFI_SCAN_UUID,
    NETWORK_INFO_FLAGS, NETWORK_INFO_UUID, NETWORK_INTERFACE,
    MAX_NOTIFY_BYTES, MAX_SCAN_NETWORKS, BLEBackendUnavailable,
    BlueZGattServer, advertisement_properties,
    btmgmt_add_command, btmgmt_info_command, btmgmt_name_command,
    btmgmt_remove_command, build_scan_events, decode_configure_write,
    decode_scan_write, encode_json, hello_payload,
    parse_btmgmt_names,
)
from network.ble_provisioning_manager import BLEProvisioningManager
from network.wifi_manager import WiFiManager


class RecordingWiFi(WiFiManager):
    def __init__(self):
        super().__init__(mode="mock")
        self.calls = []

    def configure_wifi(self, ssid, password):
        self.calls.append((ssid, "***"))
        return super().configure_wifi(ssid, password)


def test_module_imports_without_starting_bluez():
    module = importlib.import_module("network.ble_gatt_server")
    assert module.DEVICE_NAME == DEVICE_NAME
    assert SERVICE_UUID == "9f4c0001-7d9a-4b57-9d9f-000000000001"
    assert WIFI_CONFIG_UUID == "9f4c0002-7d9a-4b57-9d9f-000000000002"
    assert STATUS_UUID == "9f4c0003-7d9a-4b57-9d9f-000000000003"
    assert HELLO_UUID == "9f4c0004-7d9a-4b57-9d9f-000000000004"
    assert WIFI_SCAN_UUID == "9f4c0005-7d9a-4b57-9d9f-000000000005"
    assert NETWORK_INFO_UUID == "9f4c0006-7d9a-4b57-9d9f-000000000006"
    assert NETWORK_INFO_FLAGS == ("read", "notify")
    assert WIFI_SCAN_FLAGS == ("read", "write", "notify")
    assert HELLO_FLAGS == ("read",)


def test_default_advertisement_includes_service_uuid_without_includes():
    properties = advertisement_properties()
    assert properties == {
        "Type": "peripheral",
        "ServiceUUIDs": [SERVICE_UUID],
        "LocalName": ADVERTISE_NAME,
    }
    assert "Includes" not in properties


def test_device_name_and_advertise_name_are_separate_and_hello_uses_full_name():
    manager = BLEProvisioningManager(WiFiManager(mode="mock"), device_name=DEVICE_NAME)
    server = BlueZGattServer(manager)
    assert server.device_name == "VisionPoseCoach-Pi"
    assert server.advertise_name == "VPC-Pi"
    assert hello_payload(server.device_name) == {
        "type": "device_info",
        "device_name": "VisionPoseCoach-Pi",
        "service_uuid": SERVICE_UUID,
    }


def test_service_uuid_only_fallback_omits_local_name():
    assert advertisement_properties(None) == {
        "Type": "peripheral",
        "ServiceUUIDs": [SERVICE_UUID],
    }


def test_invalid_advertisement_parameters_retry_without_local_name():
    class FakeDBusError(Exception):
        type = "org.bluez.Error.Failed"
        text = "Failed to register advertisement"

    class FakeAdvertisingManager:
        def __init__(self):
            self.calls = 0

        async def call_register_advertisement(self, path, options):
            self.calls += 1
            if self.calls == 1:
                raise FakeDBusError("Failed to register advertisement")

    class FakeBus:
        def unexport(self, path, interface):
            self.unexported = (path, interface)

        def export(self, path, interface):
            self.exported = (path, interface)

    class FakeServiceOnlyAdvertisement:
        def __init__(self, path):
            self.path = path

    manager = BLEProvisioningManager(WiFiManager(mode="mock"))
    server = BlueZGattServer(manager)
    original = object()
    server._adapter_path = "/org/bluez/hci0"
    server._adv_manager = FakeAdvertisingManager()
    server._bus = FakeBus()
    server._classes = {"ServiceOnlyAdvertisement": FakeServiceOnlyAdvertisement}
    server._advertisement = original
    server._exports = [("/com/visionposecoach/ble/advertisement0", original)]

    asyncio.run(server._register_advertisement_with_fallback())

    assert server._adv_manager.calls == 2
    assert isinstance(server._advertisement, FakeServiceOnlyAdvertisement)


def test_btmgmt_commands_use_adapter_service_uuid_and_instance():
    assert btmgmt_add_command("hci0", 1) == [
        "btmgmt", "-i", "hci0", "add-adv", "-c", "-g", "-n",
        "-u", SERVICE_UUID, "1",
    ]
    assert btmgmt_remove_command("hci0", 1) == [
        "btmgmt", "-i", "hci0", "rm-adv", "1",
    ]
    assert btmgmt_info_command("hci0") == ["btmgmt", "-i", "hci0", "info"]
    assert btmgmt_name_command("hci0", "VPC-Pi") == [
        "btmgmt", "-i", "hci0", "name", "VPC-Pi",
    ]


def test_btmgmt_info_names_are_parsed_for_later_restoration():
    output = """hci0: addr 00:11:22:33:44:55\n\tname raspberrypi\n\tshort name rpi\n"""
    assert parse_btmgmt_names(output) == ("raspberrypi", "rpi")


def test_btmgmt_backend_stores_and_removes_advertising_instance():
    calls = []

    def command_runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "info":
            return subprocess.CompletedProcess(
                command, 0, stdout="hci0:\n\tname raspberrypi\n\tshort name rpi\n", stderr=""
            )
        return subprocess.CompletedProcess(command, 0, stdout="Instance added: 1", stderr="")

    manager = BLEProvisioningManager(WiFiManager(mode="mock"))
    server = BlueZGattServer(
        manager,
        advertising_backend="btmgmt",
        advertising_instance=1,
        command_runner=command_runner,
    )
    server._adapter_path = "/org/bluez/hci0"

    asyncio.run(server._start_btmgmt_advertising())
    assert server._btmgmt_instance == 1
    assert server.active_advertising_backend == "btmgmt"
    asyncio.run(server.stop())

    assert calls[0][0] == btmgmt_info_command("hci0")
    assert calls[1][0] == btmgmt_name_command("hci0", "VPC-Pi")
    assert calls[2][0] == btmgmt_add_command("hci0", 1)
    assert calls[3][0] == btmgmt_remove_command("hci0", 1)
    assert calls[4][0] == btmgmt_name_command("hci0", "raspberrypi", "rpi")
    assert calls[0][1]["shell"] is False
    assert server._btmgmt_instance is None


def test_auto_backend_falls_back_to_btmgmt_on_bluez_failed():
    class FakeDBusError(Exception):
        type = "org.bluez.Error.Failed"
        text = "Failed to register advertisement"

    def command_runner(command, **kwargs):
        if command[-1] == "info":
            return subprocess.CompletedProcess(
                command, 0, stdout="hci0:\n\tname raspberrypi\n\tshort name\n", stderr=""
            )
        return subprocess.CompletedProcess(command, 0, stdout="Instance added: 1", stderr="")

    manager = BLEProvisioningManager(WiFiManager(mode="mock"))
    server = BlueZGattServer(manager, advertising_backend="auto", command_runner=command_runner)
    server._adapter_path = "/org/bluez/hci0"

    async def fail_dbus_advertisement():
        raise FakeDBusError("Failed to register advertisement")

    server._register_dbus_advertisement_once = fail_dbus_advertisement
    asyncio.run(server._start_advertising_backend())

    assert server.active_advertising_backend == "btmgmt"
    assert server._btmgmt_instance == 1
    asyncio.run(server._stop_btmgmt_advertising())


def test_btmgmt_failure_logs_safe_process_result(caplog):
    def command_runner(command, **kwargs):
        if command[-1] == "info":
            return subprocess.CompletedProcess(
                command, 0, stdout="hci0:\n\tname raspberrypi\n\tshort name\n", stderr=""
            )
        if "name" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            13,
            stdout="controller rejected",
            stderr="Invalid Parameters password=unit-test-secret",
        )

    manager = BLEProvisioningManager(WiFiManager(mode="mock"))
    server = BlueZGattServer(manager, advertising_backend="btmgmt", command_runner=command_runner)
    server._adapter_path = "/org/bluez/hci0"

    with caplog.at_level(logging.ERROR), pytest.raises(BLEBackendUnavailable):
        asyncio.run(server._start_btmgmt_advertising())

    assert "return code=13" in caplog.text
    assert "controller rejected" in caplog.text
    assert "Invalid Parameters" in caplog.text
    assert "unit-test-secret" not in caplog.text
    assert "password=[REDACTED]" in caplog.text
    asyncio.run(server.stop())


def test_btmgmt_permission_denied_has_actionable_sudo_message():
    def command_runner(command, **kwargs):
        if command[-1] == "info":
            return subprocess.CompletedProcess(
                command, 0, stdout="hci0:\n\tname raspberrypi\n\tshort name\n", stderr=""
            )
        if "name" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Add Advertising failed with status 0x14 (Permission Denied)",
        )

    manager = BLEProvisioningManager(WiFiManager(mode="mock"))
    server = BlueZGattServer(manager, advertising_backend="btmgmt", command_runner=command_runner)
    server._adapter_path = "/org/bluez/hci0"

    with pytest.raises(BLEBackendUnavailable) as exc_info:
        asyncio.run(server._start_btmgmt_advertising())

    message = str(exc_info.value)
    assert "관리자 권한이 필요합니다" in message
    assert "sudo -E env VPC_WIFI_MODE=mock" in message
    assert "--advertising-backend btmgmt" in message
    asyncio.run(server.stop())


def test_btmgmt_cleanup_does_not_fail_when_instance_or_name_restore_fails(caplog):
    name_calls = 0

    def command_runner(command, **kwargs):
        nonlocal name_calls
        if command[-1] == "info":
            return subprocess.CompletedProcess(
                command, 0, stdout="hci0:\n\tname raspberrypi\n\tshort name rpi\n", stderr=""
            )
        if "name" in command:
            name_calls += 1
            if name_calls == 2:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="restore failed")
        if "rm-adv" in command:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="Invalid Parameters")
        return subprocess.CompletedProcess(command, 0, stdout="Instance added: 1", stderr="")

    manager = BLEProvisioningManager(WiFiManager(mode="mock"))
    server = BlueZGattServer(manager, advertising_backend="btmgmt", command_runner=command_runner)
    server._adapter_path = "/org/bluez/hci0"
    asyncio.run(server._start_btmgmt_advertising())

    with caplog.at_level(logging.ERROR):
        asyncio.run(server.stop())

    assert server._btmgmt_instance is None
    assert "restore-name failed" in caplog.text


def test_decode_configure_write_validates_json_and_size():
    payload = decode_configure_write(b'{"type":"configure_wifi","ssid":"Cafe","password":"abcdefgh"}')
    assert payload["ssid"] == "Cafe"
    with pytest.raises(ValueError, match="UTF-8 JSON"):
        decode_configure_write(b"not-json")
    with pytest.raises(ValueError, match="512"):
        decode_configure_write(b"x" * (MAX_WRITE_BYTES + 1))


def test_decode_scan_write_validates_type_and_request_id():
    assert decode_scan_write(b'{"type":"scan_wifi","request_id":"scan-001"}') == {
        "type": "scan_wifi", "request_id": "scan-001",
    }
    for payload in (
        b'{"type":"scan_wifi"}',
        b'{"type":"scan_wifi","request_id":3}',
        b'{"type":"other","request_id":"scan-001"}',
    ):
        with pytest.raises(ValueError):
            decode_scan_write(payload)


def test_scan_events_are_ordered_sorted_limited_and_compact():
    networks = [
        {"ssid": f"wifi-{index}", "signal": index, "security": "WPA2", "secured": True}
        for index in range(MAX_SCAN_NETWORKS + 5)
    ]
    networks.append({"ssid": "긴이름" * 30, "signal": 100, "security": "WPA3", "secured": True})
    events = build_scan_events("scan-001", networks)
    assert [event["t"] for event in events] == [
        "started", "begin", *(["net"] * MAX_SCAN_NETWORKS), "end",
    ]
    assert {event["r"] for event in events} == {"scan-001"}
    net_events = [event for event in events if event["t"] == "net"]
    assert [event["g"] for event in net_events] == sorted(
        [event["g"] for event in net_events], reverse=True
    )
    assert all(len(encode_json(event)) <= MAX_NOTIFY_BYTES for event in events)
    assert "password" not in str(events).lower()


class FakeScanCharacteristic:
    def __init__(self, notifying=True):
        self.notifying = notifying
        self.values = []

    def update_value(self, value):
        self.values.append(value)


class FakeStatusCharacteristic:
    def __init__(self):
        self.values = []

    def update_value(self, value):
        self.values.append(json.loads(value))


def test_network_info_read_payloads_and_port(monkeypatch):
    monkeypatch.setenv("VPC_FASTAPI_PORT", "8123")
    dry = BlueZGattServer(BLEProvisioningManager(WiFiManager(mode="dry_run"), mode="dry_run"))
    assert dry.network_info_payload() == {
        "ip": None, "host": dry.manager.wifi_manager.get_mdns_hostname(),
        "port": 8123, "interface": NETWORK_INTERFACE,
    }
    mock = BlueZGattServer(BLEProvisioningManager(WiFiManager(mode="mock"), mode="mock"))
    assert mock.network_info_payload() == {
        "ip": "192.168.0.50", "host": "visionposecoach-mock.local",
        "port": 8123, "interface": "wlan0",
    }
    assert len(encode_json(mock.network_info_payload())) <= MAX_NOTIFY_BYTES
    assert "password" not in str(mock.network_info_payload()).lower()


def test_network_info_real_uses_only_wlan0(monkeypatch):
    wifi = WiFiManager(mode="real")
    calls = []
    def fake_run(command):
        calls.append(command)
        return {"ok": True, "stdout": "10.10.141.34/24\n2001:db8::1/64\n", "message": "ok"}
    monkeypatch.setattr(wifi, "_run_nmcli", fake_run)
    monkeypatch.setattr(wifi, "get_mdns_hostname", lambda: "raspi5-009.local")
    server = BlueZGattServer(BLEProvisioningManager(wifi, mode="real"))
    assert server.network_info_payload()["ip"] == "10.10.141.34"
    assert calls == [["nmcli", "-g", "IP4.ADDRESS", "device", "show", "wlan0"]]


def test_network_info_notify_follows_connected_status():
    events = []
    class RecordingCharacteristic:
        notifying = True
        def __init__(self, kind): self.kind = kind
        def update_value(self, value): events.append((self.kind, json.loads(value)))

    async def run():
        manager = BLEProvisioningManager(WiFiManager(mode="mock"), mode="mock")
        server = BlueZGattServer(manager)
        server._status_characteristic = RecordingCharacteristic("status")
        server._network_info_characteristic = RecordingCharacteristic("network")
        await server._configure_wifi({
            "type": "configure_wifi", "client_id": "phone-001",
            "ssid": "Cafe", "password": "unit-test-secret",
        })
    asyncio.run(run())
    assert [(kind, value.get("state")) for kind, value in events] == [
        ("status", "WIFI_CONFIGURING"), ("status", "WIFI_CONNECTED"), ("network", None),
    ]
    assert events[-1][1]["ip"] == "192.168.0.50"
    assert "unit-test-secret" not in str(events)


def test_network_info_notify_disabled_is_safe():
    manager = BLEProvisioningManager(WiFiManager(mode="mock"), mode="mock")
    server = BlueZGattServer(manager)
    server._network_info_characteristic = None
    server._notify_network_info()


def test_network_info_wait_retries_without_blocking_event_loop(monkeypatch):
    manager = BLEProvisioningManager(WiFiManager(mode="real"), mode="real")
    server = BlueZGattServer(manager)
    values = iter([None, None, "10.10.141.34"])
    monkeypatch.setattr(server, "network_info_payload", lambda: {
        "ip": next(values), "host": "raspi.local", "port": 8000, "interface": "wlan0",
    })
    payload = asyncio.run(server._wait_for_interface_ipv4(attempts=5, delay_seconds=0))
    assert payload["ip"] == "10.10.141.34"


def test_network_info_wait_exhaustion_returns_null_ip(monkeypatch):
    manager = BLEProvisioningManager(WiFiManager(mode="real"), mode="real")
    server = BlueZGattServer(manager)
    monkeypatch.setattr(server, "network_info_payload", lambda: {
        "ip": None, "host": "raspi.local", "port": 8000, "interface": "wlan0",
    })
    payload = asyncio.run(server._wait_for_interface_ipv4(attempts=3, delay_seconds=0))
    assert payload["ip"] is None


def test_configure_failure_does_not_notify_stale_network_info():
    events = []
    class FailingWiFi(RecordingWiFi):
        def configure_wifi(self, ssid, password):
            return {"ok": False, "message": "connection failed"}
    class RecordingCharacteristic:
        notifying = True
        def __init__(self, kind): self.kind = kind
        def update_value(self, value): events.append((self.kind, json.loads(value)))

    async def run():
        manager = BLEProvisioningManager(FailingWiFi(), mode="mock")
        server = BlueZGattServer(manager)
        server._status_characteristic = RecordingCharacteristic("status")
        server._network_info_characteristic = RecordingCharacteristic("network")
        await server._configure_wifi({
            "type": "configure_wifi", "client_id": "phone-001",
            "ssid": "Cafe", "password": "unit-test-secret",
        })
    asyncio.run(run())
    assert [kind for kind, _ in events] == ["status", "status"]
    assert events[-1][1]["state"] == "FAILED"


def test_scan_success_notifies_once_per_event():
    manager = BLEProvisioningManager(WiFiManager(mode="mock"), mode="mock")
    server = BlueZGattServer(manager)
    characteristic = FakeScanCharacteristic()
    server._scan_characteristic = characteristic

    asyncio.run(server._scan_wifi("scan-001"))

    decoded = [__import__("json").loads(value) for value in characteristic.values]
    assert [item["t"] for item in decoded] == ["started", "begin", "net", "net", "net", "end"]
    assert {item["r"] for item in decoded} == {"scan-001"}


def test_scan_busy_and_notify_disabled_are_safe(caplog):
    manager = BLEProvisioningManager(WiFiManager(mode="mock"), mode="mock")
    server = BlueZGattServer(manager)
    characteristic = FakeScanCharacteristic(notifying=True)
    server._scan_characteristic = characteristic

    class RunningTask:
        def done(self): return False

    server._scan_task = RunningTask()
    server._on_scan_write(b'{"type":"scan_wifi","request_id":"scan-002"}')
    assert __import__("json").loads(characteristic.values[-1]) == {
        "t": "error", "r": "scan-002", "c": "scan_busy",
    }

    characteristic.notifying = False
    with caplog.at_level(logging.WARNING):
        server._on_scan_write(b'{"type":"scan_wifi","request_id":"scan-003"}')
    assert server._scan_state == {"t": "error", "r": "scan-003", "c": "notify_required"}
    assert "Notify is not enabled" in caplog.text


def test_gatt_configure_calls_injected_wifi_manager_and_hides_password():
    wifi = RecordingWiFi()
    manager = BLEProvisioningManager(wifi, mode="mock")
    secret = "unit-test-secret"
    result = manager.handle_gatt_configure({
        "type": "configure_wifi", "client_id": "phone-001", "ssid": "Cafe", "password": secret,
    })
    status = BlueZGattServer(manager).status_payload()
    assert result["ok"] is True
    assert wifi.calls == [("Cafe", "***")]
    assert status["state"] == "WIFI_CONNECTED"
    assert secret not in str(result)
    assert secret not in str(status)


def test_dry_run_accepts_configure_without_claiming_wifi_connected():
    manager = BLEProvisioningManager(WiFiManager(mode="dry_run"), mode="dry_run")
    result = manager.handle_gatt_configure({
        "type": "configure_wifi", "client_id": "phone-001", "ssid": "Cafe", "password": "abcdefgh",
    })
    status = BlueZGattServer(manager).status_payload()
    assert result["ok"] is True
    assert status["state"] == "WIFI_CONNECTED"
    assert status["wifi_connected"] is False
    assert "password" not in status


def test_docs_distinguish_http_mock_and_read_only_hello():
    gatt_spec = (ROOT / "BLE_GATT_SPEC.md").read_text(encoding="utf-8")
    app_spec = (ROOT / "APP_API_SPEC.md").read_text(encoding="utf-8")
    server_readme = (ROOT / "SERVER_README.md").read_text(encoding="utf-8")
    assert "Hello / Device Info is read-only" in gatt_spec
    assert "HTTP mock" in app_spec
    assert "does not mirror the live GATT process state" in server_readme


@pytest.mark.parametrize("payload,error_code", [
    ({"type": "wat", "ssid": "Cafe", "password": "abcdefgh"}, "INVALID_MESSAGE_TYPE"),
    ({"type": "configure_wifi", "client_id": "phone-001", "ssid": "", "password": "abcdefgh"}, "INVALID_WIFI_PAYLOAD"),
])
def test_invalid_gatt_payload_is_rejected_without_wifi_call(payload, error_code):
    wifi = RecordingWiFi()
    manager = BLEProvisioningManager(wifi, mode="mock")
    result = manager.handle_gatt_configure(payload)
    assert result["ok"] is False
    assert result["error_code"] == error_code
    assert wifi.calls == []


@pytest.mark.parametrize("succeeds,expected", [(True, "WIFI_CONNECTED"), (False, "FAILED")])
def test_gatt_configure_notifies_configuring_before_terminal_state(succeeds, expected):
    started = threading.Event()
    release = threading.Event()

    class BlockingWiFi(RecordingWiFi):
        def configure_wifi(self, ssid, password):
            self.calls.append((ssid, "***"))
            started.set()
            release.wait(timeout=2)
            if succeeds:
                return super(RecordingWiFi, self).configure_wifi(ssid, password)
            return {"ok": False, "message": "connection failed"}

    async def run():
        manager = BLEProvisioningManager(BlockingWiFi(), mode="mock")
        server = BlueZGattServer(manager)
        characteristic = FakeStatusCharacteristic()
        server._status_characteristic = characteristic
        task = asyncio.create_task(server._configure_wifi({
            "type": "configure_wifi", "client_id": "phone-001",
            "ssid": "Cafe", "password": "unit-test-secret",
        }))
        await asyncio.to_thread(started.wait, 2)
        assert [item["state"] for item in characteristic.values] == ["WIFI_CONFIGURING"]
        assert not task.done()
        release.set()
        await task
        assert [item["state"] for item in characteristic.values] == ["WIFI_CONFIGURING", expected]

    asyncio.run(run())


def test_invalid_payload_does_not_notify_configuring():
    manager = BLEProvisioningManager(RecordingWiFi(), mode="mock")
    server = BlueZGattServer(manager)
    characteristic = FakeStatusCharacteristic()
    server._status_characteristic = characteristic
    asyncio.run(server._configure_wifi({
        "type": "configure_wifi", "client_id": "phone-001", "ssid": "", "password": "secret123",
    }))
    assert [item["state"] for item in characteristic.values] == ["FAILED"]


def test_duplicate_configure_is_rejected_without_second_wifi_call():
    started = threading.Event()
    release = threading.Event()

    class BlockingWiFi(RecordingWiFi):
        def configure_wifi(self, ssid, password):
            self.calls.append((ssid, "***"))
            started.set()
            release.wait(timeout=2)
            return {"ok": True, "message": "ok"}

    async def run():
        wifi = BlockingWiFi()
        manager = BLEProvisioningManager(wifi, mode="mock")
        server = BlueZGattServer(manager)
        server._status_characteristic = FakeStatusCharacteristic()
        payload = {"type": "configure_wifi", "client_id": "phone-001", "ssid": "Cafe", "password": "secret123"}
        first = asyncio.create_task(server._configure_wifi(payload.copy()))
        await asyncio.to_thread(started.wait, 2)
        busy = manager.prepare_gatt_configure(payload.copy())
        assert busy["error_code"] == "WIFI_CONFIG_BUSY"
        assert wifi.calls == [("Cafe", "***")]
        release.set()
        await first
        assert wifi.calls == [("Cafe", "***")]
        assert "secret123" not in str(busy)

    asyncio.run(run())


def test_configure_failure_sanitizes_password_from_result_and_status():
    secret = "unit-test-secret"

    class EchoingFailureWiFi(RecordingWiFi):
        def configure_wifi(self, ssid, password):
            self.calls.append((ssid, "***"))
            return {"ok": False, "message": f"nmcli rejected password={password}"}

    manager = BLEProvisioningManager(EchoingFailureWiFi(), mode="real")
    result = manager.handle_gatt_configure({
        "type": "configure_wifi", "client_id": "phone-001", "ssid": "Cafe", "password": secret,
    })
    status = BlueZGattServer(manager).status_payload()

    assert result["error_code"] == "WIFI_CONFIGURE_FAILED"
    assert secret not in str(result)
    assert secret not in str(status)
    assert secret not in str(manager.get_status())


@pytest.mark.parametrize("mode", ["mock", "dry_run", "real"])
def test_staged_configure_preserves_manager_mode_structure(mode):
    wifi = RecordingWiFi()
    manager = BLEProvisioningManager(wifi, mode=mode)
    result = manager.handle_gatt_configure({
        "type": "configure_wifi", "client_id": "phone-001", "ssid": "Cafe", "password": "secret123",
    })
    assert result["ok"] is True
    assert manager.mode == mode
    assert wifi.calls == [("Cafe", "***")]
