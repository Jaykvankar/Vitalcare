import { FormEvent, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, Me } from "../api";
import { homeFor, useAuth } from "../App";

type Step = { kind: "password" } | { kind: "verify" } | { kind: "enroll"; uri: string; secret: string };

export default function Login() {
  const { setMe } = useAuth();
  const nav = useNavigate();
  const [step, setStep] = useState<Step>({ kind: "password" });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
      const r = await api<{ user: Me }>("/api/auth/mfa", { method: "POST", body: { code } });
      done(r.user);
    } catch (err) {
      setError((err as ApiError).message);
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-head">
          <div className="brand big">
            <span className="logo" aria-hidden>
              <svg viewBox="0 0 24 24" width="22" height="22">
                <path d="M2 12h4l2-5 4 10 3-7 2 2h5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            SecureRPM
          </div>
          <p className="muted">Remote patient monitoring with end-to-end encrypted vitals.</p>
        </div>

        {step.kind === "password" && (
          <form onSubmit={submitPassword} className="form">
            <label>
              Username
              <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </label>
            <label>
              Password
              <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </label>
            {error && <div className="error">{error}</div>}
            <button className="primary" disabled={busy}>
              {busy ? "Checking…" : "Sign in"}
            </button>
          </form>
        )}

        {step.kind !== "password" && (
          <form onSubmit={submitCode} className="form">
            {step.kind === "enroll" ? (
              <div className="enroll">
                <p>
                  Clinician and admin accounts need a second factor. Scan this code in an authenticator app that supports
                  <b> SHA-512</b> TOTP (Aegis, 2FAS, FreeOTP), then enter the 6-digit code.
                </p>
                <div className="qr">
                  <QRCodeSVG value={step.uri} size={164} />
                </div>
                <code className="secret">{step.secret}</code>
              </div>
            ) : (
              <p className="muted">Enter the 6-digit code from your authenticator app.</p>
            )}
            <label>
              Authentication code
              <input
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                required
              />
            </label>
            {error && <div className="error">{error}</div>}
            <button className="primary" disabled={busy || code.length !== 6}>
              Verify
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
