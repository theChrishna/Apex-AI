import React, { useMemo, useState } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ReferenceArea,
} from 'recharts';
import { Camera, TrendingUp } from 'lucide-react';
import { useStore } from '../store';
import { computeSimulationState } from '../data/simulatedDataSource';
import { SCENARIOS } from '../data/scenarios';
import { exportComponentPng } from '../utils/exportPng';
import { ReplayAdapter } from '../data/replayAdapter';

export const RiskTimeline: React.FC = () => {
  const {
    scenarioId,
    t,
    setTime,
    policy,
    replayEpisodes,
    selectedReplayEpisode,
  } = useStore();

  const [viewMode, setViewMode] = useState<'risk' | 'latency'>('risk');

  const currentScenario = SCENARIOS.find((s) => s.id === scenarioId);
  const faultWindow = currentScenario?.faultWindow;

  // Pre-generate full 600s timeline samples (every 15s = 41 points)
  const timelineData = useMemo(() => {
    const points = [];
    const isReplay = scenarioId === 'F' && replayEpisodes && selectedReplayEpisode;
    const epMeta = isReplay ? replayEpisodes.get(selectedReplayEpisode) : null;

    for (let timeSec = 0; timeSec <= 600; timeSec += 15) {
      if (epMeta) {
        const state = ReplayAdapter.computeReplayState(epMeta, timeSec);
        const p_det = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'details');
        const p_rev = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'reviews');
        const r_rat = state.snapshot.edges.find((e) => e.source === 'reviews' && e.destination === 'ratings');
        points.push({
          t: timeSec,
          ratings: state.risk.risk.ratings,
          reviews: state.risk.risk.reviews,
          details: state.risk.risk.details,
          productpage: state.risk.risk.productpage,
          lat_p_det: p_det ? p_det.latency_p95 : 8.5,
          lat_p_rev: p_rev ? p_rev.latency_p95 : 42.0,
          lat_r_rat: r_rat ? r_rat.latency_p95 : 10.2,
        });
      } else {
        const state = computeSimulationState(scenarioId, timeSec, policy);
        const p_det = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'details');
        const p_rev = state.snapshot.edges.find((e) => e.source === 'productpage' && e.destination === 'reviews');
        const r_rat = state.snapshot.edges.find((e) => e.source === 'reviews' && e.destination === 'ratings');
        points.push({
          t: timeSec,
          ratings: state.risk.risk.ratings,
          reviews: state.risk.risk.reviews,
          details: state.risk.risk.details,
          productpage: state.risk.risk.productpage,
          lat_p_det: p_det ? p_det.latency_p95 : 8.5,
          lat_p_rev: p_rev ? p_rev.latency_p95 : 42.0,
          lat_r_rat: r_rat ? r_rat.latency_p95 : 10.2,
        });
      }
    }
    return points;
  }, [scenarioId, policy, replayEpisodes, selectedReplayEpisode]);

  const auditEvents = useStore((s) => s.simulationState.audit);

  const handleExportPng = () => {
    exportComponentPng({
      elementId: 'risk-timeline-card',
      fileName: `MeshHeal_${viewMode === 'risk' ? 'Risk' : 'Latency'}_Timeline_${scenarioId}`,
      scenarioTitle: scenarioId,
      timeSeconds: t,
      isReplay: scenarioId === 'F',
    });
  };

  return (
    <section aria-label="Timeline charts" id="risk-timeline-card" className="card-stage p-6 sm:p-8 flex flex-col">
      {/* Header and Controls */}
      <div className="flex items-center justify-between pb-4 border-b border-border flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-primary">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold tracking-tight text-text">
              {viewMode === 'risk' ? 'Risk Score Over Time' : 'Edge Latency Over Time (Log Scale)'}
            </h2>
            <p className="text-xs text-muted font-mono">
              {viewMode === 'risk' ? 'Act (0.85) and Release (0.60) Policy Thresholds' : 'p95 latency (ms) per service edge'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Toggle pill */}
          <div className="flex bg-surface-2 p-1 rounded-pill border border-border text-xs font-mono">
            <button
              onClick={() => setViewMode('risk')}
              className={`px-3 py-1 rounded-pill transition-all ${
                viewMode === 'risk' ? 'bg-primary text-white font-semibold shadow-sm' : 'text-muted hover:text-text'
              }`}
            >
              Risk view
            </button>
            <button
              onClick={() => setViewMode('latency')}
              className={`px-3 py-1 rounded-pill transition-all ${
                viewMode === 'latency' ? 'bg-primary text-white font-semibold shadow-sm' : 'text-muted hover:text-text'
              }`}
            >
              Latency view
            </button>
          </div>

          <button
            onClick={handleExportPng}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-pill text-xs font-medium border border-border bg-surface-2 hover:bg-surface text-muted hover:text-text transition-all"
            title="Export timeline chart as 2x PNG"
            aria-label="Export timeline chart PNG"
          >
            <Camera className="w-3.5 h-3.5" />
            <span>Export PNG</span>
          </button>
        </div>
      </div>

      {/* Chart */}
      <div className="w-full h-80 pt-5">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={timelineData}
            margin={{ top: 15, right: 25, left: -10, bottom: 0 }}
            onClick={(e) => {
              if (e && e.activePayload && e.activePayload.length > 0) {
                const clickedT = e.activePayload[0].payload.t;
                if (typeof clickedT === 'number') setTime(clickedT);
              }
            }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.06)" vertical={false} />

            <XAxis
              dataKey="t"
              domain={[0, 600]}
              tick={{ fill: '#A99BC9', fontSize: 11, fontFamily: 'JetBrains Mono' }}
              tickFormatter={(v) => `${v}s`}
              stroke="rgba(255, 255, 255, 0.1)"
            />

            {viewMode === 'risk' ? (
              <YAxis
                domain={[0, 1.05]}
                ticks={[0, 0.25, 0.5, 0.60, 0.75, 0.85, 1.0]}
                tick={{ fill: '#A99BC9', fontSize: 11, fontFamily: 'JetBrains Mono' }}
                stroke="rgba(255, 255, 255, 0.1)"
              />
            ) : (
              <YAxis
                scale="log"
                domain={[5, 400]}
                ticks={[5, 10, 25, 50, 100, 200, 300]}
                tick={{ fill: '#A99BC9', fontSize: 11, fontFamily: 'JetBrains Mono' }}
                stroke="rgba(255, 255, 255, 0.1)"
              />
            )}

            {/* Shaded Fault Window */}
            {faultWindow && (
              <ReferenceArea
                x1={faultWindow.start}
                x2={faultWindow.end}
                y1={0}
                y2={viewMode === 'risk' ? 1.05 : 400}
                fill="#FF5C7C"
                fillOpacity={0.08}
                stroke="#FF5C7C"
                strokeOpacity={0.25}
                strokeDasharray="4 4"
              />
            )}

            {/* Threshold Lines */}
            {viewMode === 'risk' && (
              <>
                {/* 0.60 Release Line */}
                <ReferenceLine
                  y={policy.releaseThreshold}
                  stroke="#FFB347"
                  strokeDasharray="3 3"
                  strokeWidth={1.5}
                  label={{
                    value: 'Release < 0.60',
                    fill: '#FFB347',
                    fontSize: 10,
                    position: 'insideTopLeft',
                    fontFamily: 'JetBrains Mono',
                  }}
                />

                {/* 0.85 Act Line */}
                <ReferenceLine
                  y={policy.actThreshold}
                  stroke="#FF5C7C"
                  strokeDasharray="4 4"
                  strokeWidth={1.5}
                  label={{
                    value: 'Act > 0.85',
                    fill: '#FF5C7C',
                    fontSize: 10,
                    position: 'insideTopRight',
                    fontFamily: 'JetBrains Mono',
                  }}
                />
              </>
            )}

            {/* Current scrubber position */}
            <ReferenceLine
              x={t}
              stroke="#6D4AFF"
              strokeWidth={2}
              label={{
                value: `t=${Math.round(t)}s`,
                fill: '#F4F0FF',
                fontSize: 10,
                position: 'top',
                fontFamily: 'JetBrains Mono',
              }}
            />

            {/* Audit event pins */}
            {auditEvents.map((evt, idx) => (
              <ReferenceLine
                key={idx}
                x={evt.t}
                stroke={evt.type === 'ACTION_BLOCKED' ? '#FFB347' : '#34D6B0'}
                strokeDasharray="2 2"
                strokeWidth={1}
              />
            ))}

            <Tooltip
              contentStyle={{
                backgroundColor: 'rgba(29, 20, 56, 0.95)',
                backdropFilter: 'blur(16px)',
                borderColor: 'rgba(255, 255, 255, 0.12)',
                borderRadius: '16px',
                color: '#F4F0FF',
                fontFamily: 'JetBrains Mono',
                fontSize: '11px',
                boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                padding: '12px 16px',
              }}
              formatter={(value: any, name: any) => [
                viewMode === 'risk' ? Number(value).toFixed(2) : `${value} ms`,
                name,
              ]}
              labelFormatter={(label) => `Time: ${label}s`}
            />

            <Legend
              wrapperStyle={{
                fontSize: '11px',
                fontFamily: 'JetBrains Mono',
                paddingTop: '12px',
              }}
            />

            {/* Lines */}
            {viewMode === 'risk' ? (
              <>
                <Line
                  type="monotone"
                  dataKey="ratings"
                  name="ratings"
                  stroke="#FF5C7C"
                  strokeWidth={2.4}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="reviews"
                  name="reviews"
                  stroke="#FFB347"
                  strokeWidth={2.2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="details"
                  name="details"
                  stroke="#34D6B0"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="productpage"
                  name="productpage"
                  stroke="#6D4AFF"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </>
            ) : (
              <>
                <Line
                  type="stepAfter"
                  dataKey="lat_r_rat"
                  name="reviews -> ratings (p95)"
                  stroke="#FF5C7C"
                  strokeWidth={2.2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="stepAfter"
                  dataKey="lat_p_rev"
                  name="productpage -> reviews (p95)"
                  stroke="#FFB347"
                  strokeWidth={2.2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="stepAfter"
                  dataKey="lat_p_det"
                  name="productpage -> details (p95)"
                  stroke="#34D6B0"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </>
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
};
