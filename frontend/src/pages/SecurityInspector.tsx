import { useEffect, useState } from "react";
import { api, ApiError, timeAgo } from "../api";
import { Icon } from "../components/Icons";
import { usePolling } from "../hooks";

interface Step { id: string; title: string; family: string; algorithm: string; values: Record<string, string>; ok: boolean }
interface Packet { received_at: number; device_id: string; patient_id: number; steps: Step[] }
interface DeviceEv { id: string; label: string; device_type: string | null; patient: string; last_seen: string | null; packets: Packet[] }
interface Ledger { rows: number; head_hash: string | null; checkpoint: { through_row: number; signature: string; algorithm: string; verified: boolean } | null }
interface Attack { id: string; title: string; explanation: string }
interface View { devices: DeviceEv[]; ledger: Ledger; attacks: Attack[]; can_attack: boolean }
interface AttackResult { kind: string; blocked: boolean; status: number; message: string; explanation: string }

export default function SecurityInspector() {
  const { data, error } = usePolling<View>("/api/security/inspector", 5000);
  const [picked, setPicked] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, AttackResult | string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const withPackets = data?.devices.filter((d) => d.packets.length > 0) ?? [];
  // Pin the first device that has data, so the view does not jump as other devices send readings.
  const firstWithData = withPackets[0]?.id ?? null;
  useEffect(() => {
    if (!picked && firstWithData) setPicked(firstWithData);
  }, [picked, firstWithData]);
  const device = data?.devices.find((d) => d.id === picked) ?? withPackets[0] ?? data?.devices[0];
  const packet = device?.packets[0];

  const run = async (kind: string) => {
    if (!device) return;
    setBusy(kind);
    try {
      const r = await api<AttackResult>("/api/security/attack", { method: "POST", body: { device_id: device.id, kind } });
      setResults((x) => ({ ...x, [kind]: r }));
    } catch (e) {
      setResults((x) => ({ ...x, [kind]: (e as ApiError).message }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page inspector">
      <div className="page-head">
        <div>
          <div className="eyebrow">Security</div>
          <h1>Security inspector</h1>
          <p className="sub">What the cryptography did to the latest reading, step by step. Only public or encrypted values are shown, never vital signs or keys.</p>
        </div>
      </div>
      {error && <div className="notice error">{error.message}</div>}

      {data && data.devices.length === 0 && <div className="card pad empty">No active devices yet. Connect a device or start the demo monitors.</div>}

      {data && data.devices.length > 0 && (
        <div className="card pad">
          <div className="row">
            <label className="field" style={{ flex: "1 1 260px" }}>
              Device
              <select id="inspector-device" value={device?.id ?? ""} onChange={(e) => { setPicked(e.target.value); setResults({}); }}>
                {data.devices.map((d) => (
                  <option key={d.id} value={d.id}>{d.label} · {d.patient}{d.packets.length ? "" : " (no packet since server start)"}</option>
                ))}
              </select>
            </label>
            <div className="muted small" style={{ alignSelf: "flex-end" }}>
              {packet ? <>Latest packet received {timeAgo(new Date(packet.received_at * 1000).toISOString())} · refreshes every 5 s</> : "Waiting for this device's next reading…"}
            </div>
          </div>
        </div>
      )}

      {packet && (
        <ol className="crypto-steps">
          {packet.steps.map((s, i) => (
            <li key={s.id} className="card crypto-step">
              <span className="num">{i + 1}</span>
              <div className="body">
                <div className="row">
                  <h2>{s.title}</h2>
                  <span className="tag fam">{s.family}</span>
                  <span className="spacer" />
                  {s.ok && <span className="tag ok"><Icon.Check size={12} /> passed</span>}
                </div>
                <p className="muted small">{s.algorithm}</p>
                <dl className="kv crypto-kv">
                  {Object.entries(s.values).map(([k, v]) => (
                    <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd className="mono">{v}</dd></div>
                  ))}
                </dl>
              </div>
            </li>
          ))}
          {data?.ledger && (
            <li className="card crypto-step">
              <span className="num">{packet.steps.length + 1}</span>
              <div className="body">
                <div className="row">
                  <h2>Recorded in the privacy ledger</h2>
                  <span className="tag fam">SHA-512 + DSA family (ECDSA)</span>
                  <span className="spacer" />
                  {data.ledger.checkpoint?.verified && <span className="tag ok"><Icon.Check size={12} /> signature valid</span>}
                </div>
                <p className="muted small">Each access is appended with the SHA-512 of the previous row; checkpoints are signed with the server's ECDSA P-384 key.</p>
                <dl className="kv crypto-kv">
                  <dt>Rows in the ledger</dt><dd className="mono">{data.ledger.rows}</dd>
                  <dt>Latest row hash</dt><dd className="mono">{data.ledger.head_hash ?? "–"}</dd>
                  {data.ledger.checkpoint && <>
                    <dt>Last signed checkpoint</dt><dd className="mono">row {data.ledger.checkpoint.through_row} · {data.ledger.checkpoint.signature}</dd>
                  </>}
                </dl>
              </div>
            </li>
          )}
        </ol>
      )}

      {data?.can_attack && device && (
        <section className="card pad">
          <h2>Try to attack this device's traffic</h2>
          <p className="muted small" style={{ margin: "6px 0 14px" }}>
            Each button takes the last real packet from <b>{device.label}</b>, damages it the way an attacker would, and sends it through the
            normal checks. Nothing is changed if it is rejected; every attempt is written to the privacy ledger.
          </p>
          <div className="attack-grid">
            {data.attacks.map((a) => {
              const r = results[a.id];
              return (
                <div key={a.id} className="attack">
                  <b>{a.title}</b>
                  <span className="muted small">{a.explanation}</span>
                  <button type="button" className="btn secondary sm" disabled={busy !== null || !packet} onClick={() => run(a.id)}>
                    {busy === a.id ? "Sending…" : "Run attack"}
                  </button>
                  {typeof r === "string" && <div className="notice error">{r}</div>}
                  {r && typeof r !== "string" && (
                    r.blocked
                      ? <div className="notice success"><Icon.Shield size={16} /><div><b>Blocked</b> ({r.status}): {r.message}</div></div>
                      : <div className="notice error"><Icon.Alert size={16} /><div><b>Not blocked:</b> {r.message}</div></div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
