import React, { useEffect } from 'react';
import {
  Sun,
  Moon,
  ChevronDown,
  Layers,
  BarChart3,
  AlertCircle,
  Database,
  Network,
} from 'lucide-react';
import { useStore } from '../store';
import { SCENARIOS } from '../data/scenarios';

export const TopBar: React.FC = () => {
  const {
    view,
    setView,
    theme,
    setTheme,
    scenarioId,
    setScenario,
    replayEpisodes,
    selectedReplayEpisode,
    setReplayEpisode,
    checkReplay,
  } = useStore();

  useEffect(() => {
    checkReplay();
  }, [checkReplay]);

  const isReplay = scenarioId === 'F';

  return (
    <div className="w-full select-none z-30">
      {/* 1. Slim Top Honesty Strip (Burned into UI & export) */}
      <div
        id="honesty-badge"
        className={`w-full py-1 px-4 text-center text-xs font-mono font-medium tracking-tight border-b transition-colors ${
          isReplay
            ? 'bg-blue-500/10 text-blue-300 border-blue-500/20'
            : 'bg-amber-500/10 text-amber-300 border-amber-500/20'
        }`}
        title={
          isReplay
            ? 'Real edge telemetry replayed from disk; risk and remediation simulated.'
            : 'Synthetic edge telemetry and simulated control plane.'
        }
      >
        <span className="inline-flex items-center gap-1.5">
          <AlertCircle className="w-3.5 h-3.5 shrink-0 opacity-80" />
          <span>
            {isReplay
              ? 'REPLAY OF RECORDED TELEMETRY; risk and remediation simulated'
              : 'SIMULATED DATA - control plane not yet implemented'}
          </span>
        </span>
      </div>

      {/* 2. Main Navigation Header */}
      <header className="max-w-[1440px] mx-auto px-6 py-4 flex items-center justify-between gap-4">
        {/* Left: Brand / Logo */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-2xl bg-primary flex items-center justify-center text-white shadow-sm shrink-0">
            <Network className="w-5 h-5" />
          </div>
          <div>
            <span className="font-bold text-lg tracking-tight text-text">MeshHeal AI</span>
          </div>
        </div>

        {/* Center: Clean Segmented Pill Tabs */}
        <nav aria-label="Console views" className="flex bg-surface-2 p-1 rounded-pill border border-border shadow-sm">
          <button
            onClick={() => setView('overview')}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-pill text-xs font-medium transition-all ${
              view === 'overview'
                ? 'bg-primary text-white font-semibold shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Operations</span>
          </button>
          <button
            onClick={() => setView('evaluation')}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-pill text-xs font-medium transition-all ${
              view === 'evaluation'
                ? 'bg-primary text-white font-semibold shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Evaluation</span>
          </button>
        </nav>

        {/* Right: Scenario Selector & Theme Toggle */}
        <div className="flex items-center gap-3">
          {/* Scenario Selector Dropdown */}
          <div className="relative">
            <select
              id="scenario-select"
              value={scenarioId}
              onChange={(e) => setScenario(e.target.value)}
              className="appearance-none bg-surface-2 border border-border hover:border-border-strong text-text font-medium rounded-pill pl-4 pr-8 py-1.5 text-xs focus:ring-2 focus:ring-primary/40 outline-none transition-all cursor-pointer shadow-sm"
              aria-label="Select scenario"
            >
              {SCENARIOS.map((s) => (
                <option key={s.id} value={s.id}>
                  Scenario {s.id}: {s.name}
                </option>
              ))}
              {replayEpisodes && replayEpisodes.size > 0 && (
                <option value="F">Scenario F: Replay recorded episode</option>
              )}
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-muted absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* Episode picker if replay mode */}
          {isReplay && replayEpisodes && (
            <div className="relative">
              <select
                value={selectedReplayEpisode || ''}
                onChange={(e) => setReplayEpisode(e.target.value)}
                className="appearance-none bg-blue-950/40 border border-blue-500/30 text-blue-200 font-mono text-xs rounded-pill pl-3 pr-7 py-1.5 outline-none cursor-pointer"
                aria-label="Select recorded episode"
              >
                {Array.from(replayEpisodes.keys()).map((ep) => (
                  <option key={ep} value={ep}>
                    {ep}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3 h-3 text-blue-300 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          )}

          {/* Theme Switcher */}
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="p-2 rounded-pill border border-border bg-surface-2 text-muted hover:text-text transition-all shadow-sm"
            title={`Switch to ${theme === 'dark' ? 'Light print' : 'Dark console'} theme`}
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-300" /> : <Moon className="w-4 h-4 text-primary" />}
          </button>
        </div>
      </header>
    </div>
  );
};
