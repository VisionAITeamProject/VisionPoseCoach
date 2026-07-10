import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.ble_gatt_server import (
    DEVICE_NAME, HELLO_FLAGS, MAX_WRITE_BYTES, SERVICE_UUID, BlueZGattServer,
    decode_configure_write,
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
