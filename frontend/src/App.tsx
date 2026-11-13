import { createContext, lazy, Suspense, useContext, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, Me } from "./api";
import { Icon, initials } from "./components/Icons";
import { Theme, useTheme } from "./theme";
import Login from "./pages/Login";
import { ForcedPasswordChange } from "./pages/Account";

// Each area loads on demand so a patient never downloads the admin or clinician code.
const PatientHome = lazy(() => import("./pages/PatientHome"));
const Worklist = lazy(() => import("./pages/Worklist"));
const PatientDetail = lazy(() => import("./pages/PatientDetail"));
const Admin = lazy(() => import("./pages/Admin"));
const Account = lazy(() => import("./pages/Account"));
const DeviceGuide = lazy(() => import("./pages/DeviceGuide"));

interface AuthCtx {
  me: Me | null;
  setMe: (m: Me | null) => void;
  theme: Theme;
}
const Ctx = createContext<AuthCtx>({ me: null, setMe: () => {}, theme: "light" });
export const useAuth = () => useContext(Ctx);

export function homeFor(me: Me): string {
  return me.role === "admin" ? "/admin/users" : me.role === "clinician" ? "/worklist" : "/me";
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [theme, setTheme] = useTheme();

  useEffect(() => {
    api<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setReady(true));
  }, []);

  if (!ready) return <div className="center muted">Loading…</div>;

  return (
    <Ctx.Provider value={{ me, setMe, theme }}>
      {me && me.must_change_password ? (
        <ForcedPasswordChange />
      ) : me ? (
        <Shell me={me} theme={theme} setTheme={setTheme}>
          <Suspense fallback={<div className="muted">Loading…</div>}>
          <Routes>
            {me.role === "patient" && <Route path="/me" element={<PatientHome />} />}
            {me.role === "clinician" && <Route path="/worklist" element={<Worklist />} />}
            {me.role === "clinician" && <Route path="/patients/:id" element={<PatientDetail />} />}
            {me.role === "admin" && <Route path="/admin/*" element={<Admin />} />}
            <Route path="/account" element={<Account />} />
            <Route path="/devices/guide" element={<DeviceGuide />} />
            <Route path="*" element={<Navigate to={homeFor(me)} replace />} />
          </Routes>
          </Suspense>
        </Shell>
      ) : (
        <Routes>
          <Route path="*" element={<Login />} />
        </Routes>
      )}
    </Ctx.Provider>
  );
}

const NAV: Record<string, { to: string; label: string; icon: keyof typeof Icon }[]> = {
  patient: [
    { to: "/me", label: "My health", icon: "Heart" },
    { to: "/devices/guide", label: "Help with devices", icon: "Watch" },
  ],
  clinician: [
    { to: "/worklist", label: "Patient worklist", icon: "Grid" },
    { to: "/devices/guide", label: "Device guide", icon: "Watch" },
  ],
  admin: [
    { to: "/admin/users", label: "People", icon: "Users" },
    { to: "/admin/import", label: "Bulk import", icon: "Database" },
    { to: "/admin/assignments", label: "Care teams", icon: "Link" },
    { to: "/admin/devices", label: "Devices & pairing", icon: "Watch" },
    { to: "/devices/guide", label: "Device guide", icon: "Inbox" },
    { to: "/admin/simulator", label: "Data sources", icon: "Play" },
    { to: "/admin/audit", label: "Privacy ledger", icon: "Ledger" },
    { to: "/admin/security", label: "Keys & algorithms", icon: "Shield" },
  ],
};

const CRUMB: Record<string, string> = {
  "/me": "My health", "/worklist": "Patient worklist", "/admin/users": "People", "/admin/assignments": "Care teams",
  "/admin/devices": "Devices & pairing", "/admin/simulator": "Data sources", "/admin/audit": "Privacy ledger",
  "/admin/security": "Keys & algorithms", "/admin/import": "Bulk import", "/account": "Sign-in & security",
  "/devices/guide": "Device guide",
};

function Shell({ me, theme, setTheme, children }: { me: Me; theme: Theme; setTheme: (t: Theme) => void; children: React.ReactNode }) {
  const { setMe } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [loc.pathname]);

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setMe(null);
    nav("/");
  };
  const crumb = CRUMB[loc.pathname] ?? (loc.pathname.startsWith("/patients/") ? "Patient record" : "");

  return (
    <div className="shell">
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Main navigation">
        <div className="side-brand">
          <span className="mark"><Icon.Logo size={18} /></span>
          <span className="name">Vitalcare</span>
        </div>
        <div className="side-section">
          <div className="side-label">{me.role === "admin" ? "Administration" : "Care workspace"}</div>
          <nav className="side-nav">
            {NAV[me.role].map((n) => {
              const I = Icon[n.icon];
              return (
                <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive || (n.to === "/worklist" && loc.pathname.startsWith("/patients/")) ? "active" : "")}>
                  <I size={18} />
                  {n.label}
                </NavLink>
              );
            })}
          </nav>
        </div>
        <div className="side-note">
          <div className="title">End-to-end encrypted vitals.</div>
          <p>Readings are sealed on the device and decrypted only for people with an active care relationship and consent.</p>
        </div>
        <div className="side-foot">
          <div className="theme-switch" role="radiogroup" aria-label="Colour theme">
            {(["light", "dark", "system"] as Theme[]).map((t) => (
              <button key={t} role="radio" aria-checked={theme === t} className={theme === t ? "on" : ""} onClick={() => setTheme(t)}>
                {t === "light" ? <Icon.Sun size={13} /> : t === "dark" ? <Icon.Moon size={13} /> : <Icon.Monitor size={13} />}
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          <NavLink to="/account" className="side-user" style={{ textDecoration: "none", color: "inherit" }}>
            <span className="avatar">{initials(me.full_name)}</span>
            <div className="who">
              <b>{me.full_name}</b>
              <span>{me.role} · account</span>
            </div>
          </NavLink>
          <button className="signout" onClick={logout}>
            <Icon.Logout size={16} /> Sign out
          </button>
        </div>
      </aside>
      {open && <div className="backdrop" style={{ zIndex: 30 }} onClick={() => setOpen(false)} />}
      <div className="main">
        <header className="topbar">
          <button className="btn ghost sm mobile-menu" aria-label="Open menu" onClick={() => setOpen(true)}>
            <Icon.Menu />
          </button>
          <div className="crumbs">
            <span>Workspace</span>/<b>{crumb}</b>
          </div>
          <div className="right">
            <span className="status-dot">Encrypted connection</span>
            <span className="avatar" title={me.full_name}>{initials(me.full_name)}</span>
          </div>
        </header>
        <main className="content">{children}</main>
        <footer className="footer">Vitalcare · educational project, not a certified medical device · decision support only, no diagnosis is made.</footer>
      </div>
    </div>
  );
}
