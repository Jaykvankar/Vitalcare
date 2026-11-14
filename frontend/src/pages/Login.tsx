import { FormEvent, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, Me } from "../api";
import { homeFor, useAuth } from "../App";
import { Icon } from "../components/Icons";
import { RecoveryCodes } from "./Account";

type Step = { kind: "password" } | { kind: "verify" } | { kind: "enroll"; uri: string; secret: string } | { kind: "codes"; codes: string[]; user: Me };

const BASELINE = 96;
// Each beat ends on the baseline so the loop has no seam. Heights differ on purpose.
const BEATS: Array<Array<[number, number]>> = [
  [[10, 96], [6, 58], [6, 96], [6, 96], [7, 6], [12, 154], [8, 36], [7, 96], [14, 96]],
  [[28, 96], [7, 90], [7, 96], [18, 96], [7, 82], [7, 108], [6, 90], [6, 96], [22, 96]],
  [[12, 96], [6, 78], [6, 96], [8, 96], [8, 70], [8, 156], [10, 28], [8, 96], [12, 96]],
  [[16, 96], [8, 74], [8, 96], [14, 96], [10, 44], [12, 128], [9, 70], [8, 96], [20, 96]],
  [[8, 96], [5, 66], [5, 96], [5, 96], [6, 22], [7, 140], [6, 58], [5, 96], [7, 96], [5, 96], [5, 80], [5, 96], [4, 96], [6, 48], [7, 118], [6, 72], [5, 96], [12, 96]],
  [[54, 96], [6, 70], [6, 96], [6, 96], [8, 10], [11, 150], [9, 42], [7, 96], [10, 96]],
  [[14, 96], [10, 70], [12, 96], [12, 96], [16, 32], [18, 144], [14, 52], [10, 96], [16, 96]],
  [[18, 96], [7, 84], [7, 96], [8, 96], [8, 50], [9, 124], [8, 72], [6, 96], [8, 40], [10, 96], [16, 96]],
];

function buildTrace(): { d: string; width: number } {
  let x = 0;
  let d = `M0 ${BASELINE}`;
  for (const beat of BEATS) {
    for (const [dx, y] of beat) {
      x += dx;
      d += `L${x} ${y}`;
    }
  }
  return { d, width: x };
}

const TRACE = buildTrace();
const VISIBLE = 300;

function ChartTrace() {
  const { d, width } = TRACE;
  return (
    <div className="trace-window">
      <svg
        className="trace-run"
        style={{ width: `${(width * 2 / VISIBLE) * 100}%` }}
        viewBox={`0 0 ${width * 2} 160`}
        preserveAspectRatio="none"
        aria-hidden
      >
        <path className="trace-line" d={d} />
        <path className="trace-line" d={d} transform={`translate(${width} 0)`} />
      </svg>
    </div>
  );
}

export interface DemoAccount { username: string; role: string; full_name: string; password?: string }

/** One button per role. Prefers the account the demo script uses; falls back to any seeded account with that role. */
const ROLE_PICKS: { role: string; prefer: string; label: string; icon: keyof typeof Icon; hint: (name: string) => string }[] = [
  { role: "patient", prefer: "p.iyer", label: "Patient", icon: "Heart", hint: (n) => `${n} sees only their own vitals, and can pause sharing.` },
  { role: "clinician", prefer: "dr.mehta", label: "Caretaker", icon: "Users", hint: (n) => `${n} opens a worklist ranked by urgency.` },
  { role: "admin", prefer: "admin", label: "Admin", icon: "Shield", hint: (n) => `${n} manages people and the ledger, and cannot read vitals.` },
];

/** Demo mode only (the server returns no accounts otherwise). Fills in the username and, when the seed file
 *  has one, the password. TOTP secrets are never sent. */
function DemoRoles({ accounts, active, onPick }: { accounts: DemoAccount[]; active: string; onPick: (account: DemoAccount) => void }) {
  const picks = ROLE_PICKS.flatMap((p) => {
    const a = accounts.find((x) => x.username === p.prefer) ?? accounts.find((x) => x.role === p.role);
    return a ? [{ ...p, account: a }] : [];
  });
  if (picks.length === 0) return null;
  const chosen = picks.find((p) => p.account.username === active);
  return (
    <div className="demo-roles">
      <span className="label">Try a role (demo)</span>
      <div className="demo-row">
        {picks.map((p) => {
          const I = Icon[p.icon];
          return (
            <button key={p.role} type="button" className={active === p.account.username ? "demo-role on" : "demo-role"} onClick={() => onPick(p.account)}>
              <I size={16} /> {p.label}
            </button>
          );
        })}
      </div>
      {chosen && (
        <p className="demo-hint">
          {chosen.hint(chosen.account.full_name)} Username <b>{chosen.account.username}</b>
          {chosen.account.password ? <> and the password are filled in.</> : <> is filled in. Type the password from <code>seed_credentials.txt</code>.</>}
          {chosen.role !== "patient" && <> A 6-digit code comes next.</>}
        </p>
      )}
    </div>
  );
}

export default function Login() {
  const { setMe } = useAuth();
  const nav = useNavigate();
  const [step, setStep] = useState<Step>({ kind: "password" });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [useRecovery, setUseRecovery] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [demoAccounts, setDemoAccounts] = useState<DemoAccount[]>([]);
  const passwordRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    api<{ demo: boolean; accounts: DemoAccount[] }>("/api/auth/demo-accounts")
      .then((d) => live && setDemoAccounts(Array.isArray(d?.accounts) ? d.accounts : []))
      .catch(() => live && setDemoAccounts([]));
    return () => { live = false; };
  }, []);

  const pickDemo = (account: DemoAccount) => {
    setUsername(account.username);
    setPassword(account.password ?? "");
    setShowPassword(false);
    setError("");
    setStep({ kind: "password" });
    if (passwordRef.current) passwordRef.current.focus();
    else window.setTimeout(() => passwordRef.current?.focus(), 0);   // coming back from the code step
  };

  const done = (me: Me) => {
    setMe(me);
    nav(homeFor(me), { replace: true });
  };

  const submitPassword = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api<{ mfa: string; user?: Me; otpauth_uri?: string; secret?: string }>("/api/auth/login", {
        method: "POST",
        body: { username: username.trim(), password },
      });
      setPassword("");
      if (r.mfa === "none" && r.user) done(r.user);
      else if (r.mfa === "enroll") setStep({ kind: "enroll", uri: r.otpauth_uri!, secret: r.secret! });
      else setStep({ kind: "verify" });
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api<{ user: Me; recovery_codes: string[] | null }>("/api/auth/mfa", { method: "POST", body: { code } });
      if (r.recovery_codes) setStep({ kind: "codes", codes: r.recovery_codes, user: r.user });
      else done(r.user);
    } catch (err) {
      setError((err as ApiError).message);
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <section className="login-art">
        <div className="side-brand">
          <span className="mark"><Icon.Logo size={18} /></span>
          <span className="name">Vitalcare</span>
        </div>
        <div className="chart-hero">
          <ChartTrace />
        </div>
        <div className="pitch">
          <h1>Remote monitoring that keeps patient data private.</h1>
          <p>Vital signs are encrypted on the device, analysed on arrival, and visible only to the care team the patient has consented to.</p>
          <div className="points">
            <div><Icon.Lock size={18} /> Diffie–Hellman + AES-256 sealing, RSA-signed readings</div>
            <div><Icon.Score size={18} /> Clinical rules, NEWS2 and an AI early-warning model</div>
            <div><Icon.Ledger size={18} /> Tamper-evident ledger of every access</div>
          </div>
        </div>
        <DemoRoles accounts={demoAccounts} active={username} onPick={pickDemo} />
      </section>

      <section className="login-form">
        <div className="inner">
          <div className="login-strip"><ChartTrace /></div>
          {step.kind === "password" ? (
            <>
              <h2>Sign in</h2>
              <p className="sub">Use the account your care organisation gave you.</p>
              <form onSubmit={submitPassword} className="form">
                <label className="field">
                  Username
                  <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
                </label>
                <label className="field">
                  Password
                  <span className="password-field">
                    <input ref={passwordRef} type={showPassword ? "text" : "password"} autoComplete="current-password" value={password}
                      onChange={(e) => setPassword(e.target.value)} required />
                    <button type="button" className="reveal" onClick={() => setShowPassword((s) => !s)}
                      aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}
                      title={showPassword ? "Hide password" : "Show password"}>
                      {showPassword ? <Icon.EyeOff size={18} /> : <Icon.Eye size={18} />}
                    </button>
                  </span>
                </label>
                {error && <div className="notice error">{error}</div>}
                <button className="btn primary block" disabled={busy}>
                  {busy ? "Checking…" : "Continue"}
                </button>
              </form>
            </>
          ) : step.kind === "codes" ? (
            <>
              <h2>Two-step sign-in is on</h2>
              <p className="sub">One last thing: your recovery codes.</p>
              <RecoveryCodes codes={step.codes} onDone={() => done(step.user)} />
            </>
          ) : (
            <>
              <h2>{step.kind === "enroll" ? "Set up two-step sign-in" : "Two-step verification"}</h2>
              <p className="sub">
                {step.kind === "enroll"
                  ? "Staff accounts need a second factor. Scan the code with an authenticator app that supports SHA-512 (Aegis, 2FAS or FreeOTP)."
                  : "Enter the 6-digit code from your authenticator app."}
              </p>
              <form onSubmit={submitCode} className="form">
                {step.kind === "enroll" && (
                  <div>
                    <div className="qr"><QRCodeSVG value={step.uri} size={168} /></div>
                    <code className="secret">{step.secret}</code>
                  </div>
                )}
                {useRecovery ? (
                  <label className="field">
                    Recovery code
                    <input autoFocus autoComplete="off" placeholder="XXXXX-XXXXX" maxLength={11} value={code}
                      style={{ letterSpacing: "0.12em", fontFamily: "var(--mono)", fontSize: "1.05rem" }}
                      onChange={(e) => setCode(e.target.value.toUpperCase())} required />
                  </label>
                ) : (
                  <label className="field">
                    Authentication code
                    <input
                      autoFocus
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      value={code}
                      style={{ letterSpacing: "0.3em", fontFamily: "var(--mono)", fontSize: "1.1rem" }}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                      required
                    />
                  </label>
                )}
                {error && <div className="notice error">{error}</div>}
                <button className="btn primary block" disabled={busy || (useRecovery ? code.replace("-", "").length !== 10 : code.length !== 6)}>
                  Verify and sign in
                </button>
                {step.kind === "verify" && (
                  <button type="button" className="btn ghost block" onClick={() => { setUseRecovery(!useRecovery); setCode(""); setError(""); }}>
                    {useRecovery ? "Use my authenticator app" : "Lost your phone? Use a recovery code"}
                  </button>
                )}
                <button type="button" className="btn ghost block" onClick={() => { setStep({ kind: "password" }); setError(""); }}>
                  Use a different account
                </button>
              </form>
            </>
          )}
        </div>
        <p className="login-note">Staff enter a 6-digit code after the password. Patients sign in with a password only.</p>
        <DemoRoles accounts={demoAccounts} active={username} onPick={pickDemo} />
      </section>
    </div>
  );
}
