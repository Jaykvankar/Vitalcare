import { useState } from "react";
import { api, ApiError } from "../api";
import { CsvPicker } from "./CsvUpload";
import { Icon } from "./Icons";

const SAMPLE = [
  "timestamp,hr,spo2,sbp,dbp,temp,rr",
  "2026-11-01T08:00:00Z,78,97,124,79,36.8,15",
  "2026-11-01T08:15:00Z,80,97,122,78,36.9,16",
  "2026-11-01T08:30:00Z,83,96,126,80,37.0,16",
  "",
].join("\n");

interface Result { committed: boolean; rows: number; valid: number; invalid: number; errors: { line: number; error: string }[]; from: string | null; to: string | null; bands?: Record<string, number> }

export function ImportHistoryModal({ patientId, patientName, onClose }: { patientId: number; patientName: string; onClose: () => void }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (csv: string, commit: boolean) => {
    setErr("");
    setBusy(true);
    try {
      setRes(await api<Result>(`/api/patients/${patientId}/import/vitals`, { method: "POST", body: { csv, commit } }));
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-labelledby="imp-title" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <div><h2 id="imp-title">Import past vital signs</h2><div className="sub">for {patientName}</div></div>
          <button className="btn ghost sm" aria-label="Close" onClick={onClose}><Icon.X size={16} /></button>
        </div>
        <div className="card-body form">
          {res?.committed ? (
            <div className="notice success"><Icon.Check size={18} />
              <div>Imported {res.valid} readings ({res.bands?.critical ?? 0} critical, {res.bands?.warning ?? 0} warning). They are encrypted with this patient's key, marked as a historical import by you, and recorded in the privacy ledger. No alerts were raised for past data.</div>
            </div>
          ) : (
            <>
              <CsvPicker sample={SAMPLE} sampleName="vitalcare-vitals-template.csv" onText={(t) => { setText(t); send(t, false); }} />
              <p className="muted small">Columns: <code>timestamp</code> (ISO 8601 or Unix seconds), <code>hr, spo2, sbp, dbp, temp, rr</code>. Up to 20,000 rows. Imported readings are scored on their own baseline so they never disturb live monitoring.</p>
              {err && <div className="notice error">{err}</div>}
              {res && (
                <>
                  <div className={`notice ${res.invalid ? "error" : "info"}`}>
                    {res.invalid ? <Icon.Alert size={18} /> : <Icon.Check size={18} />}
                    <div>
                      {res.valid} valid rows{res.from && ` from ${new Date(res.from).toLocaleString()} to ${new Date(res.to!).toLocaleString()}`}. {res.invalid > 0 && `${res.invalid} rows have problems:`}
                      {res.errors.length > 0 && <ul>{res.errors.slice(0, 8).map((e) => <li key={e.line}>Line {e.line}: {e.error}</li>)}</ul>}
                    </div>
                  </div>
                  <button className="btn primary" disabled={busy || res.invalid > 0 || res.valid === 0} onClick={() => send(text, true)}>
                    {busy ? "Importing…" : `Import ${res.valid} readings`}
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
