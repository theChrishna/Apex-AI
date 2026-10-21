import React from 'react';
import { Radio, Cpu, Shield, Network, CheckCircle2, AlertCircle, XCircle } from 'lucide-react';
import { useStore } from '../store';
import { ModuleStatus } from '../data/types';

interface HealthChipProps {
  title: string;
  subtitle: string;
  status: ModuleStatus;
  lastUpdate: string;
  note: string;
  icon: React.ReactNode;
}

const HealthChip: React.FC<HealthChipProps> = ({
  title,
  subtitle,
  status,
  lastUpdate,
  note,
  icon,
}) => {
  const statusColors = {
    ok: {
      border: 'border-teal-500/25 hover:border-teal-500/50',
      bgGlow: 'hover:shadow-glow-ok',
      badgeBg: 'bg-teal-500/10 border-teal-500/30 text-teal-300',
      dot: 'bg-teal-400 shadow-[0_0_8px_rgba(45,212,191,0.6)]',
      iconBox: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
      label: 'HEALTHY',
    },
    degraded: {
      border: 'border-amber-500/30 hover:border-amber-500/55',
      bgGlow: 'hover:shadow-glow-warn',
      badgeBg: 'bg-amber-500/15 border-amber-500/30 text-amber-300',
      dot: 'bg-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.6)]',
      iconBox: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
      label: 'DEGRADED',
    },
    down: {
      border: 'border-rose-500/40 hover:border-rose-500/70',
      bgGlow: 'hover:shadow-glow-crit',
      badgeBg: 'bg-rose-500/15 border-rose-500/30 text-rose-300',
      dot: 'bg-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.6)]',
      iconBox: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
      label: 'FAILED',
    },
  }[status];

  return (
    <div
      className={`glass-panel p-4 rounded-2xl flex flex-col justify-between transition-all duration-300 ${statusColors.border} ${statusColors.bgGlow}`}
    >
      {/* Upper row: Icon & Status Badge */}
      <div className="flex items-center justify-between gap-3 mb-2.5">
        <div className="flex items-center gap-3">
          <div className={`p-2.5 rounded-xl border ${statusColors.iconBox}`}>
            {icon}
          </div>
          <div>
            <h3 className="font-semibold text-xs tracking-tight text-text">{title}</h3>
            <p className="text-[11px] text-muted">{subtitle}</p>
          </div>
        </div>

        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-bold border tracking-wider ${statusColors.badgeBg}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${statusColors.dot}`} />
          <span>{statusColors.label}</span>
        </div>
      </div>

      {/* Lower row: Telemetry Note & Polling Frequency */}
      <div className="flex items-center justify-between text-xs font-mono text-muted pt-2 border-t border-border/50">
        <span className="truncate pr-2">{note}</span>
        <span className="text-[10px] text-text/80 font-medium shrink-0 px-1.5 py-0.5 rounded bg-surface-subtle">
          {lastUpdate}
        </span>
      </div>
    </div>
  );
};

export const ModuleHealth: React.FC = () => {
  const moduleHealth = useStore((s) => s.simulationState.moduleHealth);

  return (
    <div className="w-full">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3.5">
        <HealthChip
          title="Telemetry Poller"
          subtitle="Prometheus / Istio metrics"
          status={moduleHealth.telemetry.status}
          lastUpdate={moduleHealth.telemetry.lastUpdate}
          note={moduleHealth.telemetry.note}
          icon={<Radio className="w-4 h-4 text-cyan-400" />}
        />

        <HealthChip
          title="GNN Predictor"
          subtitle="Graph neural net inference"
          status={moduleHealth.gnnPredictor.status}
          lastUpdate={moduleHealth.gnnPredictor.lastUpdate}
          note={moduleHealth.gnnPredictor.note}
          icon={<Cpu className="w-4 h-4 text-indigo-400" />}
        />

        <HealthChip
          title="Control Plane"
          subtitle="VirtualService controller"
          status={moduleHealth.controlPlane.status}
          lastUpdate={moduleHealth.controlPlane.lastUpdate}
          note={moduleHealth.controlPlane.note}
          icon={<Shield className="w-4 h-4 text-purple-400" />}
        />

        <HealthChip
          title="Mesh Data Plane"
          subtitle="Istio Envoy Sidecars"
          status={moduleHealth.meshIstio.status}
          lastUpdate={moduleHealth.meshIstio.lastUpdate}
          note={moduleHealth.meshIstio.note}
          icon={<Network className="w-4 h-4 text-teal-400" />}
        />
      </div>
    </div>
  );
};
