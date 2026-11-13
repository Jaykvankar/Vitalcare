import { useState } from "react";
import { api, PatientProfile, saveFile, timeAgo } from "../api";
import { useAuth } from "../App";
import { Icon } from "../components/Icons";
import { Monitor, PatientHeader } from "../components/Monitor";
import { usePolling } from "../hooks";

export default function PatientHome() {
  const { me } = useAuth();
  const pid = me!.patient_id!;
  const { data: p, reload } = usePolling<PatientProfile>(`/api/patients/${pid}`, 30000);
  const [busy, setBusy] = useState(false);

  const exportData = async () => {
    const data = await api("/api/me/export");
    saveFile(`securerpm-my-data-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(data, null, 2));
  };

  const toggleConsent = async () => {
    if (!p) return;
    const next = !p.consent_active;
    if (!next && !confirm("Pause sharing? Your devices will stop uploading and your care team will lose access until you resume.")) return;
    setBusy(true);
    await api("/api/me/consent", { method: "PUT", body: { active: next } }).finally(() => setBusy(false));
    reload();
  };

  const side = p && (
    <>
      <div className="card pad">
        <div className="row">
          <h2>Sharing with my care team</h2>
          <span className="spacer" />
          <span className={`tag ${p.consent_active ? "ok" : "danger"}`}>{p.consent_active ? "On" : "Paused"}</span>
        </div>
        <p className="muted small" style={{ margin: "8px 0 14px" }}>
          When paused, new readings are rejected and clinicians cannot decrypt your record. You can still see your own history. Changed {timeAgo(p.consent_changed_at)}.
        </p>
        <button className={`btn ${p.consent_active ? "danger" : "primary"}`} disabled={busy} onClick={toggleConsent}>
          {p.consent_active ? "Pause sharing" : "Resume sharing"}
        </button>
      </div>
      <div className="card pad">
        <h2>My devices</h2>
        <ul className="device-list" style={{ marginTop: 12 }}>
          {p.devices.filter((d) => d.active).map((d) => (
            <li key={d.id}>
              <span className="ico"><Icon.Watch size={17} /></span>
              <div className="info"><b>{d.label}</b><span>Last seen {timeAgo(d.last_seen)}</span></div>
            </li>
          ))}
        </ul>
        <p className="muted xs" style={{ marginTop: 10 }}>To add a device, ask your clinician for a pairing code.</p>
      </div>
      <div className="card pad">
        <h2>My details</h2>
        <dl className="kv" style={{ marginTop: 12 }}>
          <dt>Date of birth</dt><dd>{p.dob ?? "–"}</dd>
          <dt>Phone</dt><dd>{p.phone ?? "–"}</dd>
          <dt>Address</dt><dd>{p.address ?? "–"}</dd>
        </dl>
        <p className="muted xs" style={{ marginTop: 10 }}>Stored encrypted with a key unique to you.</p>
      </div>
    </>
  );

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Your health</div>
          <h1>Hello, {me!.full_name.split(" ")[0]}</h1>
          <p className="sub">Readings from your monitor are encrypted on the device and stay encrypted in storage.</p>
        </div>
        <button className="btn secondary" onClick={exportData}><Icon.Database size={16} /> Download my data</button>
      </div>
      {p && <PatientHeader p={p} />}
      {p && <Monitor patientId={pid} patientName={p.name} canAck={false} side={side} />}
    </div>
  );
}
