import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { api, ApiError, DEVICE_STATUS_LABEL, DeviceRow, DeviceType, pairingLink } from "../api";
import { useAuth } from "../App";
import { useDeviceCatalog } from "../hooks";
import { Icon } from "./Icons";

type Issued = { pairing_id: string; code: string; expires_at: string };
type Stage = "choose" | "name" | "connect";
type Link = "waiting" | "paired" | "receiving" | "expired" | "locked";

const STEP_NAMES = ["Choose device", "Name it", "Connect", "Check it works"];

export function DeviceIcon({ name, size = 20 }: { name?: string | null; size?: number }) {
  const I = (name && Icon[name as keyof typeof Icon]) || Icon.Watch;
  return <I size={size} />;
}

export function statusTagClass(status: DeviceType["status"]) {
  return status === "ready" ? "tag ok" : status === "needs_adapter" ? "tag warn" : "tag";
}

async function copy(text: string, done: (msg: string) => void) {
  try {
    await navigator.clipboard.writeText(text);
    done("Copied");
  } catch {
    done("Copy failed: select the text and copy it");
  }
}

/** Guided "Connect a device" flow: choose a device type, name it, connect with a code or QR, confirm data arrives. */
export function ConnectDevice({ patientId, patientName, onClose }: { patientId: number; patientName: string; onClose: () => void }) {
  const { me } = useAuth();
  const catalog = useDeviceCatalog();
  const [stage, setStage] = useState<Stage>("choose");
  const [type, setType] = useState<DeviceType | null>(null);
  const [label, setLabel] = useState("");
  const [issued, setIssued] = useState<Issued | null>(null);
  const [link, setLink] = useState<Link>("waiting");
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [copied, setCopied] = useState("");

  // Poll the code until a device uses it, then poll the device until its first reading arrives.
  useEffect(() => {
    if (!issued || link === "receiving" || link === "expired" || link === "locked") return;
    const tick = async () => {
      setNow(Date.now());
      try {
        if (link === "waiting") {
          const s = await api<{ status: string; device_id: string | null }>(`/api/devices/pairing-codes/${issued.pairing_id}`);
          if (s.status === "paired") {
            setDeviceId(s.device_id);
            setLink("paired");
          } else if (s.status === "expired" || s.status === "locked") {
            setLink(s.status);
          }
        } else if (link === "paired" && deviceId) {
          const rows = await api<DeviceRow[]>(`/api/devices?patient_id=${patientId}`);
          if (rows.find((d) => d.id === deviceId)?.last_seen) setLink("receiving");
        }
      } catch {
        /* keep polling; a network blip should not end the flow */
      }
    };
    const id = window.setInterval(tick, 2000);
    return () => window.clearInterval(id);
  }, [issued, link, deviceId, patientId]);

  const choose = (d: DeviceType) => {
    setType(d);
    setLabel(d.default_label);
    setStage("name");
  };

  const createCode = async () => {
    if (!type) return;
    setErr("");
    setBusy(true);
    try {
      const r = await api<Issued>("/api/devices/pairing-codes", {
        method: "POST",
        body: { patient_id: patientId, label: label.trim() || type.default_label, device_type: type.id },
      });
      setIssued(r);
      setLink("waiting");
      setDeviceId(null);
      setNow(Date.now());
      setStage("connect");
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const useTestMonitor = async () => {
    if (!issued) return;
    setErr("");
    setBusy(true);
    try {
      const r = await api<{ device_id: string }>("/api/admin/simulator/pair", {
        method: "POST",
        body: { pairing_id: issued.pairing_id, code: issued.code, source: "synthetic" },
      });
      setDeviceId(r.device_id);
      setLink("paired");
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const left = issued ? Math.max(0, Math.round((new Date(issued.expires_at).getTime() - now) / 1000)) : 0;
  const shownLink: Link = link === "waiting" && issued && left === 0 ? "expired" : link;
  const pairText = issued ? pairingLink(window.location.origin, issued.pairing_id, issued.code) : "";
  const stepIndex = stage === "choose" ? 0 : stage === "name" ? 1 : shownLink === "paired" || shownLink === "receiving" ? 3 : 2;
  const visible = catalog?.filter((d) => !d.admin_only || me?.role === "admin") ?? null;

  return (
    <div className="backdrop" onClick={onClose}>
      <div className="modal wide connect" role="dialog" aria-modal="true" aria-labelledby="connect-title" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <div>
            <h2 id="connect-title">Connect a device</h2>
            <div className="sub">for {patientName}</div>
          </div>
          <button className="btn ghost sm" aria-label="Close" onClick={onClose}><Icon.X size={16} /></button>
        </div>

        <ol className="wizard-steps" aria-label="Progress">
          {STEP_NAMES.map((s, i) => (
            <li key={s} className={i < stepIndex ? "done" : i === stepIndex ? "on" : ""} aria-current={i === stepIndex ? "step" : undefined}>
              <span className="n">{i < stepIndex ? <Icon.Check size={12} /> : i + 1}</span>{s}
            </li>
          ))}
        </ol>

        <div className="card-body form">
          {stage === "choose" && (
            <>
              <p className="muted small">What will send readings for this patient? Not sure? Open the <Link to="/devices/guide" onClick={onClose}>Device guide</Link>.</p>
              {!visible ? <div className="muted small">Loading devices…</div> : (
                <div className="device-grid">
                  {visible.map((d) => (
                    <button key={d.id} type="button" className="device-card" onClick={() => choose(d)}>
                      <span className="ico"><DeviceIcon name={d.icon} /></span>
                      <span className="body">
                        <b>{d.name}</b>
                        <span className="muted xs">{d.connects_through}</span>
                        <span className="measures">{d.measures.map((m) => <span key={m} className="tag">{m}</span>)}</span>
                      </span>
                      <span className={statusTagClass(d.status)}>{DEVICE_STATUS_LABEL[d.status]}</span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {stage === "name" && type && (
            <>
              <div className="row"><span className="ico-lg"><DeviceIcon name={type.icon} size={22} /></span><div><b>{type.name}</b><div className="muted xs">{type.connects_through}</div></div></div>
              <label className="field">
                Name shown in the device list
                <input id="device-label" autoFocus value={label} maxLength={64} onChange={(e) => setLabel(e.target.value)} />
              </label>
              <div>
                <div className="field-label">What you need</div>
                <ul className="checklist">{type.what_you_need.map((w) => <li key={w}><Icon.Check size={14} /> {w}</li>)}</ul>
              </div>
              {type.status !== "ready" && (
                <div className="notice info"><Icon.Alert size={18} /><div>
                  {type.status === "needs_adapter"
                    ? "This device connects through a gateway that has an adapter for this model. Check with your IT team that one is installed before giving the code to the patient."
                    : "Hospital IT connects this device. Create the code here and give it to them."}
                </div></div>
              )}
              {err && <div className="notice error">{err}</div>}
              <div className="row">
                <button type="button" className="btn ghost" onClick={() => setStage("choose")}>Back</button>
                <span className="spacer" />
                <button type="button" className="btn primary" disabled={busy} onClick={createCode}><Icon.Key size={16} /> {busy ? "Creating…" : "Create connection code"}</button>
              </div>
            </>
          )}

          {stage === "connect" && type && issued && (
            <>
              {shownLink === "receiving" ? (
                <div className="notice success"><Icon.Check size={18} /><div><b>Readings are arriving.</b> {label} is connected and sending encrypted readings for {patientName}. You can close this window.</div></div>
              ) : shownLink === "paired" ? (
                <div className="notice success"><Icon.Check size={18} /><div><b>Connected.</b> Waiting for the first reading… switch on the sensors if they are not on yet.</div></div>
              ) : shownLink === "expired" || shownLink === "locked" ? (
                <div className="notice error"><Icon.Alert size={18} /><div>
                  {shownLink === "expired" ? "This code has expired (codes last 10 minutes)." : "This code was locked after 5 wrong attempts."}
                  <div style={{ marginTop: 8 }}><button type="button" className="btn secondary sm" onClick={createCode}>Create a new code</button></div>
                </div></div>
              ) : (
                <>
                  <div className="connect-grid">
                    <div className="qr" aria-label="Pairing QR code"><QRCodeSVG value={pairText} size={164} /></div>
                    <div className="stack" style={{ gap: 10 }}>
                      <div className="field-label">Or type this code on the device</div>
                      <div className="pair-code" aria-label="Pairing code">{issued.code}</div>
                      <div className="row small">
                        <button type="button" className="btn ghost sm" onClick={() => copy(issued.code, setCopied)}>Copy code</button>
                        <span className="spacer" />
                        <span className="muted">Expires in {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</span>
                      </div>
                      {copied && <span className="muted xs" role="status">{copied}</span>}
                    </div>
                  </div>
                  <div>
                    <div className="field-label">What to do now</div>
                    <ol className="steps">{type.how_to_connect.map((s) => <li key={s}>{s}</li>)}</ol>
                  </div>
                  {type.id === "simulator" && me?.role === "admin" && (
                    <button type="button" className="btn secondary" disabled={busy} onClick={useTestMonitor}><Icon.Play size={16} /> Use the built-in test monitor</button>
                  )}
                  <div className="notice info"><span className="pulse" aria-hidden /> Waiting for the device to use this code…</div>
                </>
              )}
              {type.id !== "simulator" && shownLink !== "receiving" && (
                <details className="it-details">
                  <summary>For IT staff: connect a gateway from the command line</summary>
                  <p className="muted small">On the gateway, inside the Vitalcare folder:</p>
                  <pre className="cmd">{`python scripts/device_client.py pair --link "${pairText}"\nyour_sensor_program | python scripts/device_client.py stream --source stdin`}</pre>
                  <button type="button" className="btn ghost sm" onClick={() => copy(`python scripts/device_client.py pair --link "${pairText}"`, setCopied)}>Copy pairing command</button>
                  <p className="muted xs">The sensor program prints one line per reading, for example {'{"hr": 78, "spo2": 97, "sbp": 122, "dbp": 79, "temp": 36.8, "rr": 15}'}. See docs/HANDOFF.md, section 5.</p>
                </details>
              )}
              {err && <div className="notice error">{err}</div>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
