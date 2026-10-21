import React, { useState } from 'react';
import { Camera, Filter, ShieldAlert, CornerDownRight, ScrollText, ArrowRight } from 'lucide-react';
import { useStore } from '../store';
import { AuditEntry, AuditType } from '../data/types';
import { exportComponentPng } from '../utils/exportPng';

const TYPE_STYLES: Record<
  AuditType,
  { bg: string; text: string; border: string; label: string }
> = {
  REROUTE_APPLIED: {
    bg: 'bg-emerald-500/15',
    text: 'text-emerald-300',
    border: 'border-emerald-500/30',
    label: 'REROUTE',
  },
  ACTION_BLOCKED: {
    bg: 'bg-amber-500/15',
    text: 'text-amber-300',
    border: 'border-amber-500/40',
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
    border: 'border-orange-500/40',
    label: 'FALLBACK',
  },
  RECOVERED: {
    bg: 'bg-teal-500/15',
    text: 'text-teal-300',
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
    <div
      id="audit-log-card"
      className="glass-panel rounded-2xl p-5 flex flex-col h-full relative shadow-glass transition-all"
    >
      {/* Header and Filter */}
      <div className="flex items-center justify-between pb-3.5 border-b border-border/70 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
            <ScrollText className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-xs sm:text-sm font-semibold tracking-tight text-text">
              Audit Trail &amp; Remediation Log (FR-3.4)
            </h2>
            <p className="text-[11px] text-muted font-mono">
              Immutable Decision History ({filteredAudit.length} events logged)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Type Filter */}
          <div className="flex items-center gap-1.5 text-xs">
            <Filter className="w-3.5 h-3.5 text-muted shrink-0" />
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="bg-surface-subtle border border-border hover:border-border-strong text-text rounded-xl px-3 py-1.5 text-xs font-mono outline-none focus:ring-2 focus:ring-accent/40 cursor-pointer transition-all shadow-sm"
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
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border border-border bg-surface-subtle hover:bg-surface-elevated text-muted hover:text-text transition-all shadow-sm"
            title="Export audit log as 2x PNG"
            aria-label="Export audit log PNG"
          >
            <Camera className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Export PNG</span>
          </button>
        </div>
      </div>

      {/* Spacious Scrollable Table */}
      <div className="flex-1 overflow-y-auto mt-3 pr-1.5 min-h-[250px]">
        {filteredAudit.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-muted text-xs p-8 text-center">
            <div className="w-12 h-12 rounded-2xl bg-surface-subtle border border-border flex items-center justify-center mb-3">
              <ShieldAlert className="w-6 h-6 text-muted" />
            </div>
            <span className="font-medium text-text text-sm">No audit events logged yet (t &lt; {Math.round(t)}s).</span>
            <span className="text-[11px] mt-1 text-muted font-mono max-w-sm">
              Scrub the timeline forward past t=120s to observe fault injection and autonomous control-loop decisions.
            </span>
          </div>
        ) : (
          <table className="w-full text-left text-xs font-mono border-collapse">
            <thead>
              <tr className="border-b border-border/70 text-[10px] text-muted uppercase tracking-wider">
                <th className="py-2.5 px-3 font-semibold w-20">Time</th>
                <th className="py-2.5 px-3 font-semibold w-28">Type</th>
                <th className="py-2.5 px-3 font-semibold w-24">Node</th>
                <th className="py-2.5 px-3 font-semibold">Event Detail &amp; Safety Reasoning</th>
                <th className="py-2.5 px-3 font-semibold w-14 text-right">Seek</th>
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
                    className={`border-b border-border/30 hover:bg-surface-subtle/80 cursor-pointer transition-all duration-150 ${
                      isBlocked ? 'bg-amber-500/5' : ''
                    }`}
                    title={`Click to seek scrubber to t=${entry.t}s`}
                  >
                    {/* Time */}
                    <td className="py-3 px-3 text-xs text-muted whitespace-nowrap">
                      <span className="px-2 py-0.5 rounded-md bg-surface-subtle border border-border/60">
                        t={entry.t}s
                      </span>
                    </td>

                    {/* Type Chip */}
                    <td className="py-3 px-3 whitespace-nowrap">
                      <span
                        className={`inline-block px-2.5 py-1 rounded-full text-[10px] font-bold border tracking-wider shadow-sm ${style.bg} ${style.text} ${style.border}`}
                      >
                        {style.label}
                      </span>
                    </td>

                    {/* Node */}
                    <td className="py-3 px-3 text-xs font-semibold text-text whitespace-nowrap">
                      {entry.node ? (
                        <span className="px-2 py-0.5 rounded-md bg-surface-elevated border border-border">
                          {entry.node}
                        </span>
                      ) : (
                        '-'
                      )}
                    </td>

                    {/* Detail & Reason */}
                    <td className="py-3 px-3 text-xs text-text leading-relaxed">
                      <div className="flex flex-col gap-1">
                        <span>{entry.detail}</span>
                        {entry.reason && (
                          <div className="flex items-center gap-1.5 text-[11px] text-amber-300 font-semibold bg-amber-500/10 px-2.5 py-1 rounded-lg border border-amber-500/30 w-fit">
                            <CornerDownRight className="w-3.5 h-3.5 text-amber-400" />
                            <span>Guardrail Block Reason: {entry.reason}</span>
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Jump action icon */}
                    <td className="py-3 px-3 text-right">
                      <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-surface-subtle border border-border text-muted hover:text-accent hover:border-accent transition-all">
                        <ArrowRight className="w-3.5 h-3.5" />
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
