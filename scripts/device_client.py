"""Stand-alone device client: pair with a one-time code, then stream sealed + signed readings.

    python scripts/device_client.py pair   --pairing-id ID --code ABCD-EFGH-JKLM [--server https://localhost:8443]
    python scripts/device_client.py stream [--source synthetic | mimic:<stay> | bidmc:<n>] [--interval 5]

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
    if server.startswith("http://"):
        return False
    return cert or str(_path.ROOT / "certs" / "dev-cert.pem")


def cmd_pair(a: argparse.Namespace) -> None:
    private_pem, body = pairing_request(a.pairing_id, a.code)
    r = httpx.post(f"{a.server}/api/devices/pair", json=body, verify=verify_arg(a.server, a.cert), timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"Pairing failed ({r.status_code}): {r.json().get('detail')}")
    info = r.json()
    save({"server": a.server, "device_id": info["device_id"], "private_pem": private_pem.decode(),
          "server_dh_public": info["server_dh_public"], "cert": a.cert}, _passphrase())
    print(f"Paired as {info['device_id']}. Private key stored encrypted in {STATE.resolve()}")


def cmd_stream(a: argparse.Namespace) -> None:
    st = load(_passphrase())
    key = signatures.load_private_pem(st["private_pem"].encode())
    server_pub = b64d(st["server_dh_public"])
    stream = stream_for(st["device_id"], a.source)
    last = 0
    with httpx.Client(base_url=st["server"], verify=verify_arg(st["server"], st.get("cert")), timeout=10) as client:
        while True:
            vitals, _, _ = stream.step()
            seq = last = max(int(time.time() * 1000), last + 1)
            pkt = build_packet(st["device_id"], key, server_pub, vitals, ts=int(time.time()), seq=seq)
            r = client.post("/api/ingest", json=pkt)
            print(r.status_code, r.json())
            time.sleep(a.interval)


p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = p.add_subparsers(dest="cmd", required=True)
pp = sub.add_parser("pair")
pp.add_argument("--pairing-id", required=True)
pp.add_argument("--code", required=True)
pp.add_argument("--server", default="https://localhost:8443")
pp.add_argument("--cert", default=None, help="CA/cert file to trust (default: certs/dev-cert.pem)")
ps = sub.add_parser("stream")
ps.add_argument("--source", default="synthetic")
ps.add_argument("--interval", type=float, default=5.0)
args = p.parse_args()
{"pair": cmd_pair, "stream": cmd_stream}[args.cmd](args)
