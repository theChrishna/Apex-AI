import React, { useEffect } from 'react';
import {
  Play,
  Pause,
  Sun,
  Moon,
  RotateCcw,
  Sparkles,
  Layers,
  BarChart3,
  AlertCircle,
  Database,
  ChevronDown,
} from 'lucide-react';
import { useStore } from '../store';
import { SCENARIOS } from '../data/scenarios';

export const TopBar: React.FC = () => {
  const {
    view,
    setView,
    theme,
    setTheme,
    chrome,
    scenarioId,
    setScenario,
    t,
    setTime,
    isPlaying,
    togglePlay,
    speed,
    setSpeed,
    replayEpisodes,
    selectedReplayEpisode,
    setReplayEpisode,
    simulationState,
    checkReplay,
  } = useStore();

  useEffect(() => {
    checkReplay();
  }, [checkReplay]);

  const currentScenario = SCENARIOS.find((s) => s.id === scenarioId);
  const faultWindow = currentScenario?.faultWindow;
  const isReplay = scenarioId === 'F';
  const auditEvents = simulationState.audit;

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <header className="sticky top-0 z-40 w-full backdrop-blur-xl bg-surface/85 border-b border-border/80 transition-colors shadow-sm">
      <div className="max-w-[1780px] mx-auto px-5 lg:px-8 py-3.5 flex flex-col gap-3.5">
        {/* Top Tier: Logo, Honesty Badge, View Navigation, Theme Toggle */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          {/* Logo & Brand Identity */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-3">
              {/* Firefox-inspired glowing gradient icon */}
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 via-purple-500 to-cyan-400 p-[1px] shadow-glow-accent shrink-0">
                <div className="w-full h-full rounded-[11px] bg-surface flex items-center justify-center">
                  <Sparkles className="w-4 h-4 text-cyan-300" />
                </div>
              </div>

              <div>
                <div className="flex items-center gap-2.5">
                  <span className="font-bold text-base tracking-tight text-text">
                    MeshHeal <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 via-cyan-400 to-teal-300">AI</span>
                  </span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface-subtle border border-border text-muted font-medium">
                    v0.9-prototype
                  </span>
                </div>
                <p className="text-xs text-muted hidden sm:block">
                  Autonomous Service-Mesh Self-Healing Prototype
                </p>
              </div>
            </div>

            {/* Persistent Non-Negotiable Honesty Badge */}
            <div
              id="honesty-badge"
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-mono font-medium border shadow-sm transition-all ${
                isReplay
                  ? 'bg-blue-500/10 text-blue-300 border-blue-500/30'
                  : 'bg-amber-500/10 text-amber-300 border-amber-500/30'
              }`}
              title={
                isReplay
                  ? 'Real edge telemetry replayed from disk; risk and remediation simulated.'
                  : 'Synthetic edge telemetry and simulated control plane.'
              }
            >
              <AlertCircle className="w-3.5 h-3.5 shrink-0 text-amber-400" />
              <span className="tracking-tight">
                {isReplay
                  ? 'REPLAY OF RECORDED TELEMETRY; risk and remediation simulated'
                  : 'SIMULATED DATA - control plane not yet implemented'}
              </span>
            </div>
          </div>

          {/* Right Action Cluster: View Switcher & Theme */}
          <div className="flex items-center gap-3.5">
            {/* View Selector Switcher */}
            <nav
              aria-label="Console views"
              className="flex bg-surface-subtle/80 backdrop-blur border border-border/80 rounded-xl p-1 shadow-inner text-xs font-medium"
            >
              <button
                onClick={() => setView('overview')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg transition-all ${
                  view === 'overview'
                    ? 'bg-accent text-white shadow-sm font-semibold'
                    : 'text-muted hover:text-text'
                }`}
              >
                <Layers className="w-4 h-4" />
                <span>Operations Console</span>
              </button>
              <button
                onClick={() => setView('evaluation')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg transition-all ${
                  view === 'evaluation'
                    ? 'bg-accent text-white shadow-sm font-semibold'
                    : 'text-muted hover:text-text'
                }`}
              >
                <BarChart3 className="w-4 h-4" />
                <span>Evaluation (8 Folds)</span>
              </button>
            </nav>

            {/* Theme Toggle Button */}
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="p-2 rounded-xl border border-border bg-surface-subtle/80 hover:bg-surface-elevated text-muted hover:text-text transition-all shadow-sm"
              title={`Switch to ${theme === 'dark' ? 'Light print' : 'Dark console'} theme`}
              aria-label="Toggle visual theme"
            >
              {theme === 'dark' ? (
                <Sun className="w-4 h-4 text-amber-300" />
              ) : (
                <Moon className="w-4 h-4 text-indigo-500" />
              )}
            </button>
          </div>
        </div>

        {/* Lower Tier: Scenario Controls & Spacious Scrubber (rendered unless chrome=0) */}
        {chrome !== 0 && (
          <div className="flex flex-wrap items-center justify-between gap-4 pt-2.5 border-t border-border/40 text-xs">
            {/* Left: Scenario Select Box */}
            <div className="flex items-center gap-3">
              <label htmlFor="scenario-select" className="text-muted font-medium shrink-0">
                Scenario:
              </label>

              <div className="relative">
                <select
                  id="scenario-select"
                  value={scenarioId}
                  onChange={(e) => setScenario(e.target.value)}
                  className="appearance-none bg-surface-subtle border border-border hover:border-border-strong text-text font-medium rounded-xl pl-3.5 pr-8 py-1.5 text-xs focus:ring-2 focus:ring-accent/50 outline-none transition-all cursor-pointer shadow-sm"
                >
                  {SCENARIOS.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.id}: {s.name}
                    </option>
                  ))}
                  {replayEpisodes && replayEpisodes.size > 0 && (
                    <option value="F">F: Replay recorded episode</option>
                  )}
                </select>
                <ChevronDown className="w-3.5 h-3.5 text-muted absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              </div>

              {/* Episode selector for Replay */}
              {isReplay && replayEpisodes && (
                <div className="flex items-center gap-2 pl-2 border-l border-border">
                  <Database className="w-3.5 h-3.5 text-cyan-400" />
                  <div className="relative">
                    <select
                      value={selectedReplayEpisode || ''}
                      onChange={(e) => setReplayEpisode(e.target.value)}
                      className="appearance-none bg-cyan-950/30 border border-cyan-500/40 text-cyan-200 font-mono text-xs rounded-lg pl-2.5 pr-7 py-1 outline-none cursor-pointer"
                    >
                      {Array.from(replayEpisodes.keys()).map((ep) => (
                        <option key={ep} value={ep}>
                          {ep}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="w-3 h-3 text-cyan-400 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
                  </div>
                </div>
              )}
            </div>

            {/* Right: Playback Controls & Continuous Scrubber */}
            <div className="flex items-center gap-3.5 flex-1 max-w-3xl min-w-[340px]">
              {/* Play/Pause Button */}
              <button
                onClick={togglePlay}
                className={`p-2 rounded-xl border font-semibold flex items-center justify-center transition-all shadow-sm ${
                  isPlaying
                    ? 'bg-warn/15 text-warn border-warn/40 hover:bg-warn/25'
                    : 'bg-accent text-white border-accent hover:opacity-90 shadow-glow-accent'
                }`}
                title={isPlaying ? 'Pause simulation (Space)' : 'Play simulation (Space)'}
                aria-label={isPlaying ? 'Pause simulation' : 'Play simulation'}
              >
                {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 ml-0.5 fill-current" />}
              </button>

              {/* Reset to Start */}
              <button
                onClick={() => setTime(0)}
                className="p-2 rounded-xl border border-border bg-surface-subtle hover:bg-surface-elevated text-muted hover:text-text transition-all"
                title="Reset scrubber to t=0"
                aria-label="Reset simulation to beginning"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>

              {/* Playback Speed Pill */}
              <div className="flex bg-surface-subtle border border-border rounded-xl p-1 text-[11px] font-mono">
                {([1, 2, 4] as const).map((spd) => (
                  <button
                    key={spd}
                    onClick={() => setSpeed(spd)}
                    className={`px-2 py-0.5 rounded-lg transition-all ${
                      speed === spd
                        ? 'bg-accent text-white font-bold shadow-sm'
                        : 'text-muted hover:text-text'
                    }`}
                  >
                    {spd}x
                  </button>
                ))}
              </div>

              {/* Spacious Scrubber Slider with Fault Window & Event Markers */}
              <div className="relative flex-1 flex flex-col justify-center px-1">
                <div className="relative w-full h-6 flex items-center">
                  {/* Fault Window Highlight Behind Track */}
                  {faultWindow && (
                    <div
                      className="absolute h-3 rounded-full bg-red-500/25 border border-red-500/40 pointer-events-none transition-all"
                      style={{
                        left: `${(faultWindow.start / 600) * 100}%`,
                        width: `${((faultWindow.end - faultWindow.start) / 600) * 100}%`,
                      }}
                      title={`Fault Window: ${faultWindow.description} (${faultWindow.start}s - ${faultWindow.end}s)`}
                    />
                  )}

                  {/* Audit Event Markers */}
                  {auditEvents.map((evt, idx) => (
                    <div
                      key={idx}
                      className="absolute w-2 h-3.5 bg-amber-400 rounded-full -translate-x-1/2 pointer-events-none z-10 opacity-80 shadow-sm"
                      style={{ left: `${(evt.t / 600) * 100}%` }}
                      title={`t=${evt.t}s [${evt.type}]: ${evt.detail}`}
                    />
                  ))}

                  {/* Input Slider */}
                  <input
                    type="range"
                    min={0}
                    max={600}
                    step={1}
                    value={Math.round(t)}
                    onChange={(e) => setTime(Number(e.target.value))}
                    className="w-full h-2 bg-surface-subtle border border-border rounded-lg appearance-none cursor-pointer accent-accent z-20 focus:outline-none"
                    aria-label="Simulation time scrubber"
                  />
                </div>
              </div>

              {/* Formatted Time Readout */}
              <div className="font-mono text-xs text-text tabular-nums shrink-0 px-2.5 py-1 rounded-lg bg-surface-subtle border border-border">
                <span className="font-semibold text-text">{formatTime(t)}</span>
                <span className="text-muted ml-1">/ 10:00</span>
                <span className="text-[10px] text-muted ml-1.5 hidden md:inline">({Math.round(t)}s)</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </header>
  );
};
