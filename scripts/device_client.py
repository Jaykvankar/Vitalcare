"""Stand-alone device client: pair with a one-time code, then stream sealed + signed readings.

    python scripts/device_client.py pair   --link "vitalcare-pair:v1?server=...&id=...&code=..."   (from the QR code)
    python scripts/device_client.py pair   --pairing-id ID --code ABCD-EFGH-JKLM [--server https://vitalcare.example.org]
    python scripts/device_client.py stream --source stdin            (real sensor: JSON lines on standard input)
    python scripts/device_client.py stream --source synthetic        (or eicu:<stay>, mimic:<stay>, bidmc:<n>)

A real sensor program prints one line per reading and pipes it in, for example:
    python read_my_monitor.py | python scripts/device_client.py stream --source stdin

The device's RSA private key and settings are stored in device_state.json next to this script's
working directory, encrypted with AES-256-GCM under PBKDF2-HMAC-SHA-512(passphrase).
Passphrase: environment variable RPM_DEVICE_PASSPHRASE (prompted if not set).
"""
import argparse
import getpass
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

import _path

os.environ.setdefault("RPM_MASTER_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")  # unused by the client
import httpx

from app.security import aead, signatures
from app.security.hashing import b64d, b64e, canonical
from app.simulator import build_packet, pairing_request, stream_for

STATE = Path("device_state.json")


def _key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha512", passphrase.encode(), salt, 210_000, dklen=32)


def _passphrase() -> str:
    return os.environ.get("RPM_DEVICE_PASSPHRASE") or getpass.getpass("Device passphrase: ")


def save(state: dict, passphrase: str) -> None:
    salt = secrets.token_bytes(16)
    blob = aead.seal_blob(_key(passphrase, salt), json.dumps(state).encode(), canonical("device-state", b64e(salt)))
    STATE.write_text(json.dumps({"salt": b64e(salt), "blob": b64e(blob)}))


def load(passphrase: str) -> dict:
    doc = json.loads(STATE.read_text())
    key = _key(passphrase, b64d(doc["salt"]))
    return json.loads(aead.open_blob(key, b64d(doc["blob"]), canonical("device-state", doc["salt"])))


def verify_arg(server: str, cert: str | None):
    """TLS trust: an explicit CA file, the local dev certificate for localhost, else the system's trusted CAs."""
    if server.startswith("http://"):
        return True  # plain HTTP has no certificate (localhost demo mode only)
    if cert:
        return cert
    host = server.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    dev = _path.ROOT / "certs" / "dev-cert.pem"
    if host in ("localhost", "127.0.0.1") and dev.exists():
        return str(dev)
    return True


VITAL_KEYS = ("hr", "spo2", "sbp", "dbp", "temp", "rr")
LINK_PREFIX = "vitalcare-pair:v1?"


def parse_pairing_link(link: str) -> tuple[str, str, str]:
    """Read the pairing link shown as a QR code in the app: (server, pairing_id, code).

    vitalcare-pair:v1?server=https%3A%2F%2Fvitalcare.example.org&id=7f3c...&code=K7QM-2WXR-9HPD
    Only https servers are accepted, except plain http on this computer (localhost demo).
    """
    from urllib.parse import parse_qs, urlsplit

    link = link.strip()
    if not link.startswith(LINK_PREFIX):
        raise ValueError("not a Vitalcare pairing link")
    q = parse_qs(link[len(LINK_PREFIX):], strict_parsing=True)
    try:
        server, pairing_id, code = q["server"][0], q["id"][0], q["code"][0]
    except KeyError as exc:
        raise ValueError(f"pairing link is missing {exc.args[0]}") from exc
    parts = urlsplit(server)
    local = parts.hostname in ("localhost", "127.0.0.1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("the server in a pairing link must use https")
    if not parts.hostname or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("the server in a pairing link must be just an address, like https://vitalcare.example.org")
    if not pairing_id.isalnum() or len(pairing_id) > 32:
        raise ValueError("bad pairing id in link")
    return server.rstrip("/"), pairing_id, code


def parse_vitals_line(line: str) -> dict | None:
    """One JSON object per line from a sensor program. Any subset of the six vitals is fine
    (a heart-rate strap sends only "hr"), for example:
        {"hr": 78, "spo2": 97}
        {"hr": 78, "spo2": 97, "sbp": 122, "dbp": 79, "temp": 36.8, "rr": 15}
    Returns None (the line is skipped) when it has no vitals or a value is not a number.
    Blood pressure must come as a pair; the server checks plausible ranges.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    try:
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise TypeError
        vitals = {k: float(obj[k]) for k in VITAL_KEYS if obj.get(k) is not None}
        if not vitals or ("sbp" in vitals) != ("dbp" in vitals):
            raise ValueError
        return vitals
    except (ValueError, KeyError, TypeError):
        print(f"skipped (need numbers for one or more of {', '.join(VITAL_KEYS)}; sbp and dbp together): {line[:80]}",
              file=sys.stderr)
        return None


def cmd_pair(a: argparse.Namespace) -> None:
    global STATE
    STATE = Path(a.state)
    if STATE.exists():
        raise SystemExit(f"{STATE} already holds a paired device; use --state to choose another file")
    if a.link:
        try:
            a.server, a.pairing_id, a.code = parse_pairing_link(a.link)
        except ValueError as exc:
            raise SystemExit(f"Pairing link not accepted: {exc}") from exc
    elif not (a.pairing_id and a.code):
        raise SystemExit("Give either --link (from the QR code) or both --pairing-id and --code")
    private_pem, body = pairing_request(a.pairing_id, a.code)
    r = httpx.post(f"{a.server}/api/devices/pair", json=body, verify=verify_arg(a.server, a.cert), timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"Pairing failed ({r.status_code}): {r.json().get('detail')}")
    info = r.json()
    save({"server": a.server, "device_id": info["device_id"], "private_pem": private_pem.decode(),
          "server_dh_public": info["server_dh_public"], "cert": a.cert}, _passphrase())
    print(f"Paired as {info['device_id']}. Private key stored encrypted in {STATE.resolve()}")


def cmd_stream(a: argparse.Namespace) -> None:
    global STATE
    STATE = Path(a.state)
    st = load(_passphrase())
    key = signatures.load_private_pem(st["private_pem"].encode())
    server_pub = b64d(st["server_dh_public"])
    last = 0

    if a.source == "stdin":
        def readings():  # a real sensor program pipes one JSON line per reading
            for line in sys.stdin:
                v = parse_vitals_line(line)
                if v is not None:
                    yield v
    else:
        stream = stream_for(st["device_id"], a.source)

        def readings():
            while True:
                yield stream.step()[0]
                time.sleep(a.interval)

    with httpx.Client(base_url=st["server"], verify=verify_arg(st["server"], st.get("cert")), timeout=10) as client:
        for vitals in readings():
            seq = last = max(int(time.time() * 1000), last + 1)
            pkt = build_packet(st["device_id"], key, server_pub, vitals, ts=int(time.time()), seq=seq)
            r = client.post("/api/ingest", json=pkt)
            print(r.status_code, r.json(), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("pair", help="pair this device with a one-time code")
    pp.add_argument("--link", help="pairing link from the QR code in the app (replaces the three options below)")
    pp.add_argument("--pairing-id")
    pp.add_argument("--code")
    pp.add_argument("--server", default="https://localhost:8443")
    pp.add_argument("--cert", default=None, help="CA file to trust (default: system CAs; dev cert for localhost)")
    pp.add_argument("--state", default="device_state.json", help="encrypted file holding this device's key")
    ps = sub.add_parser("stream", help="send readings")
    ps.add_argument("--source", default="synthetic",
                    help="stdin (JSON lines from a real sensor) | synthetic | eicu:<stay> | mimic:<stay> | bidmc:<n>")
    ps.add_argument("--interval", type=float, default=5.0, help="seconds between readings (not used for stdin)")
    ps.add_argument("--state", default="device_state.json")
    args = p.parse_args()
    {"pair": cmd_pair, "stream": cmd_stream}[args.cmd](args)
