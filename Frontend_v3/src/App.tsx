import { createContext, useContext, useEffect, useState } from "react";
import { CalendarDays, Moon, Sun } from "lucide-react";
import { State, fmtStamp, usePoll } from "./api";
import { Mark } from "./components/common";
import Home from "./pages/Home";
import Overview from "./pages/Overview";
import Incidents from "./pages/Incidents";
import Evaluation from "./pages/Evaluation";
import HowItWorks from "./pages/HowItWorks";
import Fleet from "./pages/Fleet";

interface Ctx { state: State | null; error: string | null; reload: () => void }
const StateCtx = createContext<Ctx>({ state: null, error: null, reload: () => {} });
export const useMesh = () => useContext(StateCtx);

// `alias`: an older hash that still opens the page (Live mesh was merged into Overview)
const ROUTES = [
  { path: "/", label: "Home", el: <Home /> },
  { path: "/overview", alias: "/mesh", label: "Overview", el: <Overview /> },
  { path: "/incidents", label: "Incidents", el: <Incidents /> },
  { path: "/evaluation", label: "Evaluation", el: <Evaluation /> },
  { path: "/how", label: "How it works", el: <HowItWorks /> },
  { path: "/fleet", label: "Fleet", el: <Fleet /> },
];

const routeOf = () => (window.location.hash.replace(/^#/, "").split("?")[0] || "/");

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
      {theme === "dark" ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
    </button>
  );
}

function ReplayControls({ state, reload }: { state: State; reload: () => void }) {
  const r = state.replay;
  if (!r) return null;
  const ctl = async (q: string) => { await fetch(`/api/replay/control?${q}`); reload(); };
  return (
    <span className="replay-ctl" role="group" aria-label="Replay controls">
      <button className="btn small" aria-pressed={r.speed === 1} onClick={() => ctl("speed=1")}>1×</button>
      <button className="btn small" aria-pressed={r.speed === 10} onClick={() => ctl("speed=10")}>10×</button>
      <button className="btn small" onClick={() => ctl("restart=1")}>Restart</button>
    </span>
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
  const current = ROUTES.find((r) => r.path === route || r.alias === route) ?? ROUTES[0];
  useEffect(() => { document.title = `${current.label} · MeshHeal AI`; }, [current]);
  return (
    <StateCtx.Provider value={{ state: data, error, reload }}>
      <a className="skip" href="#content">Skip to content</a>
      <header className="top">
        <a className="brand" href="#/"><Mark size={26} /> MeshHeal AI</a>
        <nav className="links" aria-label="Main">
          {ROUTES.map((r) => <a key={r.path} href={`#${r.path}`} aria-current={r.path === current.path ? "page" : undefined}>{r.label}</a>)}
        </nav>
        <div className="top-tools">
          {data && <ReplayControls state={data} reload={reload} />}
          {data && <span className="chip" title={data.mode === "REPLAY" ? "Position inside the recorded run (UTC)" : "Current time (UTC)"}><CalendarDays size={16} aria-hidden="true" />{fmtStamp(data.now)}</span>}
          {data && <span className={`chip status ${data.mode === "REPLAY" ? "warn" : "ok"}${data.status.controller_running ? " pulse" : ""}`} title={data.label}>{data.mode}</span>}
          <ThemeToggle />
        </div>
      </header>
      <main id="content" tabIndex={-1}>{current.el}</main>
      {current.path !== "/" && current.path !== "/fleet" && <footer className="footer">MeshHeal AI · 5th-semester mini project · one testbed (Istio Bookinfo), 8 fault episodes. See the Evaluation page for what this does and does not show.</footer>}
    </StateCtx.Provider>
  );
}
