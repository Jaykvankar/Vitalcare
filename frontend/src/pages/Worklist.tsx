import { useNavigate } from "react-router-dom";
import { PatientSummary, sourceInfo, timeAgo } from "../api";
import { Icon, initials } from "../components/Icons";
import { BandBadge, SourceChip } from "../components/Monitor";
import { usePolling } from "../hooks";

export default function Worklist() {
  const { data, error } = usePolling<PatientSummary[]>("/api/patients", 5000);
  const nav = useNavigate();
  const counts = { critical: 0, warning: 0, normal: 0 };
  data?.forEach((p) => p.band && (counts[p.band] += 1));
  const openAlerts = data?.reduce((n, p) => n + p.open_alerts, 0) ?? 0;
  const escalated = data?.reduce((n, p) => n + p.escalated_alerts, 0) ?? 0;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Care workspace</div>
          <h1>Patient worklist</h1>
          <p className="sub">Your assigned patients, most urgent first. Updates every 5 seconds.</p>
        </div>
      </div>

      <div className="stats">
        <div className="card stat critical"><div className="label"><Icon.Alert size={15} /> Critical</div><div className="num">{counts.critical}</div></div>
        <div className="card stat warning"><div className="label"><Icon.Score size={15} /> Needs attention</div><div className="num">{counts.warning}</div></div>
        <div className="card stat normal"><div className="label"><Icon.Check size={15} /> Stable</div><div className="num">{counts.normal}</div></div>
        <div className="card stat"><div className="label"><Icon.Inbox size={15} /> Open alerts</div><div className="num">{openAlerts}</div></div>
      </div>

      {escalated > 0 && (
        <div className="notice error" role="alert"><Icon.Alert size={18} />
          <div><b>{escalated} critical alert{escalated === 1 ? " has" : "s have"} been waiting more than 15 minutes.</b> Open the highlighted patients and acknowledge or act.</div>
        </div>
      )}
      {error && <div className="notice error">{error.message}</div>}
      <div className="card scroll-x">
        <table className="table">
          <thead>
            <tr>
              <th>Patient</th>
              <th>Status</th>
              <th>AI risk</th>
              <th className="num">Open alerts</th>
              <th>Last reading</th>
              <th>Data</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((p) => {
              const risk = p.risk === null ? null : Math.round(p.risk * 100);
              return (
                <tr key={p.id} className="clickable" tabIndex={0} onClick={() => nav(`/patients/${p.id}`)} onKeyDown={(e) => e.key === "Enter" && nav(`/patients/${p.id}`)}>
                  <td>
                    <div className="person">
                      <span className="avatar">{initials(p.name)}</span>
                      <div><b>{p.name}</b><span>P-{String(p.id).padStart(4, "0")}{!p.consent_active && " · sharing paused"}</span></div>
                    </div>
                  </td>
                  <td><BandBadge band={p.band} /></td>
                  <td>
                    {risk === null ? <span className="muted">–</span> : (
                      <div className="risk-cell">
                        <span className="tnum" style={{ width: 36 }}>{risk}%</span>
                        <div className={`meter ${risk >= 60 ? "critical" : risk >= 30 ? "warning" : ""}`}><i style={{ width: `${risk}%` }} /></div>
                      </div>
                    )}
                  </td>
                  <td className="num">{p.open_alerts || <span className="muted">–</span>}{p.escalated_alerts > 0 && <span className="tag danger" style={{ marginLeft: 6 }}>Escalated</span>}</td>
                  <td className="muted">{timeAgo(p.last_reading_at)}</td>
                  <td title={sourceInfo(p.data_source).detail}><SourceChip source={p.data_source} /></td>
                </tr>
              );
            })}
            {data && data.length === 0 && (
              <tr><td colSpan={6} className="empty">No patients are assigned to you yet. Ask an administrator to add you to a care team.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
