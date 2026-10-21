import React from 'react';
import { Play, Pause, RotateCcw } from 'lucide-react';
import { useStore } from '../store';
import { SCENARIOS } from '../data/scenarios';

export const PlaybackDock: React.FC = () => {
  const {
    chrome,
    scenarioId,
    t,
    setTime,
    isPlaying,
    togglePlay,
    speed,
    setSpeed,
    simulationState,
  } = useStore();

  if (chrome === 0) return null;

  const currentScenario = SCENARIOS.find((s) => s.id === scenarioId);
  const faultWindow = currentScenario?.faultWindow;
  const auditEvents = simulationState.audit;

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <aside
      aria-label="Simulation playback dock"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 floating-dock px-5 py-2.5 flex items-center gap-4 text-xs select-none max-w-2xl w-[92vw] sm:w-[620px] transition-all"
    >
      {/* Play / Pause */}
      <button
        onClick={togglePlay}
        className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold transition-all shrink-0 ${
          isPlaying
            ? 'bg-warn text-bg hover:opacity-90'
            : 'bg-primary text-white hover:opacity-90 shadow-sm'
        }`}
        title={isPlaying ? 'Pause simulation (Space)' : 'Play simulation (Space)'}
        aria-label={isPlaying ? 'Pause simulation' : 'Play simulation'}
      >
        {isPlaying ? <Pause className="w-3.5 h-3.5 fill-current" /> : <Play className="w-3.5 h-3.5 ml-0.5 fill-current" />}
      </button>

      {/* Reset */}
      <button
        onClick={() => setTime(0)}
        className="p-1.5 rounded-full text-muted hover:text-text transition-colors shrink-0"
        title="Reset scrubber to t=0"
        aria-label="Reset simulation to beginning"
      >
        <RotateCcw className="w-3.5 h-3.5" />
      </button>

      {/* Speed Selector */}
      <div className="flex bg-surface-2/80 rounded-pill p-0.5 border border-border text-[11px] font-mono shrink-0">
        {([1, 2, 4] as const).map((spd) => (
          <button
            key={spd}
            onClick={() => setSpeed(spd)}
            className={`px-2 py-0.5 rounded-pill transition-all ${
              speed === spd
                ? 'bg-primary text-white font-bold shadow-sm'
                : 'text-muted hover:text-text'
            }`}
          >
            {spd}x
          </button>
        ))}
      </div>

      {/* Scrubber Slider */}
      <div className="relative flex-1 flex flex-col justify-center min-w-[120px]">
        <div className="relative w-full h-5 flex items-center">
          {/* Fault Window Highlight */}
          {faultWindow && (
            <div
              className="absolute h-2.5 rounded-full bg-critical/25 border border-critical/40 pointer-events-none"
              style={{
                left: `${(faultWindow.start / 600) * 100}%`,
                width: `${((faultWindow.end - faultWindow.start) / 600) * 100}%`,
              }}
              title={`Fault: ${faultWindow.description} (${faultWindow.start}s - ${faultWindow.end}s)`}
            />
          )}

          {/* Audit Event Pins */}
          {auditEvents.map((evt, idx) => (
            <div
              key={idx}
              className="absolute w-1.5 h-3 bg-warn rounded-full -translate-x-1/2 pointer-events-none z-10 opacity-75"
              style={{ left: `${(evt.t / 600) * 100}%` }}
              title={`t=${evt.t}s: ${evt.type}`}
            />
          ))}

          {/* Slider input */}
          <input
            type="range"
            min={0}
            max={600}
            step={1}
            value={Math.round(t)}
            onChange={(e) => setTime(Number(e.target.value))}
            className="w-full h-1.5 bg-surface-2 border border-border rounded-lg appearance-none cursor-pointer accent-primary z-20 focus:outline-none"
            aria-label="Simulation time scrubber"
          />
        </div>
      </div>

      {/* Time Readout */}
      <div className="font-mono text-xs text-text tabular-nums shrink-0 px-2.5 py-1 rounded-pill bg-surface-2 border border-border">
        <span className="font-semibold text-text">{formatTime(t)}</span>
        <span className="text-muted ml-1">/ 10:00</span>
      </div>
    </aside>
  );
};
