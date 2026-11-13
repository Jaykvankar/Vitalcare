import { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };

function Base({ size = 18, children, ...rest }: P & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden {...rest}>
      {children}
    </svg>
  );
}

export const Icon = {
  Logo: (p: P) => <Base {...p} strokeWidth={2.4}><path d="M2 12h4l2.5-6 4 12 3-8 1.5 2H22" /></Base>,
  Grid: (p: P) => <Base {...p}><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></Base>,
  Inbox: (p: P) => <Base {...p}><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /></Base>,
  Users: (p: P) => <Base {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></Base>,
  Link: (p: P) => <Base {...p}><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></Base>,
  Play: (p: P) => <Base {...p}><circle cx="12" cy="12" r="9" /><path d="m10 8.5 5.5 3.5-5.5 3.5z" /></Base>,
  Ledger: (p: P) => <Base {...p}><path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4z" /><path d="M8 9h8M8 13h8M8 17h5" /></Base>,
  Shield: (p: P) => <Base {...p}><path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z" /><path d="m9 12 2 2 4-4" /></Base>,
  Heart: (p: P) => <Base {...p}><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z" /></Base>,
  Drop: (p: P) => <Base {...p}><path d="M12 2.7s7 7.3 7 12.3a7 7 0 1 1-14 0c0-5 7-12.3 7-12.3z" /></Base>,
  Wind: (p: P) => <Base {...p}><path d="M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7" /></Base>,
  Gauge: (p: P) => <Base {...p}><path d="M12 14l4-4" /><path d="M3.3 19a10 10 0 1 1 17.4 0" /></Base>,
  Thermo: (p: P) => <Base {...p}><path d="M14 14.8V4a2 2 0 1 0-4 0v10.8a4 4 0 1 0 4 0z" /></Base>,
  Score: (p: P) => <Base {...p}><path d="M3 3v18h18" /><path d="M7 15l4-4 3 3 5-6" /></Base>,
  Alert: (p: P) => <Base {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></Base>,
  Check: (p: P) => <Base {...p}><path d="M20 6 9 17l-5-5" /></Base>,
  Watch: (p: P) => <Base {...p}><rect x="6" y="6" width="12" height="12" rx="3" /><path d="M9 6l1-4h4l1 4M9 18l1 4h4l1-4M12 10v2l1 1" /></Base>,
  Plus: (p: P) => <Base {...p}><path d="M12 5v14M5 12h14" /></Base>,
  Lock: (p: P) => <Base {...p}><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></Base>,
  Logout: (p: P) => <Base {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></Base>,
  Sun: (p: P) => <Base {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Base>,
  Moon: (p: P) => <Base {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></Base>,
  Monitor: (p: P) => <Base {...p}><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></Base>,
  Menu: (p: P) => <Base {...p}><path d="M3 6h18M3 12h18M3 18h18" /></Base>,
  ArrowLeft: (p: P) => <Base {...p}><path d="M19 12H5M12 19l-7-7 7-7" /></Base>,
  Key: (p: P) => <Base {...p}><circle cx="7.5" cy="15.5" r="4.5" /><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3" /></Base>,
  Database: (p: P) => <Base {...p}><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></Base>,
  Eye: (p: P) => <Base {...p}><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></Base>,
  EyeOff: (p: P) => <Base {...p}><path d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-2.2 3.1M6.6 6.6A17.3 17.3 0 0 0 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M2 2l20 20" /></Base>,
  X: (p: P) =><Base {...p}><path d="M18 6 6 18M6 6l12 12" /></Base>,
};

export function initials(name: string) {
  return name
    .replace(/^(Dr\.?\s+)/i, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]!.toUpperCase())
    .join("");
}
