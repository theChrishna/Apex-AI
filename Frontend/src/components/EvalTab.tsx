import React from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ErrorBar,
} from 'recharts';
import { Camera, CheckCircle2, MinusCircle, XCircle, Info, Award, Trophy, Scale } from 'lucide-react';
import {
  EVALUATION_DATA,
  EVALUATION_FOOTNOTES,
  EVALUATION_SUMMARY,
} from '../data/evaluation';
import { exportComponentPng } from '../utils/exportPng';
import { useStore } from '../store';

export const EvalTab: React.FC = () => {
  const { t } = useStore();

  const chartData = EVALUATION_DATA.map((d) => ({
    episode: `Fold ${d.episode} (${d.node} +${d.delay_ms}ms)`,
    episodeShort: `Ep ${d.episode}`,
    node: d.node,
    delay_ms: d.delay_ms,
    gnn_ap: d.gnn_ap,
    gnn_ap_error: [d.gnn_ap_std, d.gnn_ap_std],
    bl_ap: d.bl_ap,
    gnn_rc1: d.gnn_rc1,
    bl_rc1: d.bl_rc1,
    winner: d.winner,
  }));

  const handleExportPng = () => {
    exportComponentPng({
      elementId: 'evaluation-tab-card',
      fileName: 'MeshHeal_Evaluation_Benchmark',
      scenarioTitle: 'Evaluation Benchmark (8 Folds)',
      timeSeconds: t,
      isReplay: false,
    });
  };

  return (
    <div
      id="evaluation-tab-card"
      className="glass-panel rounded-2xl p-6 lg:p-8 space-y-6 shadow-glass transition-all"
    >
      {/* Header and Export */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-border/70">
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-indigo-500 via-purple-500 to-cyan-400 p-[1px] shadow-glow-accent">
            <div className="w-full h-full rounded-[15px] bg-surface flex items-center justify-center">
              <Award className="w-5 h-5 text-cyan-300" />
            </div>
          </div>
          <div>
            <h1 className="text-base sm:text-lg font-bold text-text tracking-tight">
              Model Evaluation: Leave-One-Episode-Out Cross Validation
            </h1>
            <p className="text-xs text-muted font-mono mt-0.5">
              8 empirical folds • GNN (5 seeds avg) vs Rule Baseline (&quot;flag if incoming p95 &gt; threshold&quot;)
            </p>
          </div>
        </div>

        <button
          onClick={handleExportPng}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold border border-border bg-surface-subtle hover:bg-surface-elevated text-text transition-all shadow-sm"
          title="Export evaluation report figure as 2x PNG"
          aria-label="Export evaluation report PNG"
        >
          <Camera className="w-4 h-4 text-accent" />
          <span>Export Report Figure (PNG)</span>
        </button>
      </div>

      {/* Win / Tie / Loss Summary Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* GNN Wins */}
        <div className="p-4 rounded-2xl bg-teal-500/10 border border-teal-500/25 flex items-center justify-between">
          <div>
            <div className="text-xs font-mono uppercase tracking-wider text-teal-300/80">GNN Outperformed</div>
            <div className="text-2xl font-bold font-mono text-teal-300 mt-0.5">
              {EVALUATION_SUMMARY.gnnWins} <span className="text-xs font-normal text-teal-400">/ 8 Folds</span>
            </div>
            <p className="text-[11px] text-teal-200/70 mt-1">Superior AP on folds A, 3, 6</p>
          </div>
          <div className="p-3 rounded-xl bg-teal-500/20 text-teal-300">
            <Trophy className="w-6 h-6" />
          </div>
        </div>

        {/* Ties */}
        <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-between">
          <div>
            <div className="text-xs font-mono uppercase tracking-wider text-amber-300/80">Parity / Ties (&le;0.01)</div>
            <div className="text-2xl font-bold font-mono text-amber-300 mt-0.5">
              {EVALUATION_SUMMARY.ties} <span className="text-xs font-normal text-amber-400">/ 8 Folds</span>
            </div>
            <p className="text-[11px] text-amber-200/70 mt-1">Equal performance on folds B, 4, 5</p>
          </div>
          <div className="p-3 rounded-xl bg-amber-500/20 text-amber-300">
            <Scale className="w-6 h-6" />
          </div>
        </div>

        {/* Baseline Wins */}
        <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/25 flex items-center justify-between">
          <div>
            <div className="text-xs font-mono uppercase tracking-wider text-rose-300/80">Baseline Ahead</div>
            <div className="text-2xl font-bold font-mono text-rose-300 mt-0.5">
              {EVALUATION_SUMMARY.baselineWins} <span className="text-xs font-normal text-rose-400">/ 8 Folds</span>
            </div>
            <p className="text-[11px] text-rose-200/70 mt-1">Rule baseline better on folds 1, 2</p>
          </div>
          <div className="p-3 rounded-xl bg-rose-500/20 text-rose-300">
            <XCircle className="w-6 h-6" />
          </div>
        </div>
      </div>

      {/* Two Grouped Bar Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Chart 1: Average Precision (AP) */}
        <div className="p-5 rounded-2xl bg-surface-subtle/50 border border-border/80 flex flex-col shadow-sm">
          <div className="mb-3">
            <h2 className="text-xs sm:text-sm font-semibold text-text uppercase tracking-wider font-mono">
              Average Precision (AP) per Fold
            </h2>
            <p className="text-xs text-muted">
              GNN (5 seeds avg with std error bar) vs Rule Baseline
            </p>
          </div>

          <div className="w-full h-72 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                margin={{ top: 15, right: 10, left: -15, bottom: 25 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.07)" vertical={false} />
                <XAxis
                  dataKey="episodeShort"
                  stroke="rgba(255, 255, 255, 0.12)"
                  tick={{ fill: '#94A3B8', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                  interval={0}
                />
                <YAxis
                  domain={[0, 1.1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1.0]}
                  stroke="rgba(255, 255, 255, 0.12)"
                  tick={{ fill: '#94A3B8', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(13, 19, 34, 0.95)',
                    backdropFilter: 'blur(12px)',
                    borderColor: 'rgba(255, 255, 255, 0.12)',
                    borderRadius: '12px',
                    color: '#F8FAFC',
                    fontFamily: 'JetBrains Mono',
                    fontSize: '11px',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  }}
                  formatter={(val: any) => [Number(val).toFixed(3), '']}
                  labelFormatter={(idx, items) => {
                    if (items && items.length > 0) {
                      return items[0].payload.episode;
                    }
                    return String(idx);
                  }}
                />
                <Legend
                  wrapperStyle={{
                    fontSize: '11px',
                    fontFamily: 'JetBrains Mono',
                    paddingTop: '8px',
                  }}
                />
                <Bar
                  dataKey="gnn_ap"
                  name="GNN AP (avg)"
                  fill="#6366F1"
                  radius={[4, 4, 0, 0]}
                >
                  <ErrorBar
                    dataKey="gnn_ap_error"
                    width={4}
                    strokeWidth={1.5}
                    stroke="#F8FAFC"
                  />
                </Bar>
                <Bar
                  dataKey="bl_ap"
                  name="Rule Baseline AP"
                  fill="#F59E0B"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: Root-Cause Identification Top-1 (RC@1) */}
        <div className="p-5 rounded-2xl bg-surface-subtle/50 border border-border/80 flex flex-col shadow-sm">
          <div className="mb-3">
            <h2 className="text-xs sm:text-sm font-semibold text-text uppercase tracking-wider font-mono">
              Root-Cause Identification (RC@1) per Fold
            </h2>
            <p className="text-xs text-muted">
              Probability that top-ranked node matches injected culprit
            </p>
          </div>

          <div className="w-full h-72 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                margin={{ top: 15, right: 10, left: -15, bottom: 25 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.07)" vertical={false} />
                <XAxis
                  dataKey="episodeShort"
                  stroke="rgba(255, 255, 255, 0.12)"
                  tick={{ fill: '#94A3B8', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                  interval={0}
                />
                <YAxis
                  domain={[0, 1.1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1.0]}
                  stroke="rgba(255, 255, 255, 0.12)"
                  tick={{ fill: '#94A3B8', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(13, 19, 34, 0.95)',
                    backdropFilter: 'blur(12px)',
                    borderColor: 'rgba(255, 255, 255, 0.12)',
                    borderRadius: '12px',
                    color: '#F8FAFC',
                    fontFamily: 'JetBrains Mono',
                    fontSize: '11px',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  }}
                  formatter={(val: any) => [Number(val).toFixed(3), '']}
                  labelFormatter={(idx, items) => {
                    if (items && items.length > 0) {
                      return items[0].payload.episode;
                    }
                    return String(idx);
                  }}
                />
                <Legend
                  wrapperStyle={{
                    fontSize: '11px',
                    fontFamily: 'JetBrains Mono',
                    paddingTop: '8px',
                  }}
                />
                <Bar
                  dataKey="gnn_rc1"
                  name="GNN RC@1"
                  fill="#14B8A6"
                  radius={[4, 4, 0, 0]}
                />
                <Bar
                  dataKey="bl_rc1"
                  name="Rule Baseline RC@1"
                  fill="#F59E0B"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Complete Empirical Data Table */}
      <div className="overflow-x-auto border border-border rounded-2xl">
        <table className="w-full text-left text-xs font-mono border-collapse">
          <thead>
            <tr className="bg-surface-subtle text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="py-3 px-4 font-semibold">Fold / Ep</th>
              <th className="py-3 px-4 font-semibold">Fault Node</th>
              <th className="py-3 px-4 font-semibold">Delay (ms)</th>
              <th className="py-3 px-4 font-semibold">GNN AP (avg &plusmn; std)</th>
              <th className="py-3 px-4 font-semibold">Baseline AP</th>
              <th className="py-3 px-4 font-semibold">GNN RC@1</th>
              <th className="py-3 px-4 font-semibold">Baseline RC@1</th>
              <th className="py-3 px-4 font-semibold text-right">Fold Result</th>
            </tr>
          </thead>
          <tbody>
            {EVALUATION_DATA.map((row) => (
              <tr
                key={row.episode}
                className="border-b border-border/40 hover:bg-surface-subtle/60 transition-colors"
              >
                <td className="py-3.5 px-4 font-bold text-accent">Episode {row.episode}</td>
                <td className="py-3.5 px-4 font-semibold text-text">
                  <span className="px-2 py-0.5 rounded-md bg-surface-subtle border border-border">
                    {row.node}
                  </span>
                </td>
                <td className="py-3.5 px-4 text-text">+{row.delay_ms} ms</td>
                <td className="py-3.5 px-4 text-text">
                  <strong className="text-white">{row.gnn_ap.toFixed(3)}</strong>{' '}
                  <span className="text-muted text-[11px]">
                    (&plusmn;{row.gnn_ap_std.toFixed(3)})
                  </span>
                </td>
                <td className="py-3.5 px-4 text-text">{row.bl_ap.toFixed(3)}</td>
                <td className="py-3.5 px-4 text-text">{row.gnn_rc1.toFixed(3)}</td>
                <td className="py-3.5 px-4 text-text">{row.bl_rc1.toFixed(3)}</td>
                <td className="py-3.5 px-4 text-right">
                  <span
                    className={`inline-block px-2.5 py-1 rounded-full text-[10px] font-bold tracking-wider ${
                      row.winner === 'gnn'
                        ? 'bg-teal-500/20 text-teal-300 border border-teal-500/40'
                        : row.winner === 'tie'
                        ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                        : 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                    }`}
                  >
                    {row.winner.toUpperCase()}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mandatory Footnotes */}
      <div className="p-4 rounded-2xl bg-surface-subtle/70 border border-border space-y-2 text-xs">
        <div className="flex items-center gap-2 font-semibold text-text mb-1">
          <Info className="w-4 h-4 text-accent" />
          <span>Evaluation Notes &amp; Methodological Disclaimers</span>
        </div>
        <ul className="list-disc list-inside space-y-1.5 text-muted text-xs leading-relaxed">
          {EVALUATION_FOOTNOTES.map((note, idx) => (
            <li key={idx}>{note}</li>
          ))}
        </ul>
      </div>
    </div>
  );
};
