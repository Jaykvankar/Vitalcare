import { FormEvent, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, ApiError, sourceInfo } from "../api";
import { usePolling } from "../hooks";
import { Icon, initials } from "../components/Icons";
import { DevicesCard, SourceChip } from "../components/Monitor";
import { CsvPicker } from "../components/CsvUpload";
import { saveFile } from "../api";

interface UserRow { id: number; username: string; full_name: string; role: string; active: boolean; mfa_enrolled: boolean; patient_id: number | null }
interface PatientRow { id: number; name: string; username: string; consent_active: boolean; key_version: number; devices: { id: string; label: string }[]; simulating: boolean; simulator_status: string | null; source: string | null }
interface AssignmentRow { id: number; clinician_id: number; clinician: string; patient_id: number; patient: string }
interface AuditRow { id: number; ts: string; actor: string; action: string; target: string; detail: string; hash: string }
interface VerifyResult { ok: boolean; rows: number; checkpoints: number; anchored_through_row: number; unanchored_rows: number; problems: string[] }
interface Source { id: string; label: string; detail: string }

function Head({ eyebrow, title, sub, children }: { eyebrow: string; title: string; sub: string; children?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p className="sub">{sub}</p>
      </div>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

export default function Admin() {
  return (
    <div className="page">
      <Routes>
        <Route path="users" element={<Users />} />
        <Route path="import" element={<BulkImport />} />
        <Route path="assignments" element={<Assignments />} />
        <Route path="devices" element={<Devices />} />
        <Route path="simulator" element={<Simulator />} />
        <Route path="audit" element={<Audit />} />
        <Route path="security" element={<Security />} />
        <Route path="*" element={<Navigate to="users" replace />} />
      </Routes>
    </div>
  );
}

/* ---------------------------------------------------------------- people */

function Users() {
  const { data, reload } = usePolling<UserRow[]>("/api/admin/users", 15000);
  const empty = { username: "", full_name: "", role: "patient", password: "", dob: "", phone: "", address: "" };
  const [f, setF] = useState(empty);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [erase, setErase] = useState<UserRow | null>(null);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setMsg(null);
    try {
      const body = { ...f, dob: f.dob || null, phone: f.phone || null, address: f.address || null };
      await api("/api/admin/users", { method: "POST", body });
      setMsg({ ok: true, text: `${f.full_name} was added.${f.role !== "patient" ? " They will set up two-step sign-in the first time they log in." : " A simulated monitor was paired for them."}` });
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
      <Head eyebrow="Administration" title="People" sub="Create and manage accounts. Administrators cannot see vital signs or personal health details." />
      <div className="grid side-main">
        <div className="card scroll-x">
          <table className="table">
            <thead><tr><th>Name</th><th>Role</th><th>Two-step</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data?.map((u) => (
                <tr key={u.id}>
                  <td><div className="person"><span className="avatar">{initials(u.full_name)}</span><div><b>{u.full_name}</b><span className="mono">{u.username}</span></div></div></td>
                  <td><span className="tag">{u.role}</span></td>
                  <td>{u.role === "patient" ? <span className="faint">Not required</span> : u.mfa_enrolled ? <span className="tag ok">Enrolled</span> : <span className="tag">Pending</span>}</td>
                  <td>{u.active ? "Active" : <span className="tag danger">Disabled</span>}</td>
                  <td className="actions">
                    {u.role !== "patient" && u.mfa_enrolled && <button className="btn ghost sm" onClick={() => act(`/api/admin/users/${u.id}/reset-mfa`)}>Reset two-step</button>}
                    {u.role !== "admin" && <button className="btn ghost sm" onClick={() => act(`/api/admin/users/${u.id}/active`, { active: !u.active })}>{u.active ? "Disable" : "Enable"}</button>}
                    {u.role === "patient" && u.patient_id && u.active && <button className="btn danger sm" onClick={() => setErase(u)}>Erase</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form className="card pad form" onSubmit={create}>
          <h2>Add a person</h2>
          <label className="field">Full name<input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required /></label>
          <label className="field">Username<input value={f.username} pattern="[a-zA-Z0-9_.\-]{3,64}" onChange={(e) => setF({ ...f, username: e.target.value })} required /></label>
          <label className="field">Role
            <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="patient">Patient</option>
              <option value="clinician">Clinician</option>
              <option value="admin">Administrator</option>
            </select>
          </label>
          <label className="field">Initial password <span className="hint">At least 12 characters</span><input type="password" minLength={12} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required /></label>
          {f.role === "patient" && (
            <>
              <label className="field">Date of birth<input type="date" value={f.dob} onChange={(e) => setF({ ...f, dob: e.target.value })} /></label>
              <label className="field">Phone<input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></label>
              <label className="field">Address<input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></label>
              <p className="muted xs">Personal details are encrypted with the patient's own AES-256 key.</p>
            </>
          )}
          {msg && <div className={`notice ${msg.ok ? "success" : "error"}`}>{msg.text}</div>}
          <button className="btn primary">Add person</button>
        </form>
      </div>
      {erase && <EraseModal user={erase} onClose={() => { setErase(null); reload(); }} />}
    </>
  );
}

function EraseModal({ user, onClose }: { user: UserRow; onClose: () => void }) {
  const [typed, setTyped] = useState("");
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);
  const go = async () => {
    setErr("");
    try {
      await api(`/api/admin/patients/${user.patient_id}/erase`, { method: "POST", body: { confirm_username: typed } });
      setDone(true);
    } catch (e) {
      setErr((e as ApiError).message);
    }
  };
  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="erase-title" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <div><h2 id="erase-title">Erase {user.full_name}</h2><div className="sub">Right to erasure · cannot be undone</div></div>
          <button className="btn ghost sm" aria-label="Close" onClick={onClose}><Icon.X size={16} /></button>
        </div>
        <div className="card-body form">
          {done ? (
            <div className="notice success"><Icon.Check size={18} /> The patient's key was destroyed. Their readings, notes and personal details can no longer be decrypted by anyone.</div>
          ) : (
            <>
              <p className="small">This destroys the patient's own AES-256 key (<b>crypto-shredding</b>). Every reading, rollup, note and personal detail was encrypted with it, so all of it becomes permanently unreadable at once. The account is disabled, devices are revoked and care-team links are removed.</p>
              <div className="notice error"><Icon.Alert size={18} /><div>Copies in old database backups stay readable until those backups expire or the master key used for them is retired.</div></div>
              <label className="field">Type <code>{user.username}</code> to confirm<input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" /></label>
              {err && <div className="notice error">{err}</div>}
              <button className="btn danger" disabled={typed !== user.username} onClick={go}>Erase permanently</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- bulk import */

const PEOPLE_SAMPLE = [
  "username,full_name,role,dob,phone,address,care_team",
  "dr.sen,Dr. Arjun Sen,clinician,,,,",
  "nurse.roy,Nisha Roy,clinician,,,,",
  "p.verma,Kavita Verma,patient,1962-08-19,+91 98000 11111,22 Ring Road Delhi,dr.sen;nurse.roy",
  "p.nair,Suresh Nair,patient,1955-01-07,+91 98000 22222,5 Beach Road Kochi,dr.sen",
  "",
].join("\n");

interface PreviewRow { line: number; username: string; full_name: string; role: string; care_team: string[]; errors: string[] }
interface Batch { id: string; kind: string; rows: number; by: string; patient: string | null; sha512: string; created_at: string }
interface PeopleResult { committed: boolean; rows: PreviewRow[]; valid?: number; invalid?: number; created?: number; credentials_csv?: string }

function BulkImport() {
  const [text, setText] = useState("");
  const [rows, setRows] = useState<PreviewRow[] | null>(null);
  const [counts, setCounts] = useState<{ valid: number; invalid: number } | null>(null);
  const [result, setResult] = useState<{ created: number; credentials_csv: string } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: batches, reload } = usePolling<Batch[]>("/api/admin/import/batches", 30000);

  const send = async (csv: string, commit: boolean) => {
    setErr("");
    setBusy(true);
    try {
      const r = await api<PeopleResult>("/api/admin/import/people", { method: "POST", body: { csv, commit } });
      setRows(r.rows);
      if (r.committed) {
        setResult({ created: r.created!, credentials_csv: r.credentials_csv! });
        setCounts(null);
        reload();
      } else setCounts({ valid: r.valid!, invalid: r.invalid! });
    } catch (e) {
      setErr((e as ApiError).message);
      setRows(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Head eyebrow="Administration" title="Bulk import" sub="Onboard a hospital's staff and patients from one CSV file. Every row is checked first; nothing is created until the whole file is valid." />
      {!result && (
        <CsvPicker sample={PEOPLE_SAMPLE} sampleName="securerpm-people-template.csv" onText={(t) => { setText(t); send(t, false); }} />
      )}
      {err && <div className="notice error">{err}</div>}
      {result && (
        <div className="card pad form">
          <div className="notice success"><Icon.Check size={18} /> Created {result.created} accounts. Everyone gets a temporary password and must choose their own at first sign-in. Staff set up two-step sign-in then.</div>
          <div className="notice error"><Icon.Alert size={18} /><div>Download the temporary passwords now and hand them out securely. They are shown only once and are not stored anywhere.</div></div>
          <div className="row">
            <button className="btn primary" onClick={() => saveFile("securerpm-temporary-passwords.csv", result.credentials_csv, "text/csv")}>Download temporary passwords</button>
            <button className="btn ghost" onClick={() => { setResult(null); setRows(null); setText(""); }}>Import another file</button>
          </div>
        </div>
      )}
      {rows && !result && counts && (
        <div className="card">
          <div className="card-head">
            <div><h2>Preview</h2><div className="sub">{counts.valid} ready · {counts.invalid} with problems</div></div>
            <button className="btn primary" disabled={busy || counts.invalid > 0} onClick={() => send(text, true)}>
              {busy ? "Creating…" : counts.invalid > 0 ? "Fix the errors to continue" : `Create ${counts.valid} accounts`}
            </button>
          </div>
          <div className="scroll-x" style={{ marginTop: 14 }}>
            <table className="table compact">
              <thead><tr><th>Line</th><th>Username</th><th>Name</th><th>Role</th><th>Care team</th><th>Check</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.line}>
                    <td className="faint">{r.line}</td>
                    <td className="mono">{r.username}</td>
                    <td>{r.full_name}</td>
                    <td><span className="tag">{r.role}</span></td>
                    <td className="small">{r.care_team.join(", ") || <span className="faint">–</span>}</td>
                    <td>{r.errors.length ? <span className="crit-text small">{r.errors.join("; ")}</span> : <span className="tag ok">OK</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <div className="grid two">
        <div className="card pad">
          <h2>File format</h2>
          <ul className="steps" style={{ marginTop: 10 }}>
            <li>Columns: <code>username, full_name, role, dob, phone, address, care_team</code></li>
            <li><code>role</code> is patient, clinician or admin. <code>dob</code> is YYYY-MM-DD.</li>
            <li><code>care_team</code> lists clinician usernames separated by <code>;</code> (they can be in the same file).</li>
            <li>Up to 500 rows per file. Patient details are encrypted with each patient's own key.</li>
            <li>Past vital signs are imported per patient by their clinician, from the patient record.</li>
          </ul>
        </div>
        <div className="card scroll-x">
          <div className="card-head"><div><h2>Recent imports</h2><div className="sub">File fingerprints are SHA-512 prefixes</div></div></div>
          <table className="table compact" style={{ marginTop: 12 }}>
            <thead><tr><th>When</th><th>Type</th><th className="num">Rows</th><th>By</th><th>File SHA-512</th></tr></thead>
            <tbody>
              {batches?.map((b) => (
                <tr key={b.id}>
                  <td className="small">{new Date(b.created_at).toLocaleString()}</td>
                  <td>{b.kind}{b.patient && ` · ${b.patient}`}</td>
                  <td className="num">{b.rows}</td>
                  <td className="small">{b.by}</td>
                  <td className="mono xs faint">{b.sha512}…</td>
                </tr>
              ))}
              {batches && batches.length === 0 && <tr><td colSpan={5} className="empty">No imports yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}


/* ---------------------------------------------------------------- care teams */

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
      <Head eyebrow="Administration" title="Care teams" sub="A clinician can decrypt a patient's data, pair devices and acknowledge alerts only while assigned." />
      <form className="card pad" onSubmit={add}>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label className="field" style={{ flex: "1 1 220px" }}>Clinician
            <select value={c} onChange={(e) => setC(e.target.value)} required>
              <option value="">Select a clinician</option>
              {clinicians.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
            </select>
          </label>
          <label className="field" style={{ flex: "1 1 220px" }}>Patient
            <select value={p} onChange={(e) => setP(e.target.value)} required>
              <option value="">Select a patient</option>
              {patients?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </label>
          <button className="btn primary"><Icon.Plus size={16} /> Assign</button>
        </div>
        {err && <div className="notice error" style={{ marginTop: 12 }}>{err}</div>}
      </form>
      <div className="card scroll-x">
        <table className="table">
          <thead><tr><th>Clinician</th><th>Patient</th><th /></tr></thead>
          <tbody>
            {rows?.map((a) => (
              <tr key={a.id}>
                <td><div className="person"><span className="avatar">{initials(a.clinician)}</span><b>{a.clinician}</b></div></td>
                <td><div className="person"><span className="avatar">{initials(a.patient)}</span><b>{a.patient}</b></div></td>
                <td className="actions"><button className="btn ghost sm" onClick={() => remove(a.id)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- devices */

function Devices() {
  const { data: patients } = usePolling<PatientRow[]>("/api/admin/patients", 30000);
  const [pid, setPid] = useState<number | null>(null);
  const selected = patients?.find((p) => p.id === pid) ?? patients?.[0];
  return (
    <>
      <Head eyebrow="Administration" title="Devices & pairing" sub="Pair a monitor to a patient with a one-time code. The device keeps its private key; the server stores only the public key." />
      <div className="grid side-main">
        <div className="card scroll-x">
          <table className="table">
            <thead><tr><th>Patient</th><th className="num">Active devices</th><th>Data</th></tr></thead>
            <tbody>
              {patients?.map((p) => (
                <tr key={p.id} className="clickable" onClick={() => setPid(p.id)} style={selected?.id === p.id ? { background: "var(--surface-2)" } : undefined}>
                  <td><div className="person"><span className="avatar">{initials(p.name)}</span><div><b>{p.name}</b><span className="mono">{p.username}</span></div></div></td>
                  <td className="num">{p.devices.length}</td>
                  <td><SourceChip source={p.source ?? undefined} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selected && <DevicesCard key={selected.id} patientId={selected.id} patientName={selected.name} canManage />}
      </div>
      <div className="card pad">
        <h2>How pairing works</h2>
        <ol className="steps" style={{ marginTop: 10 }}>
          <li>An administrator, or a clinician on the patient's care team, creates a one-time code (valid 10 minutes).</li>
          <li>The code is entered on the device. The device generates its own RSA-3072 key pair and sends its public key with an HMAC-SHA-512 proof of the code; the code itself never crosses the network.</li>
          <li>Five wrong proofs burn the code. A used code cannot be reused. Revoked devices are rejected at ingest immediately.</li>
        </ol>
        <p className="muted small" style={{ marginTop: 10 }}>Command-line device: <code>python scripts/device_client.py pair --pairing-id ID --code CODE</code>, then <code>stream</code>.</p>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- data sources / simulator */

const EPISODES = ["hypoxia", "tachycardia", "hypotension", "fever", "activity"];

function Simulator() {
  const { data, reload } = usePolling<PatientRow[]>("/api/admin/patients", 4000);
  const { data: src } = usePolling<{ available: { mimic: boolean; bidmc: boolean }; sources: Source[] }>("/api/admin/simulator/sources", 60000);
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);

  const call = async (path: string, body: unknown, ok: string) => {
    try {
      await api(path, { method: "POST", body });
      setFlash({ ok: true, text: ok });
      reload();
    } catch (e) {
      setFlash({ ok: false, text: (e as ApiError).message });
    }
  };
  const all = async (on: boolean) => {
    for (const p of data ?? []) if (p.consent_active && p.devices.length) await api("/api/admin/simulator", { method: "POST", body: { patient_id: p.id, enabled: on } });
    reload();
  };

  return (
    <>
      <Head eyebrow="Administration" title="Data sources" sub="Simulated monitors post sealed, signed readings to the real ingest API every 5 seconds. Each can play synthetic data or replay a real, de-identified ICU recording.">
        <button className="btn secondary" onClick={() => all(true)}><Icon.Play size={16} /> Start all</button>
        <button className="btn ghost" onClick={() => all(false)}>Stop all</button>
      </Head>
      <div className="grid two">
        <div className="card pad">
          <div className="row"><Icon.Database size={18} /><h2>MIMIC-III Clinical Demo</h2><span className="spacer" />{src?.available.mimic ? <span className="tag ok">Loaded</span> : <span className="tag">Not downloaded</span>}</div>
          <p className="muted small" style={{ marginTop: 8 }}>100 real ICU patients (PhysioNet, ODbL). Hourly charted heart rate, SpO₂, respiration, blood pressure and temperature. Replayed one hour per tick.</p>
        </div>
        <div className="card pad">
          <div className="row"><Icon.Database size={18} /><h2>BIDMC PPG & Respiration</h2><span className="spacer" />{src?.available.bidmc ? <span className="tag ok">Loaded</span> : <span className="tag">Not downloaded</span>}</div>
          <p className="muted small" style={{ marginTop: 8 }}>53 real ICU recordings at 1 Hz (PhysioNet, ODC-BY). Heart rate, SpO₂ and respiration only; blood pressure and temperature are held fixed.</p>
        </div>
      </div>
      {flash && <div className={`notice ${flash.ok ? "success" : "error"}`}>{flash.text}</div>}
      <div className="card scroll-x">
        <table className="table">
          <thead><tr><th>Patient</th><th>Data source</th><th>Streaming</th><th>Last upload</th><th>Inject episode</th></tr></thead>
          <tbody>
            {data?.map((p) => {
              const s = sourceInfo(p.source ?? undefined);
              return (
                <tr key={p.id}>
                  <td><div className="person"><span className="avatar">{initials(p.name)}</span><div><b>{p.name}</b><span>{p.consent_active ? `${p.devices.length} device(s)` : "sharing paused"}</span></div></div></td>
                  <td style={{ minWidth: 240 }}>
                    <select value={p.source ?? "synthetic"} disabled={!p.devices.length}
                      onChange={(e) => call("/api/admin/simulator/source", { patient_id: p.id, source: e.target.value }, `${p.name} now uses ${e.target.selectedOptions[0].text}.`)}>
                      {(src?.sources ?? [{ id: "synthetic", label: "Synthetic generator", detail: "" }]).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
                    </select>
                    <div className="muted xs" style={{ marginTop: 4 }}>{s.detail}</div>
                  </td>
                  <td>
                    <label className="switch">
                      <input type="checkbox" checked={p.simulating} disabled={!p.devices.length} onChange={() => call("/api/admin/simulator", { patient_id: p.id, enabled: !p.simulating }, `Streaming ${p.simulating ? "stopped" : "started"} for ${p.name}.`)} />
                      <span className="track" />
                      {p.simulating ? "On" : "Off"}
                    </label>
                  </td>
                  <td className="small">{p.simulator_status === "ok" ? <span className="tag ok">Accepted</span> : p.simulator_status ? <span className="tag danger" title={p.simulator_status}>{p.simulator_status.slice(0, 32)}</span> : <span className="faint">–</span>}</td>
                  <td style={{ minWidth: 150 }}>
                    <select defaultValue="" disabled={!p.simulating || s.kind === "real"} title={s.kind === "real" ? "Episodes cannot be injected into real recordings" : ""}
                      onChange={(e) => { const k = e.target.value; if (k) { call("/api/admin/simulator/episode", { patient_id: p.id, kind: k }, `Started a ${k} episode for ${p.name}. It develops over the next few minutes.`); e.target.value = ""; } }}>
                      <option value="">{s.kind === "real" ? "Real data" : "Choose…"}</option>
                      {EPISODES.map((k) => <option key={k} value={k}>{k}</option>)}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- audit */

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
      <Head eyebrow="Administration" title="Privacy ledger" sub="Every sign-in, decryption, consent change and pairing, append-only. Each row stores the SHA-512 of the previous row; checkpoints are signed with the server's ECDSA P-384 key.">
        <button className="btn ghost" onClick={checkpoint}><Icon.Key size={16} /> Sign checkpoint</button>
        <button className="btn primary" onClick={verify} disabled={busy}><Icon.Shield size={16} /> {busy ? "Verifying…" : "Verify integrity"}</button>
      </Head>
      {result && (
        <div className={`notice ${result.ok ? "success" : "error"}`}>
          {result.ok ? <Icon.Check size={18} /> : <Icon.Alert size={18} />}
          <div>
            <b>{result.ok ? "Ledger intact." : "Tampering detected."}</b> {result.rows} rows, {result.checkpoints} signed checkpoints, anchored through row {result.anchored_through_row}
            {result.unanchored_rows > 0 && ` (${result.unanchored_rows} newer rows await the next checkpoint)`}.
            {result.problems.length > 0 && <ul>{result.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          </div>
        </div>
      )}
      <div className="card scroll-x">
        <table className="table compact">
          <thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Detail</th><th>Hash</th></tr></thead>
          <tbody>
            {data?.map((r) => (
              <tr key={r.id}>
                <td className="num faint">{r.id}</td>
                <td className="small" style={{ whiteSpace: "nowrap" }}>{new Date(r.ts).toLocaleString()}</td>
                <td>{r.actor}</td>
                <td><span className="tag mono">{r.action}</span></td>
                <td className="small">{r.target}</td>
                <td className="small muted">{r.detail}</td>
                <td className="mono xs faint">{r.hash}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- keys */

interface KeyStatus { master_key_version: number; patients_by_key_version: Record<string, number>; dh_public_fingerprint: string; audit_key_fingerprint: string; algorithms: Record<string, string> }

function Security() {
  const { data } = usePolling<KeyStatus>("/api/admin/keys", 30000);
  return (
    <>
      <Head eyebrow="Administration" title="Keys & algorithms" sub="Private keys never leave the server. Fingerprints are SHA-512 prefixes of the public keys." />
      {data && (
        <div className="grid two">
          <div className="card pad">
            <h2>Key material</h2>
            <dl className="kv" style={{ marginTop: 14 }}>
              <dt>Master key</dt><dd>Version {data.master_key_version}</dd>
              <dt>Patient keys</dt><dd>{Object.entries(data.patients_by_key_version).map(([v, n]) => `${n} on v${v}`).join(", ")}</dd>
              <dt>Ingest DH key</dt><dd className="mono xs">{data.dh_public_fingerprint}</dd>
              <dt>Ledger ECDSA key</dt><dd className="mono xs">{data.audit_key_fingerprint}</dd>
            </dl>
            <p className="muted small" style={{ marginTop: 14 }}>Rotate with <code>python scripts/rotate_master_key.py</code>. Only wrapped keys change; readings are not re-encrypted.</p>
          </div>
          <div className="card pad">
            <h2>Algorithms in use</h2>
            <dl className="kv" style={{ marginTop: 14 }}>
              {Object.entries(data.algorithms).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}><dt style={{ textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</dt><dd>{v}</dd></div>
              ))}
            </dl>
          </div>
        </div>
      )}
    </>
  );
}
