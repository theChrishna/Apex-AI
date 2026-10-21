import React, { useEffect } from 'react';
import { useStore } from './store';
import { TopBar } from './components/TopBar';
import { Banner } from './components/Banner';
import { ModuleHealth } from './components/ModuleHealth';
import { Topology } from './components/Topology';
import { NodePanel } from './components/NodePanel';
import { SafetyCard } from './components/SafetyCard';
import { RiskTimeline } from './components/RiskTimeline';
import { AuditLog } from './components/AuditLog';
import { EvalTab } from './components/EvalTab';

export const App: React.FC = () => {
  const {
    view,
    theme,
    isPlaying,
    togglePlay,
    setTime,
    t,
    tick,
  } = useStore();

  // Active playback timer
  useEffect(() => {
    if (!isPlaying) return;

    // 250ms interval advancing 0.25s
    const timer = setInterval(() => {
      tick(0.25);
    }, 250);

    return () => clearInterval(timer);
  }, [isPlaying, tick]);

  // Keyboard navigation: Space toggles play/pause, Left/Right arrow scrubs time
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't capture when typing in form inputs
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        return;
      }

      if (e.code === 'Space') {
        e.preventDefault();
        togglePlay();
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault();
        setTime(Math.max(0, t - 5));
      } else if (e.code === 'ArrowRight') {
        e.preventDefault();
        setTime(Math.min(600, t + 5));
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [togglePlay, setTime, t]);

  // Set html class according to theme
  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.classList.add('light');
    } else {
      document.documentElement.classList.remove('light');
    }
  }, [theme]);

  return (
    <div
      data-paused={!isPlaying}
      className="min-w-[1280px] min-h-screen bg-bg text-text flex flex-col font-sans transition-colors duration-200"
    >
      {/* 1. Header with Firefox-inspired polish, brand aura & time scrubber */}
      <TopBar />

      {/* 2. Amber fallback alert banner (Scenario D) */}
      <Banner />

      {/* 3. Main Dashboard Body Container with generous breathing space */}
      <main className="flex-1 max-w-[1780px] w-full mx-auto px-5 lg:px-8 py-6 flex flex-col gap-6">
        {view === 'overview' ? (
          <>
            {/* Health Strip Tier */}
            <ModuleHealth />

            {/* Upper Tier: 60% Topology / 40% Diagnostics & Guardrails */}
            <div className="grid grid-cols-12 gap-6 min-h-[500px]">
              {/* Left 60%: Cytoscape Topology */}
              <div className="col-span-12 xl:col-span-7 h-full">
                <Topology />
              </div>

              {/* Right 40%: Node Diagnostics & Safety Card */}
              <div className="col-span-12 xl:col-span-5 flex flex-col gap-6 h-full">
                <div className="flex-1 min-h-[320px]">
                  <NodePanel />
                </div>
                <div className="shrink-0">
                  <SafetyCard />
                </div>
              </div>
            </div>

            {/* Lower Tier: 50% Risk & Latency Timeline / 50% Audit Log */}
            <div className="grid grid-cols-12 gap-6 min-h-[340px]">
              {/* Bottom Left: Recharts Risk & Latency Timeline */}
              <div className="col-span-12 xl:col-span-6 h-full">
                <RiskTimeline />
              </div>

              {/* Bottom Right: Audit Log Table */}
              <div className="col-span-12 xl:col-span-6 h-full">
                <AuditLog />
              </div>
            </div>
          </>
        ) : (
          /* Second Tab: Comprehensive Model Evaluation Benchmark */
          <div className="w-full">
            <EvalTab />
          </div>
        )}
      </main>
    </div>
  );
};

export default App;
