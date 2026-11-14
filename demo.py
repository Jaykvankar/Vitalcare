"""Vitalcare demo: one command from a fresh checkout to a running, streaming system.

    .venv\\Scripts\\python demo.py              (browser-friendly: http://localhost:8000)
    .venv\\Scripts\\python demo.py --https      (https://localhost:8443 with the self-signed dev cert)
    .venv\\Scripts\\python demo.py --reset      (back up the current demo data and seed it again)

What it does, skipping any step that is already done:
  1. creates .env with a random master key            (scripts/init_env.py)
  2. creates the self-signed TLS certificate          (scripts/gen_dev_cert.py)
  3. builds the web app if frontend/dist is missing   (npm ci && npm run build)
  4. seeds 7 demo users and 4 patients with 24 h of encrypted history (app.seed). With the PhysioNet data
     in data/real/, two patients replay real eICU ICU stays from different hospitals and one a MIMIC-III stay.
  5. starts the server with every patient's simulated monitor streaming sealed, signed readings
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def web_app_outdated() -> bool:
    """True when frontend/dist is missing or older than any frontend source file."""
    built = ROOT / "frontend" / "dist" / "index.html"
    if not built.exists():
        return True
    front = ROOT / "frontend"
    sources = [front / "index.html", front / "package.json", *(front / "src").rglob("*"), *(front / "public").rglob("*")]
    newest = max((p.stat().st_mtime for p in sources if p.is_file()), default=0.0)
    return newest > built.stat().st_mtime


def sign_ins(creds: str) -> list[tuple[str, str, str]]:
    """(username, role, password) from seed_credentials.txt (one value per line under "== user (role)")."""
    lines = creds.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.startswith("== ") and " (" in line:
            user, role = line[3:].split(" (", 1)
            pw = next((lines[j + 1] for j in range(i + 1, len(lines) - 1) if lines[j] == "password:"), "")
            out.append((user, role.rstrip(")"), pw.strip()))
    return out


def run(args: list[str], cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True)  # noqa: S603  (fixed argument lists)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--https", action="store_true", help="serve https://localhost:8443 instead of http://localhost:8000")
    ap.add_argument("--reset", action="store_true", help="back up and recreate the demo database")
    a = ap.parse_args()

    if not (ROOT / ".env").exists():
        step("Creating .env with a new random master key")
        run([PY, "scripts/init_env.py"])
    if not (ROOT / "certs" / "dev-cert.pem").exists():
        step("Creating a self-signed TLS certificate for localhost")
        run([PY, "scripts/gen_dev_cert.py"])
    if web_app_outdated():
        npm = shutil.which("npm")
        if npm is None:
            sys.exit("The web app is not built (or is older than its source) and npm was not found. "
                     "Install Node.js 20+ and run this again.")
        step("Building the web app")
        if not (ROOT / "frontend" / "node_modules").exists():
            run([npm, "ci", "--no-audit", "--no-fund"], cwd=ROOT / "frontend")
        run([npm, "run", "build"], cwd=ROOT / "frontend")

    data_dir = ROOT / "backend" / "data"
    if a.reset and data_dir.exists():
        backup = ROOT / f"demo-backup-{time.strftime('%Y%m%d-%H%M%S')}"
        step(f"Backing up the current demo data to {backup.name}")
        backup.mkdir()
        for p in (data_dir, ROOT / "simulator_keys", ROOT / "seed_credentials.txt"):
            if p.exists():
                shutil.move(str(p), str(backup / p.name))
        # Keep the same (readable) passwords after a reset, so a browser that saved them still signs in.
        os.environ["RPM_SEED_KEEP_PASSWORDS"] = str(backup / "seed_credentials.txt")
    if not (data_dir / "rpm.db").exists():
        step("Seeding demo users, patients and 24 h of encrypted history (about a minute)")
        run([PY, "-m", "app.seed"], cwd=ROOT / "backend")

    url = "https://localhost:8443" if a.https else "http://localhost:8000"
    creds = (ROOT / "seed_credentials.txt").read_text(encoding="utf-8")
    accounts = "\n".join(f"      {u:10} {r:10} {pw}" for u, r, pw in sign_ins(creds))
    print(f"""
==> Vitalcare is starting at {url}

    Sign in with (also in seed_credentials.txt; passwords are case-sensitive):
{accounts}
    In demo mode the sign-in page fills the password when you pick a role.
    Staff (dr.mehta, dr.rao, admin) then need a 6-digit code. In a second terminal run:
      {PY} scripts\\totp_code.py dr.mehta
    and type the code it prints (it changes every 30 seconds).

    Try it:
      dr.mehta  -> worklist ranked by urgency -> open a patient -> acknowledge an alert
      admin     -> Data sources (switch a monitor to another real ICU stay), Bulk import, Privacy ledger
      p.iyer    -> own vitals, pause sharing, download my data

    Press Ctrl+C to stop.
""", flush=True)
    if "recovery codes" not in creds:
        print("    (This demo database predates recovery codes; staff can create them under Account.)\n", flush=True)
    env = {**os.environ, "RPM_DEMO_AUTOSTREAM": "true", "RPM_DEMO_MODE": "true"}
    cmd = [PY, str(ROOT / "run_server.py")] + ([] if a.https else ["--http"])
    try:
        sys.exit(subprocess.call(cmd, env=env))  # noqa: S603
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
