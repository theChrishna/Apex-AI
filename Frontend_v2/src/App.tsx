import { createContext, useContext, useEffect, useState } from "react";
import { State, usePoll } from "./api";
import { Mark } from "./components/common";
import Overview from "./pages/Overview";
import LiveMesh from "./pages/LiveMesh";
import Incidents from "./pages/Incidents";
import Evaluation from "./pages/Evaluation";
import HowItWorks from "./pages/HowItWorks";

interface Ctx { state: State | null; error: string | null; reload: () => void }
const StateCtx = createContext<Ctx>({ state: null, error: null, reload: () => {} });
export const useMesh = () => useContext(StateCtx);

const ROUTES = [
  { path: "/", label: "Overview", el: <Overview /> },
  { path: "/mesh", label: "Live mesh", el: <LiveMesh /> },
  { path: "/incidents", label: "Incidents", el: <Incidents /> },
  { path: "/evaluation", label: "Evaluation", el: <Evaluation /> },
  { path: "/how", label: "How it works", el: <HowItWorks /> },
];

const routeOf = () => (window.location.hash.replace(/^#/, "") || "/");

function ThemeToggle() {
  const read = () => document.documentElement.getAttribute("data-theme") ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const [theme, setTheme] = useState(read);
  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("meshheal-theme", next); } catch { /* private mode */ }
    setTheme(next);
  };
  return (
    <button className="icon-btn" onClick={flip} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} title="Toggle theme">
      {theme === "dark"
        ? <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>}
    </button>
  );
}

export default function App() {
  const [route, setRoute] = useState(routeOf);
  const { data, error, reload } = usePoll<State>("/api/state", 2000);
  useEffect(() => {
    const on = () => { setRoute(routeOf()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const current = ROUTES.find((r) => r.path === route) ?? ROUTES[0];
  useEffect(() => { document.title = `${current.label} · MeshHeal AI`; }, [current]);
  return (
    <StateCtx.Provider value={{ state: data, error, reload }}>
      <a className="skip" href="#content">Skip to content</a>
      <header className="nav">
        <div className="nav-inner">
          <a className="brand" href="#/"><Mark /> MeshHeal AI</a>
          <nav className="links" aria-label="Main">
            {ROUTES.map((r) => <a key={r.path} href={`#${r.path}`} aria-current={r.path === current.path ? "page" : undefined}>{r.label}</a>)}
          </nav>
          <span className="spacer" />
          {data && <span className={`pill ${data.mode === "REPLAY" ? "warn" : "ok"}`} title={data.label}>{data.mode}</span>}
          <ThemeToggle />
        </div>
      </header>
      <main id="content" tabIndex={-1}>{current.el}</main>
      <footer className="footer">MeshHeal AI · 5th-semester mini project · one testbed (Istio Bookinfo), 8 fault episodes. See the Evaluation page for what this does and does not show.</footer>
    </StateCtx.Provider>
  );
}
