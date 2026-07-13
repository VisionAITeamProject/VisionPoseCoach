import asyncio
import importlib
import logging
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.ble_gatt_server import (
    ADVERTISE_NAME, DEVICE_NAME, HELLO_FLAGS, MAX_WRITE_BYTES, SERVICE_UUID,
    BLEBackendUnavailable, BlueZGattServer, advertisement_properties,
    btmgmt_add_command, btmgmt_remove_command, decode_configure_write,
    hello_payload,
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
    assert module.SERVICE_UUID == SERVICE_UUID
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
        "btmgmt", "-i", "hci0", "add-adv", "-c", "-g",
        "-u", SERVICE_UUID, "1",
    ]
    assert btmgmt_remove_command("hci0", 1) == [
        "btmgmt", "-i", "hci0", "rm-adv", "1",
    ]


def test_btmgmt_backend_stores_and_removes_advertising_instance():
    calls = []

    def command_runner(command, **kwargs):
        calls.append((command, kwargs))
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

    assert calls[0][0] == btmgmt_add_command("hci0", 1)
    assert calls[1][0] == btmgmt_remove_command("hci0", 1)
    assert calls[0][1]["shell"] is False
    assert server._btmgmt_instance is None


def test_auto_backend_falls_back_to_btmgmt_on_bluez_failed():
    class FakeDBusError(Exception):
        type = "org.bluez.Error.Failed"
        text = "Failed to register advertisement"

    def command_runner(command, **kwargs):
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


def test_decode_configure_write_validates_json_and_size():
    payload = decode_configure_write(b'{"type":"configure_wifi","ssid":"Cafe","password":"abcdefgh"}')
    assert payload["ssid"] == "Cafe"
    with pytest.raises(ValueError, match="UTF-8 JSON"):
        decode_configure_write(b"not-json")
    with pytest.raises(ValueError, match="512"):
        decode_configure_write(b"x" * (MAX_WRITE_BYTES + 1))


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
        "type": "configure_wifi", "ssid": "Cafe", "password": "abcdefgh",
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
    ({"type": "configure_wifi", "ssid": "", "password": "abcdefgh"}, "INVALID_WIFI_PAYLOAD"),
])
def test_invalid_gatt_payload_is_rejected_without_wifi_call(payload, error_code):
    wifi = RecordingWiFi()
    manager = BLEProvisioningManager(wifi, mode="mock")
    result = manager.handle_gatt_configure(payload)
    assert result["ok"] is False
    assert result["error_code"] == error_code
    assert wifi.calls == []
