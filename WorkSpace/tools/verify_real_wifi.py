import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from network.wifi_manager import WiFiManager


def mask_secret(text, secret):
    if not isinstance(text, str):
        return text
    if isinstance(secret, str) and secret:
        return text.replace(secret, "***")
    return text


def print_status(status):
    print("WiFi status:")
    print(f"  mode: {status.get('mode')}")
    print(f"  connected: {status.get('connected')}")
    print(f"  ssid: {status.get('ssid')}")
    print(f"  local_ip: {status.get('local_ip')}")
    print(f"  hostname: {status.get('hostname')}")
    print(f"  provisioning_required: {status.get('provisioning_required')}")
    if status.get("last_error"):
        print(f"  last_error: {status.get('last_error')}")


def print_networks(scan, limit):
    print("WiFi scan:")
    print(f"  ok: {scan.get('ok')}")
    print(f"  mode: {scan.get('mode')}")
    if scan.get("message"):
        print(f"  message: {scan.get('message')}")

    networks = scan.get("networks") or []
    if not networks:
        print("  networks: none")
        return

    print(f"  networks: showing {min(len(networks), limit)} of {len(networks)}")
    for network in networks[:limit]:
        security = network.get("security") or "open"
        print(
            f"  - ssid={network.get('ssid')} "
            f"signal={network.get('signal')} "
            f"security={security} "
            f"secured={network.get('secured')}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Verify VisionPoseCoach real WiFi mode on Raspberry Pi without exposing passwords."
    )
    parser.add_argument("--connect", action="store_true", help="Attempt WiFi connection. Disabled by default.")
    parser.add_argument("--ssid", help="SSID to connect when --connect is set.")
    parser.add_argument("--password", help="WiFi password to connect when --connect is set.")
    parser.add_argument("--limit", type=int, default=8, help="Number of scanned networks to print.")
    args = parser.parse_args()

    env_mode = os.getenv("VPC_WIFI_MODE", "dry_run")
    print(f"VPC_WIFI_MODE: {env_mode}")
    print("Creating WiFiManager(mode='real') for Raspberry Pi nmcli verification.")

    manager = WiFiManager(mode="real")
    status = manager.get_status()
    print_status(status)

    scan = manager.list_networks()
    print_networks(scan, max(args.limit, 0))

    if not scan.get("ok") and "nmcli" in str(scan.get("message", "")).lower():
        print(
            "Hint: nmcli was not available or failed. On Raspberry Pi OS, install and enable "
            "NetworkManager before running real WiFi mode."
        )

    if not args.connect:
        print("Connection attempt skipped. Use --connect --ssid ... --password ... to connect.")
        return 0

    if not args.ssid or args.password is None:
        parser.error("--connect requires --ssid and --password")

    print(f"Attempting WiFi connection to SSID: {args.ssid}")
    result = manager.configure_wifi(args.ssid, args.password)
    safe_message = mask_secret(str(result.get("message", "")), args.password)

    print("WiFi configure result:")
    print(f"  ok: {result.get('ok')}")
    print(f"  mode: {result.get('mode')}")
    print(f"  ssid: {result.get('ssid')}")
    print(f"  connected: {result.get('connected')}")
    print(f"  message: {safe_message}")

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
