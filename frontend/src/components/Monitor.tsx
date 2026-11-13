import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertItem, api, ApiError, Band, DeviceRow, PatientProfile, Point, Readings, REASON_LABELS, sourceInfo, timeAgo } from "../api";
import { useAuth } from "../App";
import { usePolling } from "../hooks";
import { Icon, initials } from "./Icons";

export function BandBadge({ band }: { band: Band }) {
  const label = band === "normal" ? "Stable" : band === "warning" ? "Warning" : band === "critical" ? "Critical" : "No data";
  return <span className={`badge ${band ?? "none"}`}>{label}</span>;
}

export function SourceChip({ source }: { source?: string }) {
  const s = sourceInfo(source);
  if (s.kind === "none") return null;
  return <span className={`chip ${s.kind}`} title={s.detail}>{s.label}</span>;
}

/* ---------------------------------------------------------------- header */

export function PatientHeader({ p, right }: { p: PatientProfile; right?: React.ReactNode }) {
  const s = sourceInfo(p.data_source);
  return (
    <div className="card patient-head">
      <span className="avatar">{initials(p.name)}</span>
      <div>
        <div className="name">
          {p.name} <BandBadge band={p.band} />
        </div>
        <div className="meta-line">
          <span>ID P-{String(p.id).padStart(4, "0")}</span>
          {p.dob && <span>DOB {p.dob}</span>}
          {p.phone && <span>{p.phone}</span>}
          <span>Last reading {timeAgo(p.last_reading_at)}</span>
        </div>
      </div>
      <div className="meta-cols">
        <div>
          <b>Data source</b>
          <span>{s.kind === "none" ? "No paired device" : s.detail}</span>
        </div>
        <div>
          <b>Encrypted record</b>
          <span>AES-256-GCM · own patient key</span>
        </div>
        {right && <div>{right}</div>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- vitals */

const CARDS: { key: keyof Point; label: string; unit: string; icon: keyof typeof Icon; flag: string; color: string; fmt?: (v: number) => string }[] = [
  { key: "hr", label: "Heart rate", unit: "bpm", icon: "Heart", flag: "HR", color: "var(--accent)" },
  { key: "spo2", label: "Oxygen saturation", unit: "%", icon: "Drop", flag: "SPO2", color: "var(--series-2)", fmt: (v) => v.toFixed(1) },
  { key: "rr", label: "Respiratory rate", unit: "br/min", icon: "Wind", flag: "RR", color: "var(--series-3)" },
  { key: "sbp", label: "Blood pressure", unit: "mmHg", icon: "Gauge", flag: "BP", color: "var(--accent)" },
  { key: "temp", label: "Temperature", unit: "°C", icon: "Thermo", flag: "TEMP", color: "var(--series-3)", fmt: (v) => v.toFixed(1) },
  { key: "news2", label: "NEWS2 score", unit: "of 20", icon: "Score", flag: "NEWS2", color: "var(--series-2)" },
];

function median(xs: number[]) {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : NaN;
}

function Spark({ data, k, color }: { data: Point[]; k: keyof Point; color: string }) {
  return (
    <div className="spark">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
          <YAxis hide domain={["dataMin - 1", "dataMax + 1"]} />
          <Line type="monotone" dataKey={k as string} stroke={color} strokeWidth={1.6} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function VitalCards({ latest, points }: { latest: Point | null; points: Point[] }) {
  const recent = points.slice(-60);
  if (!latest) return <div className="card empty">Waiting for the first reading from a paired device.</div>;
  const reasons = latest.reasons;
  return (
    <div className="vitals">
      {CARDS.map((c) => {
        const raw = latest[c.key] as number | undefined;
        const I = Icon[c.icon];
        const value = c.key === "sbp" ? `${Math.round(latest.sbp)}/${Math.round(latest.dbp)}` : raw === undefined ? "–" : c.fmt ? c.fmt(raw) : Math.round(raw);
        const hit = reasons.find((r) => r.startsWith(c.flag));
        const sev = hit ? (latest.band === "critical" && !hit.includes("MEDIUM") ? "critical" : "warning") : "";
        const ref = median(recent.map((p) => p[c.key] as number).filter((x) => typeof x === "number"));
        return (
          <div key={c.key} className={`card vital ${sev}`}>
            <span className="flag" />
            <div className="top">
              {c.label}
              <I size={16} />
            </div>
            <div className="value">
              {value}
              <span className="unit">{c.unit}</span>
            </div>
            <div className="ref">
              {hit ? REASON_LABELS[hit] ?? hit : Number.isFinite(ref) ? `Recent median ${c.fmt ? c.fmt(ref) : Math.round(ref)} ${c.unit}` : " "}
            </div>
            {c.key !== "news2" && recent.length > 2 && <Spark data={recent} k={c.key} color={c.color} />}
          </div>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- trend chart */

const METRICS = [
  { key: "hr", label: "Heart rate", unit: "bpm", lines: [["hr", "Heart rate", "var(--accent)"]], refs: [50, 100, 120] },
  { key: "spo2", label: "SpO₂", unit: "%", lines: [["spo2", "SpO₂", "var(--series-2)"]], refs: [92, 95] },
  { key: "rr", label: "Respiratory rate", unit: "br/min", lines: [["rr", "Resp. rate", "var(--series-3)"]], refs: [8, 20, 24] },
  { key: "bp", label: "Blood pressure", unit: "mmHg", lines: [["sbp", "Systolic", "var(--accent)"], ["dbp", "Diastolic", "var(--series-2)"]], refs: [90, 180] },
  { key: "temp", label: "Temperature", unit: "°C", lines: [["temp", "Temperature", "var(--series-3)"]], refs: [38, 38.5] },
  { key: "risk", label: "AI risk", unit: "", lines: [["risk", "Model probability", "var(--critical)"]], refs: [0.6] },
] as const;

function fmtTime(ts: number, range: string) {
  const d = new Date(ts * 1000);
  return range === "7d" ? d.toLocaleDateString(undefined, { weekday: "short", hour: "2-digit" }) : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function TrendCard({ data, range, setRange }: { data: Readings | null; range: string; setRange: (r: string) => void }) {
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("hr");
  const m = METRICS.find((x) => x.key === metric)!;
  const points = data?.points ?? [];
  const live = data?.latest && Date.now() / 1000 - data.latest.ts < 30;
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Vital signs over time</h2>
          <div className="sub">{data ? `${data.count} encrypted readings decrypted for this view` : "Loading…"}</div>
        </div>
        <div className="row">
          <span className="chip">{live ? "Live" : "Paused"}</span>
          <div className="seg" role="tablist" aria-label="Time range">
            {["6h", "24h", "7d"].map((r) => (
              <button key={r} role="tab" aria-selected={range === r} className={range === r ? "on" : ""} onClick={() => setRange(r)}>{r}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="card-body">
        <div className="tabs" role="tablist" aria-label="Vital sign">
          {METRICS.map((x) => (
            <button key={x.key} role="tab" aria-selected={metric === x.key} className={metric === x.key ? "tab on" : "tab"} onClick={() => setMetric(x.key)}>{x.label}</button>
          ))}
        </div>
        {points.length === 0 ? (
          <div className="empty">No readings in this time range.</div>
        ) : (
          <div className="chart">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={points} margin={{ top: 16, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="ts" tickFormatter={(t) => fmtTime(t, range)} stroke="var(--faint)" tick={{ fill: "var(--muted)" }} fontSize={11} minTickGap={48} tickLine={false} axisLine={false} />
                <YAxis stroke="var(--faint)" tick={{ fill: "var(--muted)" }} fontSize={11} domain={["auto", "auto"]} width={44} tickLine={false} axisLine={false} />
                <Tooltip
                  labelFormatter={(t) => new Date(Number(t) * 1000).toLocaleString()}
                  formatter={(v: number, name) => [`${Number(v).toFixed(m.key === "risk" ? 2 : 1)} ${m.unit}`, name]}
                  contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "var(--shadow-lg)", color: "var(--ink)" }}
                  labelStyle={{ color: "var(--muted)" }}
                />
                {m.refs.map((r) => (
                  <ReferenceLine key={r} y={r} stroke="var(--warning)" strokeDasharray="4 4" strokeOpacity={0.55} />
                ))}
                {m.lines.map(([k, name, color]) => (
                  <Line key={k} type="monotone" dataKey={k} name={name} stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- AI assessment */

function AssessmentCard({ latest }: { latest: Point | null }) {
  if (!latest) return null;
  const verdict = latest.band === "critical" ? "Urgent review suggested" : latest.band === "warning" ? "Needs attention" : "Within expected range";
  const reasons = latest.reasons.filter((r) => r !== "ML_RISK");
  const risk = Math.round(latest.risk * 100);
  return (
    <div className="card pad assess">
      <div className="row">
        <span className="eyebrow" style={{ margin: 0 }}>AI early-warning</span>
        <span className="spacer" />
        <span className="xs faint">rules · NEWS2 · gradient boosting</span>
      </div>
      <div className={`verdict ${latest.band}`}>{verdict}</div>
      <ul>
        {reasons.length === 0 && <li>Latest readings are close to this patient's own recent baseline.</li>}
        {reasons.map((r) => <li key={r}>{REASON_LABELS[r] ?? r}</li>)}
        {latest.reasons.includes("ML_RISK") && <li>The model sees a deterioration-like trend across several vitals.</li>}
        <li className="muted">Decision support only. No diagnostic conclusion is made.</li>
      </ul>
      <div className="kpis">
        <div className="kpi">
          <div className="label">Model risk</div>
          <div className="num">{risk}%</div>
          <div className={`meter ${risk >= 60 ? "critical" : risk >= 30 ? "warning" : ""}`}><i style={{ width: `${risk}%` }} /></div>
        </div>
        <div className="kpi">
          <div className="label">NEWS2</div>
          <div className="num">{latest.news2 ?? "–"}</div>
          <div className={`meter ${(latest.news2 ?? 0) >= 7 ? "critical" : (latest.news2 ?? 0) >= 5 ? "warning" : ""}`}><i style={{ width: `${Math.min(100, ((latest.news2 ?? 0) / 15) * 100)}%` }} /></div>
        </div>
      </div>
      <div className="foot">
        <span>Alert threshold: model ≥ 60% or NEWS2 ≥ 5</span>
        <span>{new Date(latest.ts * 1000).toLocaleTimeString()}</span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- alerts */

export function AlertList({ patientId, canAck }: { patientId: number; canAck: boolean }) {
  const { data, error, reload } = usePolling<AlertItem[]>(`/api/patients/${patientId}/alerts`, 5000);
  const [noteFor, setNoteFor] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const open = data?.filter((a) => a.status === "open").length ?? 0;

  const ack = async (id: number) => {
    await api(`/api/alerts/${id}/ack`, { method: "POST", body: { note } });
    setNoteFor(null);
    setNote("");
    reload();
  };

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Alerts</h2>
          <div className="sub">{open ? `${open} open · one alert per reason until acknowledged` : "No open alerts"}</div>
        </div>
      </div>
      <div style={{ marginTop: 12 }}>
        {error && <div className="notice error" style={{ margin: "0 22px 16px" }}>{error.message}</div>}
        {!data ? <div className="empty">Loading…</div> : data.length === 0 ? <div className="empty">Nothing has been flagged for this patient.</div> : (
          <ul className="alerts">
            {data.slice(0, 12).map((a) => (
              <li key={a.id} className={`alert ${a.status === "open" ? a.severity : "done"}`}>
                <span className="ico">{a.status === "open" ? <Icon.Alert size={16} /> : <Icon.Check size={16} />}</span>
                <div>
                  <div className="title">
                    {REASON_LABELS[a.reason_code] ?? a.reason_code}
                    <span className="code">{a.reason_code}</span>
                    {a.status === "open" ? <BandBadge band={a.severity} /> : <span className="tag ok">Acknowledged</span>}
                    {a.status === "open" && a.escalated_at && <span className="tag danger">Escalated</span>}
                  </div>
                  <div className="muted small">
                    First {timeAgo(a.first_seen)} · last {timeAgo(a.last_seen)} · {a.occurrences} reading{a.occurrences === 1 ? "" : "s"}
                    {a.status === "acknowledged" && ` · by ${a.acknowledged_by} ${timeAgo(a.acknowledged_at)}`}
                  </div>
                  {a.note && <div className="note">{a.note}</div>}
                </div>
                {canAck && a.status === "open" && noteFor !== a.id ? (
                  <button className="btn secondary sm" onClick={() => setNoteFor(a.id)}>Acknowledge</button>
                ) : <span />}
                {noteFor === a.id && (
                  <div className="ack-row">
                    <input autoFocus placeholder="Note for the record (stored encrypted)" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
                    <button className="btn primary sm" onClick={() => ack(a.id)}>Confirm</button>
                    <button className="btn ghost sm" onClick={() => setNoteFor(null)}>Cancel</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- devices + pairing */

export function PairModal({ patientId, patientName, onClose }: { patientId: number; patientName: string; onClose: () => void }) {
  const [label, setLabel] = useState("Wearable monitor");
  const [issued, setIssued] = useState<{ pairing_id: string; code: string; expires_at: string } | null>(null);
  const [status, setStatus] = useState("waiting");
  const [err, setErr] = useState("");
  const [now, setNow] = useState(Date.now());
  const { me } = useAuth();

  useEffect(() => {
    if (!issued || status !== "waiting") return;
    const id = window.setInterval(async () => {
      setNow(Date.now());
      try {
        const s = await api<{ status: string }>(`/api/devices/pairing-codes/${issued.pairing_id}`);
        setStatus(s.status);
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => window.clearInterval(id);
  }, [issued, status]);

  const issue = async () => {
    setErr("");
    try {
      setIssued(await api("/api/devices/pairing-codes", { method: "POST", body: { patient_id: patientId, label } }));
      setStatus("waiting");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  };
  const simulate = async () => {
    if (!issued) return;
    setErr("");
    try {
      await api("/api/admin/simulator/pair", { method: "POST", body: { pairing_id: issued.pairing_id, code: issued.code, source: "synthetic" } });
      setStatus("paired");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  };
  const left = issued ? Math.max(0, Math.round((new Date(issued.expires_at).getTime() - now) / 1000)) : 0;

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="pair-title" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <div>
            <h2 id="pair-title">Pair a device</h2>
            <div className="sub">for {patientName}</div>
          </div>
          <button className="btn ghost sm" aria-label="Close" onClick={onClose}><Icon.X size={16} /></button>
        </div>
        <div className="card-body form">
          {!issued ? (
            <>
              <label className="field">
                Device name
                <input value={label} maxLength={64} onChange={(e) => setLabel(e.target.value)} />
              </label>
              <ol className="steps">
                <li>We create a one-time code that expires in 10 minutes.</li>
                <li>Enter it on the device. The device makes its own RSA-3072 key and proves it knows the code (HMAC-SHA-512). The code itself is never sent.</li>
                <li>Only the device's public key is stored. You can revoke it at any time.</li>
              </ol>
              {err && <div className="notice error">{err}</div>}
              <button className="btn primary" onClick={issue}><Icon.Key size={16} /> Create pairing code</button>
            </>
          ) : status === "paired" ? (
            <div className="notice success"><Icon.Check size={18} /> Device paired. It now appears in the device list and can send encrypted readings.</div>
          ) : (
            <>
              <div className="pair-code" aria-label="Pairing code">{issued.code}</div>
              <div className="row small">
                <span className="muted">Pairing ID <code>{issued.pairing_id}</code></span>
                <span className="spacer" />
                <span className={status === "waiting" && left > 0 ? "muted" : "crit-text"}>
                  {status === "waiting" && left > 0 ? `Expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : status === "locked" ? "Locked after wrong attempts" : "Expired"}
                </span>
              </div>
              <div className="notice info">Waiting for the device… On a real device, run <code>scripts/device_client.py pair</code> with this ID and code.</div>
              {me?.role === "admin" && status === "waiting" && (
                <button className="btn secondary" onClick={simulate}><Icon.Play size={16} /> Use the built-in simulator as this device</button>
              )}
              {err && <div className="notice error">{err}</div>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function DevicesCard({ patientId, patientName, canManage }: { patientId: number; patientName: string; canManage: boolean }) {
  const { data, reload } = usePolling<DeviceRow[]>(canManage ? `/api/devices?patient_id=${patientId}` : null, 10000);
  const [pairing, setPairing] = useState(false);
  const revoke = async (id: string) => {
    if (!confirm("Revoke this device? It will no longer be able to send readings.")) return;
    await api(`/api/devices/${id}/revoke`, { method: "POST" });
    reload();
  };
  if (!canManage) return null;
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Devices</h2>
          <div className="sub">Signed with each device's own key</div>
        </div>
        <button className="btn secondary sm" onClick={() => setPairing(true)}><Icon.Plus size={15} /> Pair device</button>
      </div>
      <div className="card-body">
        {!data ? <div className="muted small">Loading…</div> : data.length === 0 ? <div className="muted small">No devices yet.</div> : (
          <ul className="device-list">
            {data.map((d) => (
              <li key={d.id}>
                <span className="ico"><Icon.Watch size={17} /></span>
                <div className="info">
                  <b>{d.label} {!d.active && <span className="tag danger">Revoked</span>}</b>
                  <span>{d.id} · paired by {d.paired_by} · seen {timeAgo(d.last_seen)}</span>
                </div>
                {d.active && <button className="btn ghost sm" onClick={() => revoke(d.id)}>Revoke</button>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {pairing && <PairModal patientId={patientId} patientName={patientName} onClose={() => { setPairing(false); reload(); }} />}
    </div>
  );
}

/* ---------------------------------------------------------------- composed view */

export function Monitor({ patientId, patientName, canAck, side }: { patientId: number; patientName: string; canAck: boolean; side?: React.ReactNode }) {
  const [range, setRange] = useState("6h");
  const { data, error } = usePolling<Readings>(`/api/patients/${patientId}/readings?range=${range}`, range === "6h" ? 5000 : 15000);
  const { data: recent } = usePolling<Readings>(range === "6h" ? null : `/api/patients/${patientId}/readings?range=6h`, 5000);
  const sparkSource = useMemo(() => (range === "6h" ? data : recent) ?? data, [range, data, recent]);

  if (error) return <div className="notice error">{error.message}</div>;
  return (
    <>
      <VitalCards latest={data?.latest ?? null} points={sparkSource?.points ?? []} />
      <div className="grid main-side">
        <div className="stack">
          <TrendCard data={data} range={range} setRange={setRange} />
          <AlertList patientId={patientId} canAck={canAck} />
        </div>
        <div className="stack">
          <AssessmentCard latest={data?.latest ?? null} />
          {side}
        </div>
      </div>
      <span className="sr-only">{patientName}</span>
    </>
  );
}
