import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.ble_provisioning_manager import BLEProvisioningManager
from network.wifi_manager import WiFiManager


def contains_key(payload, target_key):
    if isinstance(payload, dict):
        return any(key == target_key or contains_key(value, target_key) for key, value in payload.items())
    if isinstance(payload, list):
        return any(contains_key(item, target_key) for item in payload)
    return False


def main():
    wifi_manager = WiFiManager()
    manager = BLEProvisioningManager(wifi_manager)

    status = manager.get_status()
    assert status["mode"] == "dry_run"
    assert status["available"] is False
    assert status["implementation"] == "http_mock"
    assert status["real_ble"] is False
    assert status["gatt_available"] is False
    assert status["advertising"] is False
    assert status["provisioning_state"] == "NOT_STARTED"

    started = manager.start_advertising()
    assert started["ble"]["advertising"] is True
    assert started["ble"]["provisioning_state"] == "ADVERTISING"
    assert started["next_step"] == "WAIT_FOR_APP"
    assert manager.stop_advertising()["ble"]["advertising"] is False

    hello = manager.handle_provisioning_message(
        {"type": "hello", "client_id": "phone-001", "app_version": "0.1.0"}
    )
    assert hello["ok"] is True
    assert hello["message_type"] == "hello"
    assert hello["pairing_code"] == "123456"
    assert hello["provisioning_state"] == "CLIENT_CONNECTED"
    assert hello["next_step"] == "SEND_WIFI_CONFIG"

    configured = manager.handle_provisioning_message(
        {
            "type": "configure_wifi",
            "client_id": "phone-001",
            "ssid": "MyWifi",
            "password": "mypassword123",
        }
    )
    assert configured["ok"] is True
    assert configured["provisioning_state"] == "COMPLETED"
    assert configured["provisioning_completed"] is True
    assert configured["next_step"] == "CHECK_NETWORK_STATUS"
    assert configured["wifi"]["last_configured_ssid"] == "MyWifi"
    assert wifi_manager.get_status()["last_configured_ssid"] == "MyWifi"
    assert not contains_key(configured, "password")

    registration_status = manager.get_registration_status()
    assert registration_status["type"] == "provisioning_status"
    assert registration_status["provisioning_state"] == "COMPLETED"
    assert registration_status["next_step"] == "CHECK_NETWORK_STATUS"
    assert "ble" in registration_status
    assert "wifi" in registration_status
    assert not contains_key(registration_status, "password")

    provisioning_status = manager.handle_provisioning_message({"type": "status", "client_id": "phone-001"})
    assert provisioning_status["next_step"] == "CHECK_NETWORK_STATUS"
    assert "ble" in provisioning_status
    assert "wifi" in provisioning_status
    assert not contains_key(provisioning_status, "password")

    unknown = manager.handle_provisioning_message({"type": "unknown", "client_id": "phone-001"})
    assert unknown["ok"] is False
    assert unknown["provisioning_state"] == "ERROR"
    assert unknown["next_step"] == "ERROR"
    assert unknown["error_code"] == "UNKNOWN_PROVISIONING_MESSAGE"

    reset = manager.handle_provisioning_message({"type": "reset", "client_id": "phone-001"})
    assert reset["ok"] is True
    assert reset["provisioning_state"] == "NOT_STARTED"
    assert reset["next_step"] == "START_BLE_ADVERTISING"
    assert manager.get_status()["provisioning_completed"] is False

    source = (ROOT / "network" / "api_server.py").read_text(encoding="utf-8")
    assert '@app.get("/provisioning/status")' in source
    assert '"provisioning_state": provisioning_status.get("provisioning_state")' in source
    assert '"ble_available": bool(provisioning_status.get("available"))' in source
    assert '"ble_advertising": bool(provisioning_status.get("advertising"))' in source
    assert '"provisioning": provisioning_status' in source

    print("ble_provisioning_ok")


if __name__ == "__main__":
    main()
