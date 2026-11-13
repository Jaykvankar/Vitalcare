import { useNavigate } from "react-router-dom";
import { PatientSummary, timeAgo } from "../api";
import { BandBadge } from "../components/Monitor";
import { usePolling } from "../hooks";

export default function Worklist() {
  const { data, error } = usePolling<PatientSummary[]>("/api/patients", 5000);
  const nav = useNavigate();
  const counts = { critical: 0, warning: 0, normal: 0 };
  data?.forEach((p) => p.band && (counts[p.band] += 1));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Worklist</h1>
          <p className="muted">Your assigned patients, highest risk first. Updates every 5 seconds.</p>
        </div>
        <div className="summary">
          <span className="pill critical">{counts.critical} critical</span>
          <span className="pill warning">{counts.warning} warning</span>
          <span className="pill normal">{counts.normal} stable</span>
        </div>
      </div>
      {error && <div className="error banner">{error.message}</div>}
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>Patient</th>
              <th>Status</th>
              <th className="num">AI risk</th>
              <th className="num">Open alerts</th>
              <th>Last reading</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((p) => (
              <tr key={p.id} className={`clickable row-${p.band}`} onClick={() => nav(`/patients/${p.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(`/patients/${p.id}`)}>
                <td>
                  <b>{p.name}</b>
                  {!p.consent_active && <span className="tag">consent revoked</span>}
                </td>
                <td>
                  <BandBadge band={p.band} />
                </td>
                <td className="num">{p.risk === null ? "–" : `${Math.round(p.risk * 100)}%`}</td>
                <td className="num">{p.open_alerts || "–"}</td>
                <td className="muted">{timeAgo(p.last_reading_at)}</td>
              </tr>
            ))}
            {data && data.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  No patients assigned to you yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
