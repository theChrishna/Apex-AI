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
import { Camera, Trophy, Scale, XCircle, Info, Award } from 'lucide-react';
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
      className="card-stage p-6 sm:p-10 space-y-8"
    >
      {/* Header and Export */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-6 border-b border-border">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-text tracking-tight">
            Leave-One-Episode-Out Cross-Validation Benchmark
          </h1>
          <p className="text-xs text-muted font-mono mt-1">
            8 empirical folds • GNN (5 seeds avg) vs Rule Baseline (&quot;flag if incoming p95 &gt; threshold&quot;)
          </p>
        </div>

        <button
          onClick={handleExportPng}
          className="flex items-center gap-2 px-4 py-2 rounded-pill text-xs font-semibold border border-border bg-surface-2 hover:bg-surface text-text transition-all"
          title="Export evaluation report figure as 2x PNG"
          aria-label="Export evaluation report PNG"
        >
          <Camera className="w-4 h-4 text-primary" />
          <span>Export PNG (2x)</span>
        </button>
      </div>

      {/* Three Headline Tiles */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Tile 1: GNN Better */}
        <div className="p-5 rounded-tile bg-surface-2 border border-border flex items-center justify-between">
          <div>
            <div className="text-xs font-mono uppercase tracking-wider text-ok">GNN Better</div>
            <div className="text-3xl font-bold font-mono text-text mt-1">
              3 <span className="text-sm font-normal text-muted">folds</span>
            </div>
            <p className="text-xs text-muted mt-1">Episodes A, 3, 6</p>
          </div>
          <div className="p-3 rounded-full bg-teal-500/15 text-ok">
            <Trophy className="w-6 h-6" />
          </div>
        </div>

        {/* Tile 2: Tied */}
        <div className="p-5 rounded-tile bg-surface-2 border border-border flex items-center justify-between">
          <div>
            <div className="text-xs font-mono uppercase tracking-wider text-warn">Tied (&le; 0.01)</div>
            <div className="text-3xl font-bold font-mono text-text mt-1">
              3 <span className="text-sm font-normal text-muted">folds</span>
            </div>
            <p className="text-xs text-muted mt-1">Episodes B, 4, 5</p>
          </div>
          <div className="p-3 rounded-full bg-amber-500/15 text-warn">
            <Scale className="w-6 h-6" />
          </div>
        </div>

        {/* Tile 3: Worse */}
        <div className="p-5 rounded-tile bg-surface-2 border border-border flex items-center justify-between">
          <div>
            <div className="text-xs font-mono uppercase tracking-wider text-critical">Worse</div>
            <div className="text-3xl font-bold font-mono text-text mt-1">
              2 <span className="text-sm font-normal text-muted">folds</span>
            </div>
            <p className="text-xs text-muted mt-1">Episodes 1, 2</p>
          </div>
          <div className="p-3 rounded-full bg-rose-500/15 text-critical">
            <XCircle className="w-6 h-6" />
          </div>
        </div>
      </div>

      {/* AP and Root-Cause Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Chart 1: Average Precision */}
        <div className="p-6 rounded-tile bg-surface-2 border border-border flex flex-col">
          <div className="mb-4">
            <h2 className="text-sm font-semibold text-text uppercase tracking-wider font-mono">
              Average Precision (AP) per Fold
            </h2>
            <p className="text-xs text-muted">
              GNN (5 seeds avg with std error bar) vs Rule Baseline
            </p>
          </div>

          <div className="w-full h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 15, right: 10, left: -15, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.06)" vertical={false} />
                <XAxis
                  dataKey="episodeShort"
                  stroke="rgba(255, 255, 255, 0.1)"
                  tick={{ fill: '#A99BC9', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                  interval={0}
                />
                <YAxis
                  domain={[0, 1.1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1.0]}
                  stroke="rgba(255, 255, 255, 0.1)"
                  tick={{ fill: '#A99BC9', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(29, 20, 56, 0.95)',
                    backdropFilter: 'blur(16px)',
                    borderColor: 'rgba(255, 255, 255, 0.12)',
                    borderRadius: '12px',
                    color: '#F4F0FF',
                    fontFamily: 'JetBrains Mono',
                    fontSize: '11px',
                  }}
                  formatter={(val: any) => [Number(val).toFixed(3), '']}
                  labelFormatter={(idx, items) => items?.[0]?.payload?.episode || String(idx)}
                />
                <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'JetBrains Mono', paddingTop: '8px' }} />
                <Bar dataKey="gnn_ap" name="GNN AP (avg)" fill="#6D4AFF" radius={[4, 4, 0, 0]}>
                  <ErrorBar dataKey="gnn_ap_error" width={4} strokeWidth={1.5} stroke="#F4F0FF" />
                </Bar>
                <Bar dataKey="bl_ap" name="Rule Baseline AP" fill="#FFB347" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Chart 2: Root-Cause Identification Top-1 */}
        <div className="p-6 rounded-tile bg-surface-2 border border-border flex flex-col">
          <div className="mb-4">
            <h2 className="text-sm font-semibold text-text uppercase tracking-wider font-mono">
              Root-Cause Identification (RC@1) per Fold
            </h2>
            <p className="text-xs text-muted">
              Probability that top-ranked node matches injected culprit
            </p>
          </div>

          <div className="w-full h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 15, right: 10, left: -15, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.06)" vertical={false} />
                <XAxis
                  dataKey="episodeShort"
                  stroke="rgba(255, 255, 255, 0.1)"
                  tick={{ fill: '#A99BC9', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                  interval={0}
                />
                <YAxis
                  domain={[0, 1.1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1.0]}
                  stroke="rgba(255, 255, 255, 0.1)"
                  tick={{ fill: '#A99BC9', fontSize: 10, fontFamily: 'JetBrains Mono' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(29, 20, 56, 0.95)',
                    backdropFilter: 'blur(16px)',
                    borderColor: 'rgba(255, 255, 255, 0.12)',
                    borderRadius: '12px',
                    color: '#F4F0FF',
                    fontFamily: 'JetBrains Mono',
                    fontSize: '11px',
                  }}
                  formatter={(val: any) => [Number(val).toFixed(3), '']}
                  labelFormatter={(idx, items) => items?.[0]?.payload?.episode || String(idx)}
                />
                <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'JetBrains Mono', paddingTop: '8px' }} />
                <Bar dataKey="gnn_rc1" name="GNN RC@1" fill="#34D6B0" radius={[4, 4, 0, 0]} />
                <Bar dataKey="bl_rc1" name="Rule Baseline RC@1" fill="#FFB347" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Mandatory Footnotes Visible in Full Below Charts */}
      <div className="p-5 rounded-tile bg-surface-2 border border-border space-y-2 text-xs">
        <div className="flex items-center gap-2 font-semibold text-text mb-1">
          <Info className="w-4 h-4 text-primary" />
          <span>Evaluation Footnotes &amp; Disclaimers</span>
        </div>
        <ul className="list-disc list-inside space-y-1.5 text-muted text-xs leading-relaxed font-mono">
          {EVALUATION_FOOTNOTES.map((note, idx) => (
            <li key={idx}>{note}</li>
          ))}
        </ul>
      </div>

      {/* Complete Data Table */}
      <div className="overflow-x-auto border border-border rounded-tile">
        <table className="w-full text-left text-xs font-mono border-collapse">
          <thead>
            <tr className="bg-surface-2 text-muted text-[11px] uppercase tracking-wider border-b border-border">
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
              <tr key={row.episode} className="border-b border-border/40 hover:bg-surface-2 transition-colors">
                <td className="py-3.5 px-4 font-bold text-text">Episode {row.episode}</td>
                <td className="py-3.5 px-4 font-semibold text-muted">{row.node}</td>
                <td className="py-3.5 px-4 text-text">+{row.delay_ms} ms</td>
                <td className="py-3.5 px-4 text-text">
                  <strong>{row.gnn_ap.toFixed(3)}</strong>{' '}
                  <span className="text-muted text-[11px]">(&plusmn;{row.gnn_ap_std.toFixed(3)})</span>
                </td>
                <td className="py-3.5 px-4 text-text">{row.bl_ap.toFixed(3)}</td>
                <td className="py-3.5 px-4 text-text">{row.gnn_rc1.toFixed(3)}</td>
                <td className="py-3.5 px-4 text-text">{row.bl_rc1.toFixed(3)}</td>
                <td className="py-3.5 px-4 text-right">
                  <span
                    className={`inline-block px-2.5 py-0.5 rounded-pill text-[10px] font-bold tracking-wider ${
                      row.winner === 'gnn'
                        ? 'bg-teal-500/15 text-ok border border-teal-500/30'
                        : row.winner === 'tie'
                        ? 'bg-amber-500/15 text-warn border border-amber-500/30'
                        : 'bg-rose-500/15 text-critical border border-rose-500/30'
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
    </div>
  );
};
