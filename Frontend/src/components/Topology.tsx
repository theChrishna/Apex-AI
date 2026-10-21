import React, { useEffect, useRef, useState } from 'react';
import cytoscape, { Core } from 'cytoscape';
import { Camera, Info, ShieldCheck, Zap, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';
import { useStore } from '../store';
import { NodeId } from '../data/types';
import { exportComponentPng } from '../utils/exportPng';

// Color blind safe palette
const COLOR_OK = '#14B8A6';       // Crisp Teal
const COLOR_WARN = '#F59E0B';     // Warm Amber
const COLOR_CRIT = '#F43F5E';     // Vermillion / Coral Red
const COLOR_REROUTE = '#10B981';  // Vivid Emerald Green
const COLOR_MUTED = '#94A3B8';

function getRiskColor(risk: number): string {
  if (risk >= 0.75) return COLOR_CRIT;
  if (risk >= 0.40) return COLOR_WARN;
  return COLOR_OK;
}

function getRiskSymbol(risk: number, isCulprit: boolean): string {
  if (isCulprit) return '⚡ CULPRIT';
  if (risk >= 0.75) return '✖ CRIT';
  if (risk >= 0.40) return '▲ WARN';
  return '● OK';
}

function getLatencyColor(p95: number): string {
  if (p95 > 80) return COLOR_CRIT;
  if (p95 > 25) return COLOR_WARN;
  return COLOR_OK;
}

export const Topology: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const dashOffsetRef = useRef<number>(0);

  const {
    simulationState,
    selectedNode,
    setSelectedNode,
    selectedEdge,
    setSelectedEdge,
    scenarioId,
    t,
    isPlaying,
  } = useStore();

  const [clickedEdgeData, setClickedEdgeData] = useState<{
    source: string;
    target: string;
    rate: number;
    latency: number;
    error: number;
  } | null>(null);

  const { snapshot, risk, activeReroute } = simulationState;

  // Determine culprit vs victim
  const sortedRisks = Object.entries(risk.risk).sort((a, b) => b[1] - a[1]);
  const highestRiskNode = sortedRisks[0][0] as NodeId;
  const isHighRisk = sortedRisks[0][1] >= 0.75;
  const culpritNode: NodeId | null = isHighRisk ? highestRiskNode : null;

  // Initialize Cytoscape once
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      boxSelectionEnabled: false,
      autounselectify: false,
      userZoomingEnabled: true,
      userPanningEnabled: true,
      style: [
        // Region Compound Swimlanes
        {
          selector: 'node[type = "region"]',
          style: {
            'background-color': '#0B1120',
            'background-opacity': 0.85,
            'border-width': 1.5,
            'border-color': 'rgba(255, 255, 255, 0.1)',
            'border-style': 'solid',
            'shape': 'round-rectangle',
            'label': 'data(label)',
            'color': '#94A3B8',
            'font-family': 'Inter, sans-serif',
            'font-size': 11,
            'font-weight': 600,
            'text-valign': 'top',
            'text-halign': 'center',
            'text-margin-y': 14,
            'padding': '26px',
          } as any,
        },
        {
          selector: 'node[type = "empty-region"]',
          style: {
            'background-color': '#080D18',
            'background-opacity': 0.5,
            'border-width': 1.2,
            'border-color': 'rgba(255, 255, 255, 0.08)',
            'border-style': 'dashed',
            'shape': 'round-rectangle',
            'label': 'data(label)',
            'color': '#64748B',
            'font-family': 'Inter, sans-serif',
            'font-size': 11,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
            'width': 180,
            'height': 110,
          } as any,
        },
        // Service Nodes
        {
          selector: 'node[type = "service"]',
          style: {
            'width': 82,
            'height': 82,
            'shape': 'round-rectangle',
            'background-color': '#111827',
            'border-width': 2.5,
            'border-color': 'data(borderColor)',
            'label': 'data(displayLabel)',
            'color': '#F8FAFC',
            'font-family': 'JetBrains Mono, monospace',
            'font-size': 10,
            'font-weight': 500,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
            'text-max-width': '78px',
            'transition-property': 'background-color, border-color, border-width',
            'transition-duration': 0.25,
          } as any,
        },
        // Ghost/Standby node for reviews-v1 when rerouted
        {
          selector: 'node[type = "reroute-service"]',
          style: {
            'width': 82,
            'height': 82,
            'shape': 'round-rectangle',
            'background-color': '#064E3B',
            'background-opacity': 0.45,
            'border-width': 2,
            'border-color': COLOR_REROUTE,
            'border-style': 'dashed',
            'label': 'data(displayLabel)',
            'color': '#A7F3D0',
            'font-family': 'JetBrains Mono, monospace',
            'font-size': 9,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
          } as any,
        },
        // Culprit pulsing node
        {
          selector: '.is-culprit',
          style: {
            'border-width': 5,
            'border-color': COLOR_CRIT,
          } as any,
        },
        // Selected node
        {
          selector: '.is-selected',
          style: {
            'border-width': 4.5,
            'border-color': '#818CF8',
          } as any,
        },
        // Telemetry Edges
        {
          selector: 'edge[type = "telemetry"]',
          style: {
            'width': 'data(edgeWidth)',
            'line-color': 'data(edgeColor)',
            'target-arrow-color': 'data(edgeColor)',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'line-style': 'dashed',
            'line-dash-pattern': [7, 5],
            'label': 'data(edgeLabel)',
            'color': '#E2E8F0',
            'font-family': 'JetBrains Mono, monospace',
            'font-size': 9,
            'text-rotation': 'autorotate',
            'text-margin-y': -9,
            'text-background-color': '#070B14',
            'text-background-opacity': 0.9,
            'text-background-padding': '3px',
            'text-background-shape': 'roundrectangle',
          } as any,
        },
        // Reroute overlay edge
        {
          selector: 'edge[type = "reroute"]',
          style: {
            'width': 4,
            'line-color': COLOR_REROUTE,
            'target-arrow-color': COLOR_REROUTE,
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'line-style': 'dashed',
            'line-dash-pattern': [8, 4],
            'label': 'data(edgeLabel)',
            'color': '#34D399',
            'font-family': 'JetBrains Mono, monospace',
            'font-size': 9,
            'font-weight': 600,
            'text-rotation': 'autorotate',
            'text-margin-y': -10,
            'text-background-color': '#064E3B',
            'text-background-opacity': 0.95,
            'text-background-padding': '4px',
            'text-background-shape': 'roundrectangle',
          } as any,
        },
      ],
      elements: [
        // Region compound nodes (swimlanes)
        {
          data: {
            id: 'region-aws',
            type: 'region',
            label: 'AWS US-EAST (Workloads Active)',
          },
        },
        {
          data: {
            id: 'region-gcp',
            type: 'empty-region',
            label: 'GCP ASIA\n(namespace only, no workloads)',
          },
          position: { x: 620, y: 120 },
        },
        {
          data: {
            id: 'region-azure',
            type: 'empty-region',
            label: 'AZURE EU\n(namespace only, no workloads)',
          },
          position: { x: 620, y: 290 },
        },
        // Services inside AWS US-EAST (Spacious positions)
        {
          data: {
            id: 'productpage',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'productpage\n● OK 0.08',
            borderColor: COLOR_OK,
          },
          position: { x: 100, y: 205 },
        },
        {
          data: {
            id: 'details',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'details\n● OK 0.07',
            borderColor: COLOR_OK,
          },
          position: { x: 260, y: 110 },
        },
        {
          data: {
            id: 'reviews',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'reviews\n● OK 0.11',
            borderColor: COLOR_OK,
          },
          position: { x: 260, y: 300 },
        },
        {
          data: {
            id: 'ratings',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'ratings\n● OK 0.08',
            borderColor: COLOR_OK,
          },
          position: { x: 430, y: 300 },
        },
        // Standby reviews-v1 target
        {
          data: {
            id: 'reviews-v1',
            parent: 'region-aws',
            type: 'reroute-service',
            displayLabel: 'reviews-v1\n(bypass-path)',
          },
          position: { x: 430, y: 165 },
        },
        // Directed Edges
        {
          data: {
            id: 'edge-p-d',
            source: 'productpage',
            target: 'details',
            type: 'telemetry',
            edgeWidth: 3,
            edgeColor: COLOR_OK,
            edgeLabel: '8.5ms • 0.35 r/s',
          },
        },
        {
          data: {
            id: 'edge-p-r',
            source: 'productpage',
            target: 'reviews',
            type: 'telemetry',
            edgeWidth: 3.5,
            edgeColor: COLOR_OK,
            edgeLabel: '42ms • 0.42 r/s',
          },
        },
        {
          data: {
            id: 'edge-r-r',
            source: 'reviews',
            target: 'ratings',
            type: 'telemetry',
            edgeWidth: 3.2,
            edgeColor: COLOR_OK,
            edgeLabel: '10ms • 0.38 r/s',
          },
        },
        // Reroute overlay edge (hidden by default)
        {
          data: {
            id: 'edge-reroute-overlay',
            source: 'productpage',
            target: 'reviews-v1',
            type: 'reroute',
            edgeLabel: 'shifted to reviews-v1',
          },
        },
      ],
      layout: {
        name: 'preset',
      },
    });

    cy.fit(undefined, 35);

    // Event listeners
    cy.on('tap', 'node[type = "service"]', (evt) => {
      const node = evt.target;
      setSelectedNode(node.id() as NodeId);
    });

    cy.on('tap', 'edge[type = "telemetry"]', (evt) => {
      const edge = evt.target;
      const s = edge.source().id() as NodeId;
      const d = edge.target().id() as NodeId;
      setSelectedEdge({ source: s, destination: d });
      const snap = useStore.getState().simulationState.snapshot;
      const found = snap.edges.find((e) => e.source === s && e.destination === d);
      if (found) {
        setClickedEdgeData({
          source: s,
          target: d,
          rate: found.request_rate,
          latency: found.latency_p95,
          error: found.error_rate,
        });
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [setSelectedNode, setSelectedEdge]);

  // Update Cytoscape elements when simulationState changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const effectiveSelected = selectedNode || culpritNode || 'productpage';

    // Update Nodes
    const serviceNodes: NodeId[] = ['productpage', 'details', 'reviews', 'ratings'];
    serviceNodes.forEach((nodeId) => {
      const nodeElem = cy.$(`#${nodeId}`);
      if (!nodeElem.length) return;

      const r = risk.risk[nodeId] ?? 0.08;
      const isCulprit = culpritNode === nodeId;
      const color = getRiskColor(r);
      const symbol = getRiskSymbol(r, isCulprit);

      nodeElem.data('borderColor', color);
      nodeElem.data('displayLabel', `${nodeId}\n${symbol} ${r.toFixed(2)}`);

      if (isCulprit) {
        nodeElem.addClass('is-culprit');
      } else {
        nodeElem.removeClass('is-culprit');
      }

      if (effectiveSelected === nodeId) {
        nodeElem.addClass('is-selected');
      } else {
        nodeElem.removeClass('is-selected');
      }
    });

    // Update reviews-v1 visibility
    const reviewsV1Elem = cy.$('#reviews-v1');
    const rerouteEdgeElem = cy.$('#edge-reroute-overlay');
    if (activeReroute) {
      reviewsV1Elem.style('display', 'element');
      rerouteEdgeElem.style('display', 'element');
    } else {
      reviewsV1Elem.style('display', 'none');
      rerouteEdgeElem.style('display', 'none');
    }

    // Update Edges
    snapshot.edges.forEach((edge) => {
      let edgeId = '';
      if (edge.source === 'productpage' && edge.destination === 'details') edgeId = 'edge-p-d';
      if (edge.source === 'productpage' && edge.destination === 'reviews') edgeId = 'edge-p-r';
      if (edge.source === 'reviews' && edge.destination === 'ratings') edgeId = 'edge-r-r';

      const edgeElem = cy.$(`#${edgeId}`);
      if (!edgeElem.length) return;

      const edgeWidth = Math.max(2, Math.min(6.5, edge.request_rate * 9.5));
      const edgeColor = getLatencyColor(edge.latency_p95);
      const label = `${edge.latency_p95}ms • ${edge.request_rate}r/s`;

      edgeElem.data('edgeWidth', edgeWidth);
      edgeElem.data('edgeColor', edgeColor);
      edgeElem.data('edgeLabel', label);
    });
  }, [snapshot, risk, selectedNode, culpritNode, activeReroute]);

  // Dash animation loop (respects isPlaying and prefers-reduced-motion)
  useEffect(() => {
    const isReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (isReducedMotion || !isPlaying) return;

    let lastTime = performance.now();

    const animate = (time: number) => {
      const dt = (time - lastTime) / 1000;
      lastTime = time;

      dashOffsetRef.current = (dashOffsetRef.current - dt * 26) % 20;

      const cy = cyRef.current;
      if (cy) {
        cy.edges('[type = "telemetry"]').style('line-dash-offset', dashOffsetRef.current);
        cy.edges('[type = "reroute"]').style('line-dash-offset', dashOffsetRef.current * 1.5);
      }

      animFrameRef.current = requestAnimationFrame(animate);
    };

    animFrameRef.current = requestAnimationFrame(animate);

    return () => {
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [isPlaying]);

  const handleExportPng = () => {
    exportComponentPng({
      elementId: 'topology-card',
      fileName: `MeshHeal_Topology_${scenarioId}`,
      scenarioTitle: scenarioId,
      timeSeconds: t,
      isReplay: scenarioId === 'F',
    });
  };

  const handleFit = () => {
    if (cyRef.current) {
      cyRef.current.fit(undefined, 35);
    }
  };

  return (
    <div
      id="topology-card"
      className="glass-panel rounded-2xl p-5 flex flex-col h-full relative shadow-glass transition-all"
    >
      {/* Topology Header */}
      <div className="flex items-center justify-between pb-3.5 border-b border-border/70 flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
            <Zap className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-xs sm:text-sm font-semibold tracking-tight text-text">
              Service Mesh Topology &amp; Risk Graph
            </h2>
            <p className="text-[11px] text-muted font-mono">
              Istio mTLS • 3 Compound Namespaces (Multi-Cloud Layout)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {activeReroute && (
            <span className="flex items-center gap-1.5 text-xs font-mono px-3 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 shadow-sm animate-pulse-subtle">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Reroute Active: reviews-v1</span>
            </span>
          )}

          {/* Reset Fit */}
          <button
            onClick={handleFit}
            className="p-1.5 rounded-xl border border-border bg-surface-subtle hover:bg-surface-elevated text-muted hover:text-text transition-all"
            title="Reset Topology View"
            aria-label="Reset topology view"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>

          {/* Export PNG */}
          <button
            onClick={handleExportPng}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border border-border bg-surface-subtle hover:bg-surface-elevated text-muted hover:text-text transition-all shadow-sm"
            title="Export high-resolution 2x PNG with burned-in honesty badge"
            aria-label="Export topology PNG"
          >
            <Camera className="w-3.5 h-3.5" />
            <span>Export PNG</span>
          </button>
        </div>
      </div>

      {/* Main Cytoscape Canvas */}
      <div className="flex-1 relative w-full min-h-[380px] my-1">
        <div ref={containerRef} className="absolute inset-0 w-full h-full" />

        {/* Edge details popover if clicked */}
        {clickedEdgeData && (
          <div className="absolute top-4 left-4 bg-surface/95 backdrop-blur-md border border-border-strong rounded-2xl p-4 text-xs shadow-2xl z-30 font-mono min-w-[200px] animate-pulse-subtle">
            <div className="flex items-center justify-between gap-4 font-bold text-accent mb-2 pb-1 border-b border-border">
              <span>{clickedEdgeData.source} &rarr; {clickedEdgeData.target}</span>
              <button
                onClick={() => setClickedEdgeData(null)}
                className="text-muted hover:text-text text-base leading-none"
              >
                &times;
              </button>
            </div>
            <div className="space-y-1.5 text-text">
              <div className="flex justify-between">
                <span className="text-muted">p95 Latency:</span>
                <strong className="text-white">{clickedEdgeData.latency} ms</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Request Rate:</span>
                <strong className="text-white">{clickedEdgeData.rate} req/s</strong>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Error Rate:</span>
                <strong className="text-white">{(clickedEdgeData.error * 100).toFixed(2)}%</strong>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer Legend with Non-color Cues */}
      <div className="pt-3 border-t border-border/60 flex flex-wrap items-center justify-between gap-3 text-xs text-muted font-mono">
        <div className="flex items-center gap-3.5 flex-wrap">
          <span className="font-semibold text-text">Legend:</span>
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-teal-500/10 border border-teal-500/20 text-teal-300">
            <span className="w-2 h-2 rounded-full bg-teal-400" />
            <span>● OK (&lt;0.40)</span>
          </span>
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300">
            <span className="w-2 h-2 rounded-full bg-amber-400" />
            <span>▲ WARN (0.40-0.75)</span>
          </span>
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-rose-500/10 border border-rose-500/20 text-rose-300">
            <span className="w-2 h-2 rounded-full bg-rose-400" />
            <span>✖ CRIT (&gt;0.75)</span>
          </span>
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-rose-500/20 border border-rose-500/40 text-rose-300 font-bold">
            <Zap className="w-3 h-3 text-rose-400" />
            <span>⚡ Culprit</span>
          </span>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-muted">
          <Info className="w-3.5 h-3.5 text-accent" />
          <span>Width = req/s • Color = p95 • Click nodes &amp; edges for telemetry</span>
        </div>
      </div>
    </div>
  );
};
