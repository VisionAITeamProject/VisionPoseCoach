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


def main():
    manager = WiFiManager()
    status = manager.get_status()
    assert status["type"] == "wifi_status"
    assert status["mode"] == "dry_run"
    assert status["provisioning_required"] is True
    assert not contains_key(status, "password")

    configured = manager.configure_wifi("MyWifi", "mypassword123")
    assert configured["ok"] is True
    assert configured["ssid"] == "MyWifi"
    assert not contains_key(configured, "password")
    assert manager.get_status()["last_configured_ssid"] == "MyWifi"

    network_status = manager.get_network_status()
    assert network_status["type"] == "network_status"
    assert not contains_key(network_status, "password")

    source = (ROOT / "network" / "api_server.py").read_text(encoding="utf-8")
    assert '"network_ready": network_ready' in source
    assert '"wifi_connected": bool(network_status.get("connected"))' in source
    assert '"provisioning_required": bool(network_status.get("provisioning_required"))' in source
    assert '"network": network_status' in source

    forgotten = manager.forget_wifi()
    assert forgotten["ok"] is True
    assert manager.get_status()["last_configured_ssid"] is None

    print("wifi_manager_ok")


if __name__ == "__main__":
    main()
