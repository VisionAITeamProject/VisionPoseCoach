import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.wifi_manager import WiFiManager


def contains_key(payload, target_key):
    if isinstance(payload, dict):
        return any(key == target_key or contains_key(value, target_key) for key, value in payload.items())
    if isinstance(payload, list):
        return any(contains_key(item, target_key) for item in payload)
    return False


def test_wifi_manager_initial_status():
    manager = WiFiManager()

    status = manager.get_status()

    assert status["type"] == "wifi_status"
    assert status["mode"] == "dry_run"
    assert status["connected"] is False
    assert status["ssid"] is None
    assert status["provisioning_required"] is True
    assert status["last_configured_ssid"] is None
    assert "password" not in status


def test_configure_wifi_stores_ssid_without_password():
    manager = WiFiManager()

    result = manager.configure_wifi("MyWifi", "mypassword123")
    status = manager.get_status()

    assert result["ok"] is True
    assert result["ssid"] == "MyWifi"
    assert status["last_configured_ssid"] == "MyWifi"
    assert not contains_key(result, "password")
    assert not contains_key(status, "password")


def test_forget_wifi_clears_last_configured_ssid():
    manager = WiFiManager()
    manager.configure_wifi("MyWifi", "mypassword123")

    result = manager.forget_wifi()
    status = manager.get_status()

    assert result["ok"] is True
    assert status["last_configured_ssid"] is None
    assert status["ssid"] is None
    assert status["connected"] is False


def test_mask_sensitive_data_masks_password_recursively():
    manager = WiFiManager()

    masked = manager.mask_sensitive_data(
        {
            "ssid": "MyWifi",
            "password": "mypassword123",
            "nested": {"psk": "secret"},
        }
    )

    assert masked["password"] == "***"
    assert masked["nested"]["psk"] == "***"


def test_health_contract_includes_network_app_fields():
    source = (ROOT / "network" / "api_server.py").read_text(encoding="utf-8")

    assert '"network_ready": network_ready' in source
    assert '"wifi_connected": bool(network_status.get("connected"))' in source
    assert '"provisioning_required": bool(network_status.get("provisioning_required"))' in source
    assert '"network": network_status' in source
