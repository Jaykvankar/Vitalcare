"""Example sensor program: prints one JSON line per reading, the format device_client.py reads on stdin.

A hospital's gateway replaces the body of read_sensor() with code that talks to its real monitor
(Bluetooth, USB/serial, or a hospital integration feed). Everything else stays the same:

    python scripts/sensor_example.py | python scripts/device_client.py stream --source stdin

Options: --count N (stop after N readings), --interval S (seconds between readings, default 5).
"""
import argparse
import json
import random
import sys
import time


def read_sensor(rng: random.Random) -> dict:
    """Stand-in for a real device. Must return all six values in these units."""
    return {
        "hr": round(rng.gauss(76, 3)),          # beats per minute
        "spo2": round(rng.gauss(97, 0.6), 1),   # percent
        "sbp": round(rng.gauss(122, 4)),        # mmHg, systolic
        "dbp": round(rng.gauss(78, 3)),         # mmHg, diastolic
        "temp": round(rng.gauss(36.8, 0.1), 1), # degrees Celsius
        "rr": round(rng.gauss(15, 1)),          # breaths per minute
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=0, help="number of readings (0 = run until stopped)")
    ap.add_argument("--interval", type=float, default=5.0)
    a = ap.parse_args()
    rng = random.Random()
    n = 0
    while a.count == 0 or n < a.count:
        print(json.dumps(read_sensor(rng)), flush=True)
        n += 1
        if a.count == 0 or n < a.count:
            time.sleep(a.interval)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
