import React, { useState } from 'react';
import { Camera, Filter, ShieldAlert, ArrowRight } from 'lucide-react';
import { useStore } from '../store';
import { AuditEntry, AuditType } from '../data/types';
import { exportComponentPng } from '../utils/exportPng';

const TYPE_STYLES: Record<
  AuditType,
  { bg: string; text: string; border: string; label: string }
> = {
  REROUTE_APPLIED: {
    bg: 'bg-teal-500/15',
    text: 'text-ok',
    border: 'border-teal-500/30',
    label: 'REROUTE',
  },
  ACTION_BLOCKED: {
    bg: 'bg-amber-500/15',
    text: 'text-warn',
    border: 'border-amber-500/30',
    label: 'BLOCKED',
  },
  FAULT_INJECTED: {
    bg: 'bg-purple-500/15',
    text: 'text-purple-300',
    border: 'border-purple-500/30',
    label: 'FAULT',
  },
  THRESHOLD_CROSSED: {
    bg: 'bg-yellow-500/15',
    text: 'text-yellow-300',
    border: 'border-yellow-500/30',
    label: 'THRESHOLD',
  },
  FALLBACK_ACTIVATED: {
    bg: 'bg-orange-500/15',
    text: 'text-orange-300',
    border: 'border-orange-500/30',
    label: 'FALLBACK',
  },
  RECOVERED: {
    bg: 'bg-teal-500/15',
    text: 'text-ok',
    border: 'border-teal-500/30',
    label: 'RECOVERED',
  },
};

export const AuditLog: React.FC = () => {
  const { simulationState, setTime, scenarioId, t } = useStore();
  const [filterType, setFilterType] = useState<string>('ALL');

  const auditList = simulationState.audit;

  // Filter and sort newest first
  const filteredAudit = auditList
    .filter((entry) => (filterType === 'ALL' ? true : entry.type === filterType))
    .slice()
    .sort((a, b) => b.t - a.t);

  const handleExportPng = () => {
    exportComponentPng({
      elementId: 'audit-log-card',
      fileName: `MeshHeal_AuditLog_${scenarioId}`,
      scenarioTitle: scenarioId,
      timeSeconds: t,
      isReplay: scenarioId === 'F',
    });
  };

  return (
    <section aria-label="Audit trail" id="audit-log-card" className="card-stage p-6 sm:p-8 flex flex-col">
      {/* Header and Filter */}
      <div className="flex items-center justify-between pb-4 border-b border-border flex-wrap gap-3">
        <div>
          <h2 className="text-base sm:text-lg font-semibold tracking-tight text-text">
            Remediation Decision Audit Trail (FR-3.4)
          </h2>
          <p className="text-xs text-muted font-mono mt-0.5">
            {filteredAudit.length} decisions logged in current scenario timeframe
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Type Filter */}
          <div className="flex items-center gap-2 text-xs">
            <Filter className="w-3.5 h-3.5 text-muted shrink-0" />
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="bg-surface-2 border border-border hover:border-border-strong text-text rounded-pill px-3 py-1.5 text-xs font-mono outline-none focus:ring-2 focus:ring-primary/40 cursor-pointer transition-all shadow-sm"
              aria-label="Filter audit events by type"
            >
              <option value="ALL">All Event Types</option>
              <option value="REROUTE_APPLIED">REROUTE_APPLIED</option>
              <option value="ACTION_BLOCKED">ACTION_BLOCKED</option>
              <option value="FAULT_INJECTED">FAULT_INJECTED</option>
              <option value="THRESHOLD_CROSSED">THRESHOLD_CROSSED</option>
              <option value="FALLBACK_ACTIVATED">FALLBACK_ACTIVATED</option>
              <option value="RECOVERED">RECOVERED</option>
            </select>
          </div>

          {/* Export PNG */}
          <button
            onClick={handleExportPng}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-pill text-xs font-medium border border-border bg-surface-2 hover:bg-surface text-muted hover:text-text transition-all"
            title="Export audit log as 2x PNG"
            aria-label="Export audit log PNG"
          >
            <Camera className="w-3.5 h-3.5" />
            <span>Export PNG</span>
          </button>
        </div>
      </div>

      {/* 5-Column Full-Width Table (Time, Event, Service, Detail, Reason) */}
      <div className="overflow-x-auto mt-4">
        {filteredAudit.length === 0 ? (
          <div className="py-12 flex flex-col items-center justify-center text-muted text-xs text-center font-mono">
            <ShieldAlert className="w-7 h-7 mb-2 opacity-50 text-muted" />
            <span>No events recorded yet (t &lt; {Math.round(t)}s).</span>
            <span className="text-[11px] mt-1 text-muted/70">
              Scrub timeline past t=120s to observe fault injection and remediation decisions.
            </span>
          </div>
        ) : (
          <table className="w-full text-left text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border text-[11px] text-muted uppercase tracking-wider">
                <th className="py-3 px-3 font-semibold w-24">Time</th>
                <th className="py-3 px-3 font-semibold w-36">Event</th>
                <th className="py-3 px-3 font-semibold w-28">Service</th>
                <th className="py-3 px-3 font-semibold">Detail</th>
                <th className="py-3 px-3 font-semibold w-48 text-right">Reason</th>
              </tr>
            </thead>
            <tbody>
              {filteredAudit.map((entry, idx) => {
                const style = TYPE_STYLES[entry.type] || TYPE_STYLES.THRESHOLD_CROSSED;
                const isBlocked = entry.type === 'ACTION_BLOCKED';

                return (
                  <tr
                    key={entry.id || idx}
                    tabIndex={0}
                    role="button"
                    onClick={() => setTime(entry.t)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        setTime(entry.t);
                      }
                    }}
                    className={`border-b border-border/40 hover:bg-surface-2 cursor-pointer transition-all ${
                      isBlocked ? 'bg-amber-500/5' : ''
                    }`}
                    title={`Click to jump scrubber to t=${entry.t}s`}
                  >
                    {/* 1. Time */}
                    <td className="py-3.5 px-3 text-muted whitespace-nowrap">
                      t={entry.t}s
                    </td>

                    {/* 2. Event */}
                    <td className="py-3.5 px-3 whitespace-nowrap">
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-pill text-[10px] font-bold border tracking-wider shadow-sm ${style.bg} ${style.text} ${style.border}`}
                      >
                        {style.label}
                      </span>
                    </td>

                    {/* 3. Service */}
                    <td className="py-3.5 px-3 font-semibold text-text whitespace-nowrap">
                      {entry.node || '-'}
                    </td>

                    {/* 4. Detail */}
                    <td className="py-3.5 px-3 text-text leading-relaxed">
                      {entry.detail}
                    </td>

                    {/* 5. Reason */}
                    <td className="py-3.5 px-3 text-right whitespace-nowrap">
                      {entry.reason ? (
                        <span className="px-2.5 py-0.5 rounded-pill text-[10px] font-bold bg-amber-500/15 border border-amber-500/30 text-warn">
                          {entry.reason}
                        </span>
                      ) : (
                        <span className="text-muted/40">-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
};
