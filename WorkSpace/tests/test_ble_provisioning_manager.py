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


def make_manager():
    wifi_manager = WiFiManager()
    return BLEProvisioningManager(wifi_manager), wifi_manager


def test_ble_initial_status():
    manager, _ = make_manager()

    status = manager.get_status()

    assert status["mode"] == "dry_run"
    assert status["available"] is False
    assert status["implementation"] == "http_mock"
    assert status["transport"] == "http"
    assert status["mock_available"] is True
    assert status["real_ble"] is False
    assert status["gatt_available"] is False
    assert status["advertising"] is False
    assert status["device_name"] == "VisionPoseCoach-Pi"
    assert status["pairing_code"] == "123456"
    assert status["provisioning_state"] == "NOT_STARTED"
    assert status["provisioning_completed"] is False


def test_start_and_stop_advertising():
    manager, _ = make_manager()

    started = manager.start_advertising()
    stopped = manager.stop_advertising()

    assert started["ok"] is True
    assert started["ble"]["advertising"] is True
    assert started["ble"]["provisioning_state"] == "ADVERTISING"
    assert started["next_step"] == "WAIT_FOR_APP"
    assert stopped["ok"] is True
    assert stopped["ble"]["advertising"] is False


def test_hello_message():
    manager, _ = make_manager()

    response = manager.handle_provisioning_message(
        {"type": "hello", "client_id": "phone-001", "app_version": "0.1.0"}
    )

    assert response["type"] == "ble_provisioning_response"
    assert response["ok"] is True
    assert response["message_type"] == "hello"
    assert response["device_name"] == "VisionPoseCoach-Pi"
    assert response["pairing_code"] == "123456"
    assert response["provisioning_state"] == "CLIENT_CONNECTED"
    assert response["next_step"] == "SEND_WIFI_CONFIG"


def test_configure_wifi_updates_wifi_manager_without_password():
    manager, wifi_manager = make_manager()

    response = manager.handle_provisioning_message(
        {
            "type": "configure_wifi",
            "client_id": "phone-001",
            "ssid": "MyWifi",
            "password": "mypassword123",
        }
    )

    assert response["ok"] is True
    assert response["message_type"] == "configure_wifi"
    assert response["provisioning_state"] == "COMPLETED"
    assert response["provisioning_completed"] is True
    assert response["next_step"] == "CHECK_NETWORK_STATUS"
    assert response["wifi"]["last_configured_ssid"] == "MyWifi"
    assert wifi_manager.get_status()["last_configured_ssid"] == "MyWifi"
    assert manager.get_status()["provisioning_completed"] is True
    assert not contains_key(response, "password")
    assert not contains_key(manager.get_status(), "password")


def test_status_message_includes_ble_and_wifi():
    manager, _ = make_manager()

    response = manager.handle_provisioning_message({"type": "status", "client_id": "phone-001"})

    assert response["ok"] is True
    assert response["message_type"] == "status"
    assert response["next_step"] == "START_BLE_ADVERTISING"
    assert "ble" in response
    assert "wifi" in response
    assert not contains_key(response, "password")


def test_reset_clears_provisioning_completed():
    manager, _ = make_manager()
    manager.handle_provisioning_message(
        {
            "type": "configure_wifi",
            "client_id": "phone-001",
            "ssid": "MyWifi",
            "password": "mypassword123",
        }
    )

    response = manager.handle_provisioning_message({"type": "reset", "client_id": "phone-001"})

    assert response["ok"] is True
    assert response["provisioning_state"] == "NOT_STARTED"
    assert response["next_step"] == "START_BLE_ADVERTISING"
    assert manager.get_status()["provisioning_completed"] is False


def test_unknown_message_returns_error():
    manager, _ = make_manager()

    response = manager.handle_provisioning_message({"type": "wat", "client_id": "phone-001"})

    assert response["ok"] is False
    assert response["provisioning_state"] == "ERROR"
    assert response["next_step"] == "ERROR"
    assert response["error_code"] == "UNKNOWN_PROVISIONING_MESSAGE"


def test_registration_status_includes_ble_wifi_and_next_step():
    manager, _ = make_manager()
    manager.start_advertising()

    response = manager.get_registration_status()

    assert response["type"] == "provisioning_status"
    assert response["provisioning_state"] == "ADVERTISING"
    assert response["next_step"] == "WAIT_FOR_APP"
    assert "ble" in response
    assert "wifi" in response
    assert response["ble"]["implementation"] == "http_mock"
    assert response["ble"]["real_ble"] is False
    assert response["ble"]["gatt_available"] is False
    assert not contains_key(response, "password")


def test_ble_manager_status_identifies_http_mock_not_real_ble():
    manager, _ = make_manager()

    status = manager.get_status()
    registration = manager.get_registration_status()

    assert status["implementation"] == "http_mock"
    assert status["real_ble"] is False
    assert status["gatt_available"] is False
    assert registration["ble"]["implementation"] == "http_mock"
    assert registration["ble"]["real_ble"] is False
    assert registration["ble"]["gatt_available"] is False


def test_health_contract_includes_ble_app_fields():
    source = (ROOT / "network" / "api_server.py").read_text(encoding="utf-8")

    assert '@app.get("/provisioning/status")' in source
    assert '"provisioning_state": provisioning_status.get("provisioning_state")' in source
    assert '"ble_available": bool(provisioning_status.get("available"))' in source
    assert '"ble_advertising": bool(provisioning_status.get("advertising"))' in source
    assert '"provisioning": provisioning_status' in source
