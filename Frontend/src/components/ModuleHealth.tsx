import React, { useState } from 'react';
import { Radio, Cpu, Shield, Network } from 'lucide-react';
import { useStore } from '../store';
import { ModuleStatus } from '../data/types';

interface HealthPillProps {
  id: string;
  name: string;
  status: ModuleStatus;
  fact: string;
  icon: React.ReactNode;
}

const HealthPill: React.FC<HealthPillProps> = ({ name, status, fact, icon }) => {
  const [isHovered, setIsHovered] = useState(false);

  const dotColor = {
    ok: 'bg-ok shadow-[0_0_8px_rgba(52,214,176,0.6)]',
    degraded: 'bg-warn shadow-[0_0_8px_rgba(255,179,71,0.6)]',
    down: 'bg-critical shadow-[0_0_8px_rgba(255,92,124,0.6)]',
  }[status];

  const statusLabel = {
    ok: 'Healthy',
    degraded: 'Degraded',
    down: 'Offline',
  }[status];

  return (
    <div
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="relative flex-1"
    >
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-pill bg-surface border border-border hover:border-border-strong transition-all cursor-pointer shadow-sm">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="text-muted shrink-0">{icon}</span>
          <span className="font-medium text-xs text-text truncate">{name}</span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className={`w-2 h-2 rounded-full ${dotColor}`} />
          <span className="text-[11px] font-mono text-muted">{statusLabel}</span>
        </div>
      </div>

      {/* Detail Popover on Hover (Allowed Facts Only) */}
      {isHovered && (
        <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-40 bg-surface border border-border shadow-card rounded-xl px-3 py-1.5 text-xs font-mono text-text whitespace-nowrap pointer-events-none animate-pulse-subtle">
          <span>{fact}</span>
        </div>
      )}
    </div>
  );
};

export const ModuleHealth: React.FC = () => {
  const { simulationState, scenarioId, t } = useStore();
  const isGnnDown = scenarioId === 'D' && t >= 200;

  return (
    <div className="w-full">
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
        <HealthPill
          id="telemetry"
          name="Telemetry"
          status="ok"
          fact="15 s poll • 1 min rate window"
          icon={<Radio className="w-4 h-4 text-ok" />}
        />

        <HealthPill
          id="gnn"
          name="GNN Predictor"
          status={isGnnDown ? 'down' : 'ok'}
          fact={isGnnDown ? 'Inference timed out (>500 ms); static fallback engaged' : '500 ms timeout budget'}
          icon={<Cpu className="w-4 h-4 text-primary" />}
        />

        <HealthPill
          id="control"
          name="Control Plane"
          status="ok"
          fact="Simulated autonomous remediation engine"
          icon={<Shield className="w-4 h-4 text-warn" />}
        />

        <HealthPill
          id="mesh"
          name="Service Mesh"
          status="ok"
          fact="4 services deployed in aws-us-east"
          icon={<Network className="w-4 h-4 text-ok" />}
        />
      </div>
    </div>
  );
};
