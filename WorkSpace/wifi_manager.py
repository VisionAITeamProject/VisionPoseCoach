"""
LEGACY / EXPERIMENTAL FILE

이 파일은 현재 FastAPI 서버에서 사용하지 않습니다.
현재 서버에서 사용하는 WiFiManager는 network/wifi_manager.py입니다.

주의:
이 파일에는 실제 OS WiFi 설정을 변경할 수 있는 nmcli 기반 코드가 포함되어 있습니다.
현재 개발 서버와 앱 연동 구조에서는 import하거나 실행하지 마세요.

실제 Raspberry Pi WiFi 연결 구현이 필요할 경우,
network/wifi_manager.py의 dry-run 구조를 기반으로 별도 real mode를 안전하게 확장하세요.
"""

import subprocess


def run_command(command: list[str]) -> tuple[bool, str, str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    success = result.returncode == 0
    return success, result.stdout, result.stderr


def scan_wifi():
    """
    주변 Wi-Fi 목록 조회
    """
    success, stdout, stderr = run_command([
        "nmcli",
        "-t",
        "-f",
        "SSID,SIGNAL,SECURITY",
        "device",
        "wifi",
        "list"
    ])

    if not success:
        return {
            "success": False,
            "message": "Wi-Fi 목록 조회 실패",
            "error": stderr,
            "networks": []
        }

    networks = []
    seen_ssids = set()

    for line in stdout.splitlines():
        if not line.strip():
            continue

        parts = line.split(":")
        if len(parts) < 3:
            continue

        ssid = parts[0].strip()
        signal = parts[1].strip()
        security = parts[2].strip()

        if not ssid:
            continue

        if ssid in seen_ssids:
            continue

        seen_ssids.add(ssid)

        networks.append({
            "ssid": ssid,
            "signal": signal,
            "security": security
        })

    return {
        "success": True,
        "networks": networks
    }


def connect_wifi(ssid: str, password: str):
    """
    Wi-Fi 연결
    """
    command = [
        "sudo",
        "nmcli",
        "device",
        "wifi",
        "connect",
        ssid,
        "password",
        password
    ]

    success, stdout, stderr = run_command(command)

    if success:
        return {
            "success": True,
            "message": "Wi-Fi 연결 성공",
            "stdout": stdout
        }

    return {
        "success": False,
        "message": "Wi-Fi 연결 실패",
        "stderr": stderr
    }


def get_wifi_status():
    """
    현재 Wi-Fi 연결 상태 확인
    """
    success, stdout, stderr = run_command([
        "nmcli",
        "-t",
        "-f",
        "ACTIVE,SSID,SIGNAL",
        "device",
        "wifi"
    ])

    if not success:
        return {
            "success": False,
            "message": "Wi-Fi 상태 조회 실패",
            "error": stderr
        }

    active_wifi = None

    for line in stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue

        active = parts[0]
        ssid = parts[1]
        signal = parts[2]

        if active == "yes":
            active_wifi = {
                "ssid": ssid,
                "signal": signal
            }
            break

    return {
        "success": True,
        "connected": active_wifi is not None,
        "wifi": active_wifi
    }


if __name__ == "__main__":
    print("This is a legacy experimental WiFi manager. Use network/wifi_manager.py instead.")
    raise SystemExit(1)
