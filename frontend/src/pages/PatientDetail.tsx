import { Link, useParams } from "react-router-dom";
import { PatientProfile } from "../api";
import { BandBadge, Monitor } from "../components/Monitor";
import { usePolling } from "../hooks";

export default function PatientDetail() {
  const id = Number(useParams().id);
  const { data: p, error } = usePolling<PatientProfile>(`/api/patients/${id}`, 15000);

  if (error) return <div className="page"><div className="error banner">{error.message}</div></div>;
  return (
    <div className="page">
      <Link to="/worklist" className="back">← Worklist</Link>
      <div className="page-head">
        <div>
          <h1>
            {p?.name ?? "Patient"} {p && <BandBadge band={p.band} />}
          </h1>
          {p && (
            <p className="muted">
              DOB {p.dob ?? "–"} · {p.phone ?? "–"} · {p.devices.map((d) => d.label).join(", ") || "no devices"}
            </p>
          )}
        </div>
      </div>
      {p && !p.consent_active ? (
        <div className="panel pad">
          <h2>Consent revoked</h2>
          <p className="muted">This patient has stopped sharing data. Readings cannot be decrypted until they turn sharing back on.</p>
        </div>
      ) : (
        <Monitor patientId={id} canAck />
      )}
    </div>
  );
}
