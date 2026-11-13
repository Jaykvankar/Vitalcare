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
}

export interface Point {
  ts: number;
  hr: number;
  spo2: number;
  sbp: number;
  dbp: number;
  temp: number;
  rr: number;
  news2?: number;
  band: Exclude<Band, null>;
  risk: number;
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
  note: string | null;
}

export interface PatientSummary {
  id: number;
  name: string;
  band: Band;
  risk: number | null;
  last_reading_at: string | null;
  open_alerts: number;
  consent_active: boolean;
}

export interface PatientProfile extends PatientSummary {
  devices: { id: string; label: string; active: boolean; last_seen: string | null }[];
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
