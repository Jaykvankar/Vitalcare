import { useState } from "react";
import { api, PatientProfile, timeAgo } from "../api";
import { useAuth } from "../App";
import { Monitor } from "../components/Monitor";
import { usePolling } from "../hooks";

export default function PatientHome() {
  const { me } = useAuth();
  const pid = me!.patient_id!;
  const { data: profile, reload } = usePolling<PatientProfile>(`/api/patients/${pid}`, 30000);
  const [busy, setBusy] = useState(false);

  const toggleConsent = async () => {
    if (!profile) return;
    const next = !profile.consent_active;
    if (!next && !confirm("Stop sharing? Your devices will stop uploading and your care team will lose access until you turn this back on.")) return;
    setBusy(true);
    await api("/api/me/consent", { method: "PUT", body: { active: next } }).finally(() => setBusy(false));
    reload();
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>My health</h1>
          <p className="muted">Readings from your monitor are encrypted on the device and stay encrypted in storage.</p>
        </div>
      </div>

      <Monitor patientId={pid} canAck={false} />

      <div className="grid-2">
        <section className="panel pad">
          <h2>Data sharing consent</h2>
          {profile && (
            <>
              <p>
                Status:{" "}
                <b className={profile.consent_active ? "ok-text" : "crit-text"}>{profile.consent_active ? "Sharing with my care team" : "Not sharing"}</b>
                <span className="muted small"> · changed {timeAgo(profile.consent_changed_at)}</span>
              </p>
              <p className="muted small">
                When sharing is off, new readings are rejected and clinicians cannot decrypt your record. You can still see your own history.
              </p>
              <button className={profile.consent_active ? "danger" : "primary"} disabled={busy} onClick={toggleConsent}>
                {profile.consent_active ? "Stop sharing" : "Resume sharing"}
              </button>
            </>
          )}
        </section>
        <section className="panel pad">
          <h2>My devices & details</h2>
          {profile && (
            <>
              <ul className="plain">
                {profile.devices.map((d) => (
                  <li key={d.id}>
                    <b>{d.label}</b> <span className="muted small">{d.id} · last seen {timeAgo(d.last_seen)}</span>
                  </li>
                ))}
              </ul>
              <dl className="kv">
                <dt>Date of birth</dt>
                <dd>{profile.dob ?? "–"}</dd>
                <dt>Phone</dt>
                <dd>{profile.phone ?? "–"}</dd>
                <dt>Address</dt>
                <dd>{profile.address ?? "–"}</dd>
              </dl>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
