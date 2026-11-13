import { FormEvent, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, Me } from "../api";
import { homeFor, useAuth } from "../App";
import { Icon } from "../components/Icons";
import { RecoveryCodes } from "./Account";

type Step = { kind: "password" } | { kind: "verify" } | { kind: "enroll"; uri: string; secret: string } | { kind: "codes"; codes: string[]; user: Me };

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
        body: { username, password },
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
          <span className="name">SecureRPM</span>
        </div>
        <svg className="wave" viewBox="0 0 600 120" preserveAspectRatio="none" height="140" width="100%">
          <path d="M0 60 H170 L195 20 L225 105 L255 35 L275 60 H600" fill="none" stroke="currentColor" strokeWidth="3" />
        </svg>
        <div className="pitch">
          <h1>Remote monitoring that keeps patient data private.</h1>
          <p>Vital signs are encrypted on the device, analysed on arrival, and visible only to the care team the patient has consented to.</p>
          <div className="points">
            <div><Icon.Lock size={18} /> Diffie–Hellman + AES-256 sealing, RSA-signed readings</div>
            <div><Icon.Score size={18} /> Clinical rules, NEWS2 and an AI early-warning model</div>
            <div><Icon.Ledger size={18} /> Tamper-evident ledger of every access</div>
          </div>
        </div>
        <div className="legal">Educational project. Not a certified medical device.</div>
      </section>

      <section className="login-form">
        <div className="inner">
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
                  <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
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
      </section>
    </div>
  );
}
