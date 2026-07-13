#!/usr/bin/env python3
"""Run the real VisionPoseCoach BlueZ GATT provisioning peripheral."""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.ble_gatt_server import ADVERTISE_NAME, BLEBackendUnavailable, BlueZGattServer, DEVICE_NAME
from network.ble_provisioning_manager import BLEProvisioningManager
from network.wifi_manager import WiFiManager


async def run(args):
    wifi = WiFiManager(mode=args.wifi_mode)
    manager = BLEProvisioningManager(wifi, mode=wifi.mode, device_name=args.device_name)
    server = BlueZGattServer(
        manager,
        device_name=args.device_name,
        advertise_name=args.advertise_name,
    )
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass
    await server.start()
    advertised_name = args.advertise_name if server.local_name_included else "<omitted; Service UUID only>"
    print(
        f"BLE advertising: {advertised_name} "
        f"(device name: {args.device_name}, WiFi mode: {wifi.mode})"
    )
    try:
        await stop_event.wait()
    finally:
        await server.stop()


def main():
    parser = argparse.ArgumentParser(description="VisionPoseCoach real BlueZ BLE GATT server")
    parser.add_argument("--device-name", default=DEVICE_NAME)
    parser.add_argument("--advertise-name", default=ADVERTISE_NAME)
    parser.add_argument("--wifi-mode", choices=sorted(WiFiManager.VALID_MODES), default=os.getenv("VPC_WIFI_MODE", "dry_run"))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(args))
    except BLEBackendUnavailable as exc:
        print(f"BLE server unavailable: {exc}", file=sys.stderr)
        return 2
    except (PermissionError, OSError) as exc:
        print(f"BLE server failed: BlueZ D-Bus 권한과 bluetooth.service 상태를 확인하세요 ({type(exc).__name__}).", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
