import { useRef, useState } from "react";
import { Icon } from "./Icons";

/** Pick a CSV file (or paste text), read it in the browser, and hand the text to the caller. */
export function CsvPicker({ onText, sample, sampleName }: { onText: (text: string, name: string) => void; sample: string; sampleName: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [drag, setDrag] = useState(false);

  const read = (file: File) => {
    if (file.size > 3_000_000) return alert("File is larger than 3 MB");
    file.text().then((t) => {
      setName(file.name);
      onText(t, file.name);
    });
  };
  const downloadSample = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([sample], { type: "text/csv" }));
    a.download = sampleName;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div
      className={`dropzone ${drag ? "drag" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) read(f); }}
    >
      <Icon.Database size={22} />
      <div>
        <b>{name || "Drop a CSV file here"}</b>
        <div className="muted small">or choose one from your computer. Nothing is saved until you confirm the preview.</div>
      </div>
      <div className="row">
        <button type="button" className="btn secondary sm" onClick={() => input.current?.click()}>Choose file</button>
        <button type="button" className="btn ghost sm" onClick={downloadSample}>Download template</button>
      </div>
      <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) read(f); e.target.value = ""; }} />
    </div>
  );
}
