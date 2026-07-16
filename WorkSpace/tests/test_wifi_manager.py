import sys
from types import SimpleNamespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.wifi_manager import WiFiManager


def test_interface_ipv4_removes_cidr_skips_ipv6_and_uses_requested_interface(monkeypatch):
    manager = WiFiManager(mode="real")
    calls = []
    def fake_run(command):
        calls.append(command)
        return {"ok": True, "stdout": "2001:db8::1/64\n10.10.141.148/24\n10.10.141.150/24\n", "message": "ok"}
    monkeypatch.setattr(manager, "_run_nmcli", fake_run)
    assert manager.get_interface_ipv4("wlan0") == "10.10.141.148"
    assert calls == [["nmcli", "-g", "IP4.ADDRESS", "device", "show", "wlan0"]]


def test_interface_ipv4_failure_and_empty_output_return_none(monkeypatch):
    manager = WiFiManager(mode="real")
    monkeypatch.setattr(manager, "_run_nmcli", lambda command: {"ok": False, "stdout": "", "message": "failed"})
    assert manager.get_interface_ipv4() is None
    monkeypatch.setattr(manager, "_run_nmcli", lambda command: {"ok": True, "stdout": "", "message": "ok"})
    assert manager.get_interface_ipv4() is None


def test_mdns_hostname_suffix_is_added_once(monkeypatch):
    manager = WiFiManager(mode="dry_run")
    monkeypatch.setattr(manager, "_get_hostname", lambda: "raspi5-009")
    assert manager.get_mdns_hostname() == "raspi5-009.local"
    monkeypatch.setattr(manager, "_get_hostname", lambda: "raspi5-009.local")
    assert manager.get_mdns_hostname() == "raspi5-009.local"


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


def test_mock_mode_returns_fake_networks_and_connects():
    manager = WiFiManager(mode="mock")

    scan = manager.list_networks()
    result = manager.configure_wifi("MyWifi", "mypassword123")
    status = manager.get_status()

    assert scan["ok"] is True
    assert scan["mode"] == "mock"
    assert scan["networks"]
    assert result["ok"] is True
    assert result["connected"] is True
    assert status["connected"] is True
    assert status["ssid"] == "MyWifi"
    assert not contains_key(scan, "password")
    assert not contains_key(result, "password")


def test_real_scan_parses_nmcli_output_without_running_shell(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="Cafe:88:WPA2\nCafe:45:WPA1 WPA2\nOpenNet:30:\n:99:WPA2\n",
            stderr="",
        )

    monkeypatch.setattr("network.wifi_manager.subprocess.run", fake_run)
    manager = WiFiManager(mode="real")

    scan = manager.list_networks()

    assert scan["ok"] is True
    assert scan["mode"] == "real"
    assert scan["networks"] == [
        {"ssid": "Cafe", "signal": 88, "security": "WPA2", "secured": True},
        {"ssid": "OpenNet", "signal": 30, "security": "", "secured": False},
    ]
    assert calls[0][0] == [
        "nmcli",
        "-t",
        "-f",
        "SSID,SIGNAL,SECURITY",
        "device",
        "wifi",
        "list",
        "--rescan",
        "yes",
    ]
    assert calls[0][1]["shell"] is False


def test_real_scan_parses_nmcli_escaped_colon_ssid(monkeypatch):
    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="Cafe\\:Main:77:WPA2\nStudio\\\\AP:50:--\n",
            stderr="",
        )

    monkeypatch.setattr("network.wifi_manager.subprocess.run", fake_run)
    manager = WiFiManager(mode="real")

    scan = manager.list_networks()

    assert scan["ok"] is True
    assert scan["networks"] == [
        {"ssid": "Cafe:Main", "signal": 77, "security": "WPA2", "secured": True},
        {"ssid": "Studio\\AP", "signal": 50, "security": "--", "secured": False},
    ]


def test_real_configure_sanitizes_nmcli_failure(monkeypatch):
    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=10,
            stdout="",
            stderr="failed to connect with password supersecret",
        )

    monkeypatch.setattr("network.wifi_manager.subprocess.run", fake_run)
    manager = WiFiManager(mode="real")

    result = manager.configure_wifi("MyWifi", "supersecret")

    assert result["ok"] is False
    assert result["connected"] is False
    assert "supersecret" not in str(result)
    assert result["message"] == "failed to connect with password ***"
    assert not contains_key(result, "password")


def test_real_scan_returns_friendly_nmcli_missing_error(monkeypatch):
    def fake_run(command, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("network.wifi_manager.subprocess.run", fake_run)
    manager = WiFiManager(mode="real")

    scan = manager.list_networks()

    assert scan["ok"] is False
    assert scan["networks"] == []
    assert "nmcli" in scan["message"]


def test_missing_ssid_validation_error():
    manager = WiFiManager()

    result = manager.configure_wifi("", "mypassword123")

    assert result["ok"] is False
    assert result["message"] == "SSID가 올바르지 않습니다."
    assert not contains_key(result, "password")


def test_health_contract_includes_network_app_fields():
    source = (ROOT / "network" / "api_server.py").read_text(encoding="utf-8")

    assert '"network_ready": network_ready' in source
    assert '"wifi_connected": bool(network_status.get("connected"))' in source
    assert '"provisioning_required": bool(network_status.get("provisioning_required"))' in source
    assert '"network": network_status' in source
