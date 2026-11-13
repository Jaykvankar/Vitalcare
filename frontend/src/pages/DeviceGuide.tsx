import { CONNECTION_LABEL, Connection, DEVICE_STATUS_LABEL } from "../api";
import { useAuth } from "../App";
import { DeviceIcon, statusTagClass } from "../components/ConnectDevice";
import { Icon } from "../components/Icons";
import { useDeviceCatalog } from "../hooks";

const CONNECTION_HELP: { c: Connection; cls: string; text: string }[] = [
  { c: "receiving", cls: "tag ok", text: "A reading arrived in the last 2 minutes. All good." },
  { c: "recent", cls: "tag", text: "Last reading 2–10 minutes ago. Normal for devices that measure now and then, like a cuff." },
  { c: "quiet", cls: "tag warn", text: "Nothing for over 10 minutes. Check the device is on, charged and near its gateway." },
  { c: "never", cls: "tag", text: "Connected, but no reading has arrived yet. Switch the sensors on." },
  { c: "revoked", cls: "tag danger", text: "Stopped on purpose. It can no longer send readings." },
];

const TROUBLE: [string, string, string][] = [
  ["The code has expired", "Codes last 10 minutes so a lost code is useless.", "Open Connect device again and create a new code."],
  ["The code is locked", "Someone typed it wrong 5 times.", "Create a new code."],
  ["Connected, but no readings", "The sensors are off, out of range, or the gateway has no internet. A gateway clock that is more than 1 minute wrong also blocks readings.", "Switch the sensors on, move them near the gateway, check its Wi-Fi and that its clock sets itself automatically."],
  ["Readings stopped", "Battery, range or network.", "Charge or replace batteries, then check the gateway is online."],
  ["A device is lost, stolen or replaced", "Whoever has it could still send readings.", "Open the patient's Devices list and select Revoke. Connect the replacement with a new code."],
  ["My device is not in the list", "Only devices that share their data in a standard way can be connected.", "Check the three questions below, or ask IT whether an adapter can be written for it."],
];

export default function DeviceGuide() {
  const { me } = useAuth();
  const catalog = useDeviceCatalog();
  const staff = me?.role !== "patient";
  return (
    <div className="page guide">
      <div className="page-head">
        <div>
          <div className="eyebrow">Devices</div>
          <h1>Connecting devices</h1>
          <p className="sub">Which devices work with Vitalcare, how they connect, and what to do when something goes wrong.</p>
        </div>
      </div>

      <section className="card pad">
        <h2>How a device connects</h2>
        <div className="flow" role="img" aria-label="Sensor, to gateway, to Vitalcare, to the care team">
          {[
            { icon: "Drop", t: "Sensor", d: "Oximeter, cuff, thermometer or strap on the patient." },
            { icon: "Watch", t: "Gateway", d: "A small computer nearby collects the readings and locks them with encryption." },
            { icon: "Shield", t: "Vitalcare", d: "Checks each reading really came from that device, then stores it encrypted." },
            { icon: "Users", t: "Care team", d: "Only the patient's own clinicians can open it, and only with the patient's consent." },
          ].map((s, i, all) => (
            <div key={s.t} className="flow-step">
              <span className="ico-lg"><DeviceIcon name={s.icon} size={22} /></span>
              <b>{s.t}</b>
              <span className="muted small">{s.d}</span>
              {i < all.length - 1 && <span className="flow-arrow" aria-hidden>→</span>}
            </div>
          ))}
        </div>
        <p className="muted small">Most medical sensors speak Bluetooth, not internet, so a gateway sits next to the patient. A hospital bedside monitor connects through the hospital's own systems instead.</p>
      </section>

      <section className="stack">
        <h2>Which devices can be connected</h2>
        {!catalog ? <div className="muted small">Loading…</div> : (
          <div className="guide-grid">
            {catalog.map((d) => (
              <article key={d.id} className="card pad guide-card">
                <div className="row">
                  <span className="ico-lg"><DeviceIcon name={d.icon} size={22} /></span>
                  <div style={{ minWidth: 0 }}><h3>{d.name}</h3><span className={statusTagClass(d.status)}>{DEVICE_STATUS_LABEL[d.status]}</span></div>
                </div>
                <p className="muted small">{d.connects_through}</p>
                <div className="measures">{d.measures.map((m) => <span key={m} className="tag">{m}</span>)}</div>
                <details>
                  <summary>What you need and how to connect</summary>
                  <ul className="checklist">{d.what_you_need.map((w) => <li key={w}><Icon.Check size={14} /> {w}</li>)}</ul>
                  <ol className="steps">{d.how_to_connect.map((s) => <li key={s}>{s}</li>)}</ol>
                  {d.patient_tips.length > 0 && <p className="muted xs">Tip for the patient: {d.patient_tips.join(" ")}</p>}
                </details>
              </article>
            ))}
          </div>
        )}
        <p className="muted xs">
          <b>Ready to use</b> works with what is installed today. <b>Needs gateway adapter</b> works once IT installs the small adapter for
          that device model on the gateway. <b>Needs hospital IT</b> is connected through the hospital's integration systems. Device types
          are listed rather than brands, because no specific model has been certified.
        </p>
      </section>

      <div className="grid two">
        <section className="card pad">
          <h2>Will my device work?</h2>
          <p className="muted small">Yes, if you can answer yes to all three:</p>
          <ol className="steps">
            <li><b>Does it share its data in a standard way?</b> Look for Bluetooth "Pulse Oximeter", "Blood Pressure", "Health Thermometer" or "Heart Rate" support, or a maker who documents how to read the data.</li>
            <li><b>Does it measure in normal medical units?</b> Beats per minute, %, mmHg, °C, breaths per minute.</li>
            <li><b>Does it work without the maker's own phone app?</b> Devices that only talk to their own app usually cannot be connected.</li>
          </ol>
        </section>
        <section className="card pad">
          <h2>What the device status means</h2>
          <ul className="legend">
            {CONNECTION_HELP.map((h) => (
              <li key={h.c}><span className={h.cls}>{CONNECTION_LABEL[h.c]}</span><span className="small">{h.text}</span></li>
            ))}
          </ul>
        </section>
      </div>

      {staff && (
        <section className="card pad">
          <h2>Connecting a device, step by step</h2>
          <ol className="steps">
            <li>Open the patient's record and select <b>Connect device</b> in the Devices section.</li>
            <li>Choose what you are connecting and give it a name the patient will recognise.</li>
            <li>A connection code and a QR code appear. They work once and last 10 minutes.</li>
            <li>On the gateway, choose <b>Add device</b> and scan the QR code, or type the code.</li>
            <li>Keep the window open: it shows <b>Connected</b>, then <b>Readings are arriving</b>.</li>
          </ol>
        </section>
      )}

      <section className="card scroll-x">
        <div className="card-head"><div><h2>Something not working?</h2></div></div>
        <table className="table" style={{ marginTop: 12 }}>
          <thead><tr><th>What you see</th><th>Why</th><th>What to do</th></tr></thead>
          <tbody>{TROUBLE.map(([a, b, c]) => <tr key={a}><td><b>{a}</b></td><td className="small">{b}</td><td className="small">{c}</td></tr>)}</tbody>
        </table>
      </section>

      {staff && (
        <section className="card pad">
          <h2>For IT staff</h2>
          <p className="small">A gateway runs <code>scripts/device_client.py</code>. It pairs with the link inside the QR code and then sends whatever your sensor adapter prints, one JSON line per reading:</p>
          <pre className="cmd">{`python scripts/device_client.py pair --link "vitalcare-pair:v1?server=...&id=...&code=..."
python read_my_sensor.py | python scripts/device_client.py stream --source stdin

{"hr": 78, "spo2": 97, "sbp": 122, "dbp": 79, "temp": 36.8, "rr": 15}`}</pre>
          <p className="muted small">Every line needs all six values; the adapter repeats the latest blood pressure and temperature between measurements. The device key is created on the gateway and never leaves it. Full setup, Bluetooth services and service files: <code>docs/HANDOFF.md</code>, section 5.</p>
        </section>
      )}
    </div>
  );
}
