import { FormEvent, useState } from "react";
import { api, ApiError, Me } from "../api";
import { useAuth } from "../App";
import { Icon } from "../components/Icons";

export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone?: () => void }) {
  const download = () => {
    const blob = new Blob([`Vitalcare recovery codes\nEach code works once.\n\n${codes.join("\n")}\n`], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "vitalcare-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className="form">
      <div className="notice info">
        <Icon.Key size={18} />
        <div>Save these one-time recovery codes somewhere safe. Each one signs you in once if you lose your authenticator. They will not be shown again.</div>
      </div>
      <div className="code-grid">{codes.map((c) => <code key={c}>{c}</code>)}</div>
      <div className="row">
        <button type="button" className="btn secondary" onClick={download}>Download as text file</button>
        {onDone && <button type="button" className="btn primary" onClick={onDone}>I have saved them</button>}
      </div>
    </div>
  );
}

export function ChangePasswordForm({ forced, onChanged }: { forced?: boolean; onChanged: (me: Me) => void }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr("");
    if (next !== again) return setErr("The new passwords do not match");
    setBusy(true);
    try {
      const r = await api<{ user: Me }>("/api/auth/password", { method: "POST", body: { current_password: cur, new_password: next } });
      setOk(true);
      setCur(""); setNext(""); setAgain("");
      onChanged(r.user);
    } catch (e2) {
      setErr((e2 as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form" onSubmit={submit}>
      {forced && <div className="notice info">Your account was created with a temporary password. Choose your own to continue.</div>}
      <label className="field">{forced ? "Temporary password" : "Current password"}
        <input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required />
      </label>
      <label className="field">New password <span className="hint">At least 12 characters, not containing your username</span>
        <input type="password" autoComplete="new-password" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} required />
      </label>
      <label className="field">Repeat new password
        <input type="password" autoComplete="new-password" minLength={12} value={again} onChange={(e) => setAgain(e.target.value)} required />
      </label>
      {err && <div className="notice error">{err}</div>}
      {ok && !forced && <div className="notice success">Password changed. Your other sessions were signed out.</div>}
      <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Change password"}</button>
    </form>
  );
}

export function ForcedPasswordChange() {
  const { me, setMe } = useAuth();
  return (
    <div className="login">
      <section className="login-art">
        <div className="side-brand"><span className="mark"><Icon.Logo size={18} /></span><span className="name">Vitalcare</span></div>
        <div className="pitch"><h1>Welcome, {me?.full_name.split(" ")[0]}.</h1><p>One quick step before you start.</p></div>
      </section>
      <section className="login-form">
        <div className="inner">
          <h2>Set your password</h2>
          <p className="sub">Signed in as {me?.username}</p>
          <ChangePasswordForm forced onChanged={(u) => setMe(u)} />
        </div>
      </section>
    </div>
  );
}

export default function Account() {
  const { me, setMe } = useAuth();
  const [codes, setCodes] = useState<string[] | null>(null);
  const regen = async () => {
    if (!confirm("Create new recovery codes? Your old codes will stop working.")) return;
    const r = await api<{ recovery_codes: string[] }>("/api/auth/recovery-codes", { method: "POST" });
    setCodes(r.recovery_codes);
    setMe({ ...me!, recovery_codes_left: r.recovery_codes.length });
  };
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Account</div>
          <h1>Sign-in & security</h1>
          <p className="sub">Changing your password signs out your other sessions.</p>
        </div>
      </div>
      <div className="grid two">
        <div className="card pad">
          <h2 style={{ marginBottom: 14 }}>Password</h2>
          <ChangePasswordForm onChanged={(u) => setMe(u)} />
        </div>
        {me?.role !== "patient" && (
          <div className="card pad">
            <div className="row"><h2>Recovery codes</h2><span className="spacer" />
              <span className={`tag ${(me?.recovery_codes_left ?? 0) > 3 ? "ok" : "danger"}`}>{me?.recovery_codes_left ?? 0} left</span>
            </div>
            <p className="muted small" style={{ margin: "8px 0 14px" }}>Use one instead of an authenticator code if you lose your phone. Each code works once.</p>
            {codes ? <RecoveryCodes codes={codes} /> : <button className="btn secondary" onClick={regen}><Icon.Key size={16} /> Create new codes</button>}
          </div>
        )}
      </div>
    </div>
  );
}
