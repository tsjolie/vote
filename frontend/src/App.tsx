import { Navigate, Link, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Dashboard from "./pages/Dashboard";
import CreatePoll from "./pages/CreatePoll";
import PollView from "./pages/PollView";
import Admin from "./pages/Admin";
import type { ReactNode } from "react";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="center muted">Loading…</div>;
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}

function Header() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        vote.sjolie.net
      </Link>
      <nav>
        {user.is_admin && <Link to="/admin">Admin</Link>}
        <span className="muted">{user.username}</span>
        <button className="link-btn" onClick={() => logout()}>
          Log out
        </button>
      </nav>
    </header>
  );
}

export default function App() {
  return (
    <>
      <Header />
      <main className="container">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <Dashboard />
              </RequireAuth>
            }
          />
          <Route
            path="/create"
            element={
              <RequireAuth>
                <CreatePoll />
              </RequireAuth>
            }
          />
          <Route
            path="/p/:slug"
            element={
              <RequireAuth>
                <PollView />
              </RequireAuth>
            }
          />
          <Route
            path="/admin"
            element={
              <RequireAuth>
                <Admin />
              </RequireAuth>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
