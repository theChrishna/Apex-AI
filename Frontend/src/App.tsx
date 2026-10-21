import React, { useEffect } from 'react';
import { useStore } from './store';
import { TopBar } from './components/TopBar';
import { Banner } from './components/Banner';
import { StatusHeadline } from './components/StatusHeadline';
import { Topology } from './components/Topology';
import { NodeDrawer } from './components/NodeDrawer';
import { ModuleHealth } from './components/ModuleHealth';
import { SafetyCard } from './components/SafetyCard';
import { RiskTimeline } from './components/RiskTimeline';
import { AuditLog } from './components/AuditLog';
import { PlaybackDock } from './components/PlaybackDock';
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
    selectedNode,
    setSelectedNode,
  } = useStore();

  // Active playback timer
  useEffect(() => {
    if (!isPlaying) return;

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

  // Sync theme class
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
      className="min-w-[1280px] min-h-screen bg-bg text-text flex flex-col font-sans transition-colors duration-300 pb-28"
    >
      {/* 1. Slim Top Strip & Main Header */}
      <TopBar />

      {/* 2. Scenario D Fallback Banner (Amber alert) */}
      <Banner />

      {/* 3. Main Narrative Body Container */}
      <main className="max-w-[1440px] w-full mx-auto px-6 lg:px-8 flex flex-col">
        {view === 'overview' ? (
          <div className="flex flex-col space-y-16 lg:space-y-20 pt-4">
            {/* FIRST SCREEN FOCUS: Live Status Hero Headline */}
            <StatusHeadline />

            {/* FIRST SCREEN FOCUS: Topology Stage + Detail Drawer */}
            <section
              aria-label="Topology stage"
              className="w-full flex flex-col lg:flex-row items-stretch gap-6 transition-all duration-300"
            >
              {/* Topology Stage (centered and wide if no selection; shifts left when drawer opens) */}
              <div className="flex-1 min-w-0 transition-all duration-300">
                <Topology />
              </div>

              {/* Detail Drawer (about 400px wide, opens on node click, closes on Esc) */}
              {selectedNode && (
                <NodeDrawer
                  nodeId={selectedNode}
                  onClose={() => setSelectedNode(null)}
                />
              )}
            </section>

            {/* SECTION 2: Module Health (4 compact pills in one row) */}
            <section aria-label="Module health" className="w-full">
              <ModuleHealth />
            </section>

            {/* SECTION 3: Safety Guardrails (FR-3.3: 4 small tiles in one row) */}
            <SafetyCard />

            {/* SECTION 4: Risk Over Time (full-width Recharts line chart) */}
            <RiskTimeline />

            {/* SECTION 5: Audit Trail (FR-3.4: full-width 5-column table) */}
            <AuditLog />
          </div>
        ) : (
          /* Second Tab: Comprehensive 8-Fold Cross-Validation Evaluation */
          <div className="w-full pt-8 pb-12">
            <EvalTab />
          </div>
        )}
      </main>

      {/* 4. Floating Playback Dock (Centered at bottom, hidden when chrome=0) */}
      <PlaybackDock />
    </div>
  );
};

export default App;
