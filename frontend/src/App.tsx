import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api, Me } from "./api";
import Login from "./pages/Login";
import PatientHome from "./pages/PatientHome";
import Worklist from "./pages/Worklist";
import PatientDetail from "./pages/PatientDetail";
import Admin from "./pages/Admin";

interface AuthCtx {
  me: Me | null;
  setMe: (m: Me | null) => void;
}
const Ctx = createContext<AuthCtx>({ me: null, setMe: () => {} });
export const useAuth = () => useContext(Ctx);

export function homeFor(me: Me): string {
  return me.role === "admin" ? "/admin" : me.role === "clinician" ? "/worklist" : "/me";
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setReady(true));
  }, []);

  if (!ready) return <div className="center muted">Loading…</div>;

  return (
    <Ctx.Provider value={{ me, setMe }}>
      {me ? (
        <Shell me={me}>
          <Routes>
            {me.role === "patient" && <Route path="/me" element={<PatientHome />} />}
            {me.role === "clinician" && <Route path="/worklist" element={<Worklist />} />}
            {me.role === "clinician" && <Route path="/patients/:id" element={<PatientDetail />} />}
            {me.role === "admin" && <Route path="/admin/*" element={<Admin />} />}
            <Route path="*" element={<Navigate to={homeFor(me)} replace />} />
          </Routes>
        </Shell>
      ) : (
        <Routes>
          <Route path="*" element={<Login />} />
        </Routes>
      )}
    </Ctx.Provider>
  );
}

function Shell({ me, children }: { me: Me; children: React.ReactNode }) {
  const { setMe } = useAuth();
  const nav = useNavigate();
  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setMe(null);
    nav("/");
  };
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M2 12h4l2-5 4 10 3-7 2 2h5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          SecureRPM
        </div>
        <nav className="nav">
          {me.role === "clinician" && <NavLink to="/worklist">Worklist</NavLink>}
          {me.role === "patient" && <NavLink to="/me">My health</NavLink>}
          {me.role === "admin" && (
            <>
              <NavLink to="/admin/users">Users</NavLink>
              <NavLink to="/admin/assignments">Assignments</NavLink>
              <NavLink to="/admin/simulator">Simulator</NavLink>
              <NavLink to="/admin/audit">Audit log</NavLink>
              <NavLink to="/admin/security">Security</NavLink>
            </>
          )}
        </nav>
        <div className="who">
          <span>
            {me.full_name} <span className="role">{me.role}</span>
          </span>
          <button className="ghost" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">{children}</main>
      <footer className="footer">Educational project, not a certified medical device.</footer>
    </div>
  );
}
