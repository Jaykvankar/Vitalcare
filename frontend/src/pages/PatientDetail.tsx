import { Link, useParams } from "react-router-dom";
import { PatientProfile } from "../api";
import { Icon } from "../components/Icons";
import { DevicesCard, Monitor, PatientHeader } from "../components/Monitor";
import { usePolling } from "../hooks";

export default function PatientDetail() {
  const id = Number(useParams().id);
  const { data: p, error } = usePolling<PatientProfile>(`/api/patients/${id}`, 15000);

  if (error) return <div className="page"><div className="notice error">{error.message}</div></div>;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <Link to="/worklist" className="back"><Icon.ArrowLeft size={15} /> Worklist</Link>
          <h1 style={{ marginTop: 10 }}>Patient record</h1>
          <p className="sub">Decrypted for you because you are on this patient's care team. This view is recorded in the privacy ledger.</p>
        </div>
      </div>
      {p && <PatientHeader p={p} />}
      {p && !p.consent_active ? (
        <div className="card pad">
          <h2>Patient has paused data sharing</h2>
          <p className="muted" style={{ marginTop: 6 }}>Readings cannot be decrypted and new uploads are rejected until the patient turns sharing back on.</p>
        </div>
      ) : (
        p && <Monitor patientId={id} patientName={p.name} canAck side={<DevicesCard patientId={id} patientName={p.name} canManage />} />
      )}
    </div>
  );
}
