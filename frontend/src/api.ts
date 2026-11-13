export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Every state-changing call carries X-RPM-Request (CSRF defence) and sends the httpOnly session cookie.
export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: opts.method ?? "GET",
    credentials: "same-origin",
    headers: {
      "X-RPM-Request": "1",
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export type Role = "admin" | "clinician" | "patient";
export type Band = "normal" | "warning" | "critical" | null;

export interface Me {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  patient_id: number | null;
  must_change_password: boolean;
  recovery_codes_left: number | null;
}

/** Download a JSON or text payload as a file without it touching the server again. */
export function saveFile(name: string, content: string, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** One reading. Real sensors may measure only some vitals, so each one can be missing. */
export interface Point {
  ts: number;
  hr?: number;
  spo2?: number;
  sbp?: number;
  dbp?: number;
  temp?: number;
  rr?: number;
  news2?: number;
  news2_inputs?: number; // how many of the 5 NEWS2 inputs were measured (5 = complete)
  band: Exclude<Band, null>;
  risk: number | null;   // AI model probability; null when the reading lacks some vitals
  reasons: string[];
}

export interface Readings {
  patient_id: number;
  range: string;
  count: number;
  latest: Point | null;
  points: Point[];
}

export interface AlertItem {
  id: number;
  reason_code: string;
  severity: "warning" | "critical";
  status: "open" | "acknowledged";
  first_seen: string;
  last_seen: string;
  occurrences: number;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  escalated_at: string | null;
  note: string | null;
}

export interface PatientSummary {
  id: number;
  name: string;
  band: Band;
  risk: number | null;
  last_reading_at: string | null;
  open_alerts: number;
  escalated_alerts: number;
  consent_active: boolean;
  data_source: string;
}

export function sourceInfo(source: string | undefined): { kind: "real" | "synthetic" | "none"; label: string; detail: string } {
  if (!source || source === "none" || source === "unknown") return { kind: "none", label: "No device", detail: "No paired device" };
  if (source.startsWith("mimic:"))
    return { kind: "real", label: "Real data replay", detail: `MIMIC-III ICU stay ${source.split(":")[1]} (de-identified)` };
  if (source.startsWith("eicu:"))
    return { kind: "real", label: "Real data replay", detail: `eICU ICU stay ${source.split(":")[1]} (de-identified, 5-minute vitals; temperature only where it was charted)` };
  if (source.startsWith("bidmc:"))
    return { kind: "real", label: "Real data replay", detail: `BIDMC record ${source.split(":")[1]} · HR/SpO₂/RR real, BP/temp not recorded` };
  return { kind: "synthetic", label: "Synthetic data", detail: "Generated vital signs" };
}

export interface DeviceRow {
  id: string;
  label: string;
  active: boolean;
  last_seen: string | null;
  paired_at: string | null;
  paired_by: string;
  revoked_at: string | null;
  kind: "device" | "import";
  device_type: string | null;
}

/** One entry of the device catalog served by /api/devices/catalog (backend/app/device_catalog.py). */
export interface DeviceType {
  id: string;
  name: string;
  icon: string;
  measures: string[];
  connects_through: string;
  status: "ready" | "needs_adapter" | "needs_integration";
  admin_only: boolean;
  default_label: string;
  what_you_need: string[];
  how_to_connect: string[];
  patient_tips: string[];
}

export const DEVICE_STATUS_LABEL: Record<DeviceType["status"], string> = {
  ready: "Ready to use",
  needs_adapter: "Needs gateway adapter",
  needs_integration: "Needs hospital IT",
};

export type Connection = "receiving" | "recent" | "quiet" | "never" | "revoked";

/** How a paired device is doing, from the time of its last reading. */
export function connectionOf(d: { active: boolean; last_seen: string | null }, now = Date.now()): Connection {
  if (!d.active) return "revoked";
  if (!d.last_seen) return "never";
  const age = (now - new Date(d.last_seen).getTime()) / 1000;
  if (age <= 120) return "receiving";
  if (age <= 600) return "recent";
  return "quiet";
}

export const CONNECTION_LABEL: Record<Connection, string> = {
  receiving: "Receiving readings",
  recent: "Recently active",
  quiet: "No recent readings",
  never: "Not connected yet",
  revoked: "Revoked",
};

/** The text inside the pairing QR code; scripts/device_client.py pair --link reads it. */
export function pairingLink(server: string, pairingId: string, code: string): string {
  const q = new URLSearchParams({ server, id: pairingId, code });
  return `vitalcare-pair:v1?${q.toString()}`;
}

export interface PatientProfile extends PatientSummary {
  devices: { id: string; label: string; active: boolean; last_seen: string | null; device_type: string | null }[];
  consent_changed_at: string;
  dob?: string | null;
  phone?: string | null;
  address?: string | null;
}

export const REASON_LABELS: Record<string, string> = {
  SPO2_LOW: "Low oxygen saturation",
  HR_HIGH: "High heart rate",
  HR_LOW: "Low heart rate",
  BP_LOW: "Low blood pressure",
  BP_HIGH: "High blood pressure",
  TEMP_HIGH: "Fever",
  TEMP_LOW: "Low temperature",
  RR_HIGH: "Fast breathing",
  RR_LOW: "Slow breathing",
  ML_RISK: "AI model: deterioration pattern",
  NEWS2_HIGH: "NEWS2 score high (7+)",
  NEWS2_MEDIUM: "NEWS2 score medium (5-6)",
};

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
