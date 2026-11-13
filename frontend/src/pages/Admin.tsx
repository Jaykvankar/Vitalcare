import { FormEvent, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, ApiError } from "../api";
import { usePolling } from "../hooks";

interface UserRow { id: number; username: string; full_name: string; role: string; active: boolean; mfa_enrolled: boolean; patient_id: number | null }
interface PatientRow { id: number; name: string; username: string; consent_active: boolean; key_version: number; devices: { id: string; label: string }[]; simulating: boolean; simulator_status: string | null }
interface AssignmentRow { id: number; clinician_id: number; clinician: string; patient_id: number; patient: string }
interface AuditRow { id: number; ts: string; actor: string; action: string; target: string; detail: string; hash: string }
interface VerifyResult { ok: boolean; rows: number; checkpoints: number; anchored_through_row: number; unanchored_rows: number; problems: string[] }

export default function Admin() {
  return (
    <div className="page">
      <Routes>
        <Route path="users" element={<Users />} />
        <Route path="assignments" element={<Assignments />} />
        <Route path="simulator" element={<Simulator />} />
        <Route path="audit" element={<Audit />} />
        <Route path="security" element={<Security />} />
        <Route path="*" element={<Navigate to="users" replace />} />
      </Routes>
    </div>
  );
}

function Users() {
  const { data, reload } = usePolling<UserRow[]>("/api/admin/users", 15000);
  const empty = { username: "", full_name: "", role: "patient", password: "", dob: "", phone: "", address: "" };
  const [f, setF] = useState(empty);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    try {
      const body = { ...f, dob: f.dob || null, phone: f.phone || null, address: f.address || null };
      await api("/api/admin/users", { method: "POST", body });
      setMsg({ ok: true, text: `Created ${f.username}.${f.role !== "patient" ? " They will enrol TOTP at first sign-in." : " A simulated device was registered."}` });
      setF(empty);
      reload();
    } catch (err) {
      setMsg({ ok: false, text: (err as ApiError).message });
    }
  };
  const act = async (path: string, body?: unknown) => {
    await api(path, { method: "POST", body: body ?? {} });
    reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Users</h1>
          <p className="muted">Admins manage accounts. They cannot see vitals or patient personal details.</p>
        </div>
      </div>
      <div className="grid-2 wide-left">
        <div className="panel">
          <table className="table">
            <thead>
              <tr><th>Name</th><th>Username</th><th>Role</th><th>MFA</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {data?.map((u) => (
                <tr key={u.id}>
                  <td><b>{u.full_name}</b></td>
                  <td className="mono">{u.username}</td>
                  <td><span className="role">{u.role}</span></td>
                  <td>{u.role === "patient" ? <span className="muted">n/a</span> : u.mfa_enrolled ? "enrolled" : <span className="warn-text">pending</span>}</td>
                  <td>{u.active ? "active" : <span className="crit-text">disabled</span>}</td>
                  <td className="actions">
                    {u.role !== "patient" && u.mfa_enrolled && <button className="ghost small" onClick={() => act(`/api/admin/users/${u.id}/reset-mfa`)}>Reset MFA</button>}
                    {u.role !== "admin" && (
                      <button className="ghost small" onClick={() => act(`/api/admin/users/${u.id}/active`, { active: !u.active })}>
                        {u.active ? "Disable" : "Enable"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form className="panel pad form" onSubmit={create}>
          <h2>New user</h2>
          <label>Full name<input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required /></label>
          <label>Username<input value={f.username} pattern="[a-zA-Z0-9_.\-]{3,64}" onChange={(e) => setF({ ...f, username: e.target.value })} required /></label>
          <label>Role
            <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="patient">Patient</option>
              <option value="clinician">Clinician</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          <label>Initial password (min 12)<input type="password" minLength={12} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required /></label>
          {f.role === "patient" && (
            <>
              <label>Date of birth<input type="date" value={f.dob} onChange={(e) => setF({ ...f, dob: e.target.value })} /></label>
              <label>Phone<input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
              <label>Address<input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></label>
              <p className="muted small">Personal details are encrypted with the patient's own AES-256 key.</p>
            </>
          )}
          {msg && <div className={msg.ok ? "success" : "error"}>{msg.text}</div>}
          <button className="primary">Create user</button>
        </form>
      </div>
    </>
  );
}

function Assignments() {
  const { data: rows, reload } = usePolling<AssignmentRow[]>("/api/admin/assignments", 15000);
  const { data: users } = usePolling<UserRow[]>("/api/admin/users", 30000);
  const { data: patients } = usePolling<PatientRow[]>("/api/admin/patients", 30000);
  const [c, setC] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const clinicians = users?.filter((u) => u.role === "clinician" && u.active) ?? [];

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      await api("/api/admin/assignments", { method: "POST", body: { clinician_id: Number(c), patient_id: Number(p) } });
      reload();
    } catch (er) {
      setErr((er as ApiError).message);
    }
  };
  const remove = async (id: number) => {
    await api(`/api/admin/assignments/${id}`, { method: "DELETE" });
    reload();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Care-team assignments</h1>
          <p className="muted">A clinician can decrypt a patient's data only while assigned.</p>
        </div>
      </div>
      <form className="panel pad inline-form" onSubmit={add}>
        <select value={c} onChange={(e) => setC(e.target.value)} required>
          <option value="">Clinician…</option>
          {clinicians.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </select>
        <span className="muted">cares for</span>
        <select value={p} onChange={(e) => setP(e.target.value)} required>
          <option value="">Patient…</option>
          {patients?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
        <button className="primary">Assign</button>
        {err && <span className="error">{err}</span>}
      </form>
      <div className="panel">
        <table className="table">
          <thead><tr><th>Clinician</th><th>Patient</th><th /></tr></thead>
          <tbody>
            {rows?.map((a) => (
              <tr key={a.id}>
                <td>{a.clinician}</td>
                <td>{a.patient}</td>
                <td className="actions"><button className="ghost small" onClick={() => remove(a.id)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const EPISODES = ["hypoxia", "tachycardia", "hypotension", "fever", "activity"];

function Simulator() {
  const { data, reload } = usePolling<PatientRow[]>("/api/admin/patients", 4000);
  const [flash, setFlash] = useState("");
  const toggle = async (p: PatientRow) => {
    await api("/api/admin/simulator", { method: "POST", body: { patient_id: p.id, enabled: !p.simulating } });
    reload();
  };
  const all = async (on: boolean) => {
    for (const p of data ?? []) if (p.consent_active) await api("/api/admin/simulator", { method: "POST", body: { patient_id: p.id, enabled: on } });
    reload();
  };
  const episode = async (p: PatientRow, kind: string) => {
    await api("/api/admin/simulator/episode", { method: "POST", body: { patient_id: p.id, kind } });
    setFlash(`Started ${kind} episode for ${p.name}. It develops over the next minutes.`);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Device simulator</h1>
          <p className="muted">
            Each simulated wearable seals its readings with Diffie-Hellman + AES-256-GCM, signs them with its own RSA-3072 key and posts them
            to the real HTTPS ingest API every 5 seconds.
          </p>
        </div>
        <div className="summary">
          <button className="secondary" onClick={() => all(true)}>Start all</button>
          <button className="ghost" onClick={() => all(false)}>Stop all</button>
        </div>
      </div>
      {flash && <div className="success banner">{flash}</div>}
      <div className="panel">
        <table className="table">
          <thead><tr><th>Patient</th><th>Devices</th><th>Streaming</th><th>Last result</th><th>Inject episode</th></tr></thead>
          <tbody>
            {data?.map((p) => (
              <tr key={p.id}>
                <td><b>{p.name}</b>{!p.consent_active && <span className="tag">consent revoked</span>}</td>
                <td className="mono small">{p.devices.map((d) => d.id).join(", ") || "–"}</td>
                <td>
                  <label className="switch">
                    <input type="checkbox" checked={p.simulating} onChange={() => toggle(p)} disabled={!p.devices.length} />
                    <span>{p.simulating ? "on" : "off"}</span>
                  </label>
                </td>
                <td className="small">{p.simulator_status ?? <span className="muted">–</span>}</td>
                <td>
                  <select defaultValue="" onChange={(e) => { if (e.target.value) { episode(p, e.target.value); e.target.value = ""; } }} disabled={!p.simulating}>
                    <option value="">Choose…</option>
                    {EPISODES.map((k) => <option key={k} value={k}>{k}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Audit() {
  const { data, reload } = usePolling<AuditRow[]>("/api/admin/audit?limit=100", 10000);
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const verify = async () => {
    setBusy(true);
    try {
      setResult(await api<VerifyResult>("/api/admin/audit/verify", { method: "POST" }));
      reload();
    } finally {
      setBusy(false);
    }
  };
  const checkpoint = async () => {
    await api("/api/admin/audit/checkpoint", { method: "POST" });
    verify();
  };
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit log</h1>
          <p className="muted">Append-only. Each row stores SHA-512 of the previous row; checkpoints are signed with the server's ECDSA P-384 key.</p>
        </div>
        <div className="summary">
          <button className="ghost" onClick={checkpoint}>Sign checkpoint now</button>
          <button className="primary" onClick={verify} disabled={busy}>{busy ? "Verifying…" : "Verify integrity"}</button>
        </div>
      </div>
      {result && (
        <div className={`banner ${result.ok ? "success" : "error"}`}>
          {result.ok ? "Ledger intact." : "Tampering detected."} {result.rows} rows, {result.checkpoints} signed checkpoints, anchored through row{" "}
          {result.anchored_through_row} ({result.unanchored_rows} newer rows await the next checkpoint).
          {result.problems.length > 0 && <ul>{result.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        </div>
      )}
      <div className="panel">
        <table className="table compact">
          <thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Detail</th><th>Hash</th></tr></thead>
          <tbody>
            {data?.map((r) => (
              <tr key={r.id}>
                <td className="num muted">{r.id}</td>
                <td className="small">{new Date(r.ts).toLocaleString()}</td>
                <td>{r.actor}</td>
                <td><span className="code">{r.action}</span></td>
                <td className="small">{r.target}</td>
                <td className="small muted">{r.detail}</td>
                <td className="mono small muted">{r.hash}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

interface KeyStatus { master_key_version: number; patients_by_key_version: Record<string, number>; dh_public_fingerprint: string; audit_key_fingerprint: string; algorithms: Record<string, string> }

function Security() {
  const { data } = usePolling<KeyStatus>("/api/admin/keys", 30000);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Security & keys</h1>
          <p className="muted">Key material never leaves the server. Fingerprints are SHA-512 prefixes of the public keys.</p>
        </div>
      </div>
      {data && (
        <div className="grid-2">
          <section className="panel pad">
            <h2>Keys</h2>
            <dl className="kv">
              <dt>Master key version</dt><dd>v{data.master_key_version}</dd>
              <dt>Patient keys by version</dt>
              <dd>{Object.entries(data.patients_by_key_version).map(([v, n]) => `v${v}: ${n}`).join(", ")}</dd>
              <dt>DH public (ingest)</dt><dd className="mono small">{data.dh_public_fingerprint}</dd>
              <dt>Audit ECDSA key</dt><dd className="mono small">{data.audit_key_fingerprint}</dd>
            </dl>
            <p className="muted small">Rotate with <code>python scripts/rotate_master_key.py</code> (re-wraps keys only, no bulk re-encryption).</p>
          </section>
          <section className="panel pad">
            <h2>Algorithms in use</h2>
            <dl className="kv">
              {Object.entries(data.algorithms).map(([k, v]) => (
                <div key={k} className="kv-row"><dt>{k.replace(/_/g, " ")}</dt><dd>{v}</dd></div>
              ))}
            </dl>
          </section>
        </div>
      )}
    </>
  );
}
