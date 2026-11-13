import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AlertItem, api, Band, Point, Readings, REASON_LABELS, timeAgo } from "../api";
import { usePolling } from "../hooks";

export function BandBadge({ band }: { band: Band }) {
  return <span className={`badge ${band ?? "none"}`}>{band ?? "no data"}</span>;
}

const METRICS = [
  { key: "hr", label: "Heart rate", unit: "bpm", lines: [["hr", "Heart rate"]], refs: [50, 100, 120] },
  { key: "spo2", label: "SpO₂", unit: "%", lines: [["spo2", "SpO₂"]], refs: [92, 95] },
  { key: "bp", label: "Blood pressure", unit: "mmHg", lines: [["sbp", "Systolic"], ["dbp", "Diastolic"]], refs: [90, 180] },
  { key: "temp", label: "Temperature", unit: "°C", lines: [["temp", "Temperature"]], refs: [38, 38.5] },
  { key: "rr", label: "Resp. rate", unit: "/min", lines: [["rr", "Resp. rate"]], refs: [8, 20, 24] },
  { key: "risk", label: "AI risk", unit: "", lines: [["risk", "Model probability"]], refs: [0.6] },
] as const;

const CARDS: { key: keyof Point; label: string; unit: string; fmt?: (v: number) => string }[] = [
  { key: "hr", label: "Heart rate", unit: "bpm" },
  { key: "spo2", label: "SpO₂", unit: "%" },
  { key: "sbp", label: "Blood pressure", unit: "mmHg" },
  { key: "temp", label: "Temperature", unit: "°C", fmt: (v) => v.toFixed(1) },
  { key: "rr", label: "Resp. rate", unit: "/min" },
  { key: "news2", label: "NEWS2", unit: "" },
];

function VitalCards({ latest }: { latest: Point | null }) {
  if (!latest) return <div className="empty">No readings yet.</div>;
  const flagged = new Set(latest.reasons.map((r) => r.split("_")[0].toLowerCase()));
  return (
    <div className="cards">
      {CARDS.map((c) => {
        const raw = latest[c.key] as number | undefined;
        const value =
          c.key === "sbp" ? `${Math.round(latest.sbp)}/${Math.round(latest.dbp)}` : raw === undefined ? "–" : c.fmt ? c.fmt(raw) : Math.round(raw);
        const flag = flagged.has(c.key === "sbp" ? "bp" : String(c.key));
        return (
          <div key={c.key} className={`vital ${flag ? latest.band : ""}`}>
            <div className="vital-label">{c.label}</div>
            <div className="vital-value">
              {value}
              <span className="unit">{c.unit}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function fmtTime(ts: number, range: string) {
  const d = new Date(ts * 1000);
  return range === "7d"
    ? d.toLocaleDateString(undefined, { weekday: "short", hour: "2-digit" })
    : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function Chart({ points, range }: { points: Point[]; range: string }) {
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("hr");
  const m = METRICS.find((x) => x.key === metric)!;
  const colors = ["var(--accent)", "var(--accent-2)"];
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="tabs" role="tablist">
          {METRICS.map((x) => (
            <button key={x.key} role="tab" aria-selected={metric === x.key} className={metric === x.key ? "tab on" : "tab"} onClick={() => setMetric(x.key)}>
              {x.label}
            </button>
          ))}
        </div>
      </div>
      {points.length === 0 ? (
        <div className="empty">No readings in this range.</div>
      ) : (
        <div className="chart">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={points} margin={{ top: 10, right: 16, bottom: 0, left: -8 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="ts" tickFormatter={(t) => fmtTime(t, range)} stroke="var(--muted)" fontSize={12} minTickGap={40} />
              <YAxis stroke="var(--muted)" fontSize={12} domain={["auto", "auto"]} width={48} />
              <Tooltip
                labelFormatter={(t) => new Date(Number(t) * 1000).toLocaleString()}
                formatter={(v: number, name) => [`${Number(v).toFixed(m.key === "risk" ? 2 : 1)} ${m.unit}`, name]}
                contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }}
              />
              {m.refs.map((r) => (
                <ReferenceLine key={r} y={r} stroke="var(--warning)" strokeDasharray="4 4" strokeOpacity={0.6} />
              ))}
              {m.lines.map(([k, name], i) => (
                <Line key={k} type="monotone" dataKey={k} name={name} stroke={colors[i]} strokeWidth={2} dot={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export function AlertList({ patientId, canAck }: { patientId: number; canAck: boolean }) {
  const { data, error, reload } = usePolling<AlertItem[]>(`/api/patients/${patientId}/alerts`, 5000);
  const [noteFor, setNoteFor] = useState<number | null>(null);
  const [note, setNote] = useState("");

  const ack = async (id: number) => {
    await api(`/api/alerts/${id}/ack`, { method: "POST", body: { note } });
    setNoteFor(null);
    setNote("");
    reload();
  };

  if (error) return <div className="error">{error.message}</div>;
  if (!data) return <div className="muted">Loading alerts…</div>;
  if (data.length === 0) return <div className="empty">No alerts.</div>;
  return (
    <ul className="alerts">
      {data.map((a) => (
        <li key={a.id} className={`alert ${a.status === "open" ? a.severity : "done"}`}>
          <div className="alert-main">
            <div>
              <div className="alert-title">
                <span className={`dot ${a.status === "open" ? a.severity : "done"}`} />
                {REASON_LABELS[a.reason_code] ?? a.reason_code}
                <span className="code">{a.reason_code}</span>
              </div>
              <div className="muted small">
                {a.severity} · first {timeAgo(a.first_seen)} · last {timeAgo(a.last_seen)} · {a.occurrences}×
                {a.status === "acknowledged" && ` · acknowledged by ${a.acknowledged_by} ${timeAgo(a.acknowledged_at)}`}
              </div>
              {a.note && <div className="note">“{a.note}”</div>}
            </div>
            {canAck && a.status === "open" && noteFor !== a.id && (
              <button className="secondary" onClick={() => setNoteFor(a.id)}>
                Acknowledge
              </button>
            )}
          </div>
          {noteFor === a.id && (
            <div className="ack-row">
              <input placeholder="Note (optional, stored encrypted)" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
              <button className="primary" onClick={() => ack(a.id)}>
                Confirm
              </button>
              <button className="ghost" onClick={() => setNoteFor(null)}>
                Cancel
              </button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function Monitor({ patientId, canAck }: { patientId: number; canAck: boolean }) {
  const [range, setRange] = useState("6h");
  const { data, error } = usePolling<Readings>(`/api/patients/${patientId}/readings?range=${range}`, range === "6h" ? 5000 : 15000);

  if (error) return <div className="error banner">{error.message}</div>;
  return (
    <>
      <section>
        <div className="section-head">
          <h2>Latest vitals</h2>
          <span className="muted small">
            {data?.latest ? (
              <>
                {new Date(data.latest.ts * 1000).toLocaleTimeString()} · <BandBadge band={data.latest.band} /> · AI risk{" "}
                {(data.latest.risk * 100).toFixed(0)}%
              </>
            ) : (
              "waiting for data"
            )}
          </span>
        </div>
        <VitalCards latest={data?.latest ?? null} />
      </section>
      <section>
        <div className="section-head">
          <h2>Trends</h2>
          <div className="seg">
            {["6h", "24h", "7d"].map((r) => (
              <button key={r} className={range === r ? "on" : ""} onClick={() => setRange(r)}>
                {r}
              </button>
            ))}
          </div>
        </div>
        <Chart points={data?.points ?? []} range={range} />
        <div className="muted small right">{data ? `${data.count} encrypted readings decrypted for this view` : ""}</div>
      </section>
      <section>
        <div className="section-head">
          <h2>Alerts</h2>
        </div>
        <AlertList patientId={patientId} canAck={canAck} />
      </section>
    </>
  );
}
