"""Bluetooth gateway: read standard BLE health devices and print one JSON line per reading.

    pip install -r scripts/requirements-ble.txt
    python scripts/ble_gateway.py --scan                         (list nearby health devices)
    python scripts/ble_gateway.py | python scripts/device_client.py stream --source stdin
    python scripts/ble_gateway.py --address AA:BB:CC:DD:EE:FF --address 11:22:33:44:55:66 | ...

Works with any device that implements the standard Bluetooth SIG services: Heart Rate, Pulse Oximeter, Blood Pressure,
Health Thermometer (see ble_health.py). Devices that only talk to their maker's phone app cannot be read.
This program only reads sensors; sealing (Diffie-Hellman + AES-256-GCM) and signing (RSA-PSS over SHA-512) happen in
device_client.py, which receives these lines on standard input. Logs go to standard error, readings to standard output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import ble_health


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit(reading: dict[str, float]) -> None:
    print(json.dumps(reading, separators=(",", ":")), flush=True)


async def scan(seconds: float) -> list:
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    devices = []
    for device, adv in found.values():
        kinds = [ble_health.SERVICES[u] for u in adv.service_uuids if u in ble_health.SERVICES]
        if kinds:
            devices.append((device, kinds))
            log(f"  {device.address}  {device.name or '(no name)'}  {', '.join(kinds)}")
    if not devices:
        log("  no standard health devices found (is the device on, nearby, and not connected to a phone?)")
    return devices


async def follow(address: str, combiner: ble_health.Combiner, stop: asyncio.Event) -> None:
    """Connect, subscribe to every supported measurement, and reconnect if the device drops."""
    from bleak import BleakClient
    from bleak.exc import BleakError

    while not stop.is_set():
        try:
            async with BleakClient(address) as client:
                subscribed = 0
                for service in client.services:
                    for ch in service.characteristics:
                        parser = ble_health.PARSERS.get(ch.uuid)
                        if parser and ({"notify", "indicate"} & set(ch.properties)):
                            def handler(_sender, data: bytearray, parser=parser) -> None:
                                values = parser(bytes(data))
                                if values:
                                    combiner.add(values, time.monotonic())
                            await client.start_notify(ch.uuid, handler)
                            subscribed += 1
                log(f"{address}: connected, {subscribed} measurement(s) subscribed")
                while client.is_connected and not stop.is_set():
                    await asyncio.sleep(1)
                log(f"{address}: disconnected")
        except (BleakError, OSError, TimeoutError) as exc:
            log(f"{address}: {exc}; retrying in 10 s")
        await asyncio.sleep(10)


async def run(addresses: list[str], window: float) -> None:
    if not addresses:
        log("Scanning for 10 s ...")
        addresses = [d.address for d, _ in await scan(10)]
        if not addresses:
            return
    combiner = ble_health.Combiner(window)
    stop = asyncio.Event()
    tasks = [asyncio.create_task(follow(a, combiner, stop)) for a in addresses]
    try:
        while True:
            reading = combiner.due(time.monotonic())
            if reading:
                emit(reading)
            await asyncio.sleep(0.5)
    finally:
        stop.set()
        for t in tasks:
            t.cancel()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true", help="only list nearby standard health devices")
    ap.add_argument("--address", action="append", default=[], help="device address to read (repeatable)")
    ap.add_argument("--window", type=float, default=30.0,
                    help="seconds to collect measurements before sending one combined reading (default 30)")
    a = ap.parse_args()
    try:
        import bleak  # noqa: F401
    except ImportError:
        sys.exit("The Bluetooth library is not installed: pip install -r scripts/requirements-ble.txt")
    try:
        asyncio.run(scan(10) if a.scan else run(a.address, a.window))
    except KeyboardInterrupt:
        log("stopped")


if __name__ == "__main__":
    main()
