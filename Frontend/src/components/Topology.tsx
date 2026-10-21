import React, { useEffect, useRef, useState } from 'react';
import cytoscape, { Core } from 'cytoscape';
import { Camera, Maximize2, ShieldCheck, Zap } from 'lucide-react';
import { useStore } from '../store';
import { NodeId } from '../data/types';
import { exportComponentPng } from '../utils/exportPng';

// Color bands matching policy lines (below 0.60 = OK, 0.60-0.85 = WARN, above 0.85 = CRITICAL)
const COLOR_OK = '#34D6B0';       // Teal
const COLOR_WARN = '#FFB347';     // Amber
const COLOR_CRIT = '#FF5C7C';     // Critical Vermillion
const COLOR_REROUTE = '#34D6B0';  // Mitigation path
const COLOR_CULPRIT = '#FF4F81';  // Culprit pulse

function getRiskColor(risk: number): string {
  if (risk > 0.85) return COLOR_CRIT;
  if (risk >= 0.60) return COLOR_WARN;
  return COLOR_OK;
}

function getRiskSymbol(risk: number, isCulprit: boolean): string {
  if (isCulprit) return '⚡';
  if (risk > 0.85) return '✖';
  if (risk >= 0.60) return '▲';
  return '●';
}

function getLatencyColor(p95: number): string {
  if (p95 > 80) return COLOR_CRIT;
  if (p95 > 25) return COLOR_WARN;
  return COLOR_OK;
}

const ALL_SERVICES: NodeId[] = ['productpage', 'details', 'reviews', 'ratings'];

export const Topology: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const dashOffsetRef = useRef<number>(0);

  const {
    simulationState,
    selectedNode,
    setSelectedNode,
    scenarioId,
    t,
    isPlaying,
  } = useStore();

  const [hoveredEdge, setHoveredEdge] = useState<{
    source: string;
    target: string;
    p95: number;
    rate: number;
    err: number;
    x: number;
    y: number;
  } | null>(null);

  const { snapshot, risk, activeReroute } = simulationState;

  // Determine culprit node
  const sortedRisks = Object.entries(risk.risk).sort((a, b) => b[1] - a[1]);
  const highestRiskNode = sortedRisks[0][0] as NodeId;
  const isHighRisk = sortedRisks[0][1] > 0.85;
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
        // AWS Region Compound Container
        {
          selector: 'node[type = "region"]',
          style: {
            'background-color': '#261B48',
            'background-opacity': 0.45,
            'border-width': 1.5,
            'border-color': 'rgba(255, 255, 255, 0.08)',
            'border-style': 'solid',
            'shape': 'round-rectangle',
            'label': 'data(label)',
            'color': '#A99BC9',
            'font-family': 'Inter, sans-serif',
            'font-size': 11,
            'font-weight': 600,
            'text-valign': 'top',
            'text-halign': 'center',
            'text-margin-y': 14,
            'padding': '28px',
          } as any,
        },
        // GCP and Azure small dashed chips ("namespace only, no workloads")
        {
          selector: 'node[type = "empty-region"]',
          style: {
            'background-color': 'rgba(29, 20, 56, 0.4)',
            'border-width': 1,
            'border-color': 'rgba(255, 255, 255, 0.08)',
            'border-style': 'dashed',
            'shape': 'round-rectangle',
            'label': 'data(label)',
            'color': '#756894',
            'font-family': 'Inter, sans-serif',
            'font-size': 10,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
            'width': 170,
            'height': 60,
          } as any,
        },
        // Service Nodes: rounded card with name + one risk number
        {
          selector: 'node[type = "service"]',
          style: {
            'width': 92,
            'height': 80,
            'shape': 'round-rectangle',
            'background-color': '#1D1438',
            'border-width': 2.5,
            'border-color': 'data(borderColor)',
            'label': 'data(displayLabel)',
            'color': '#F4F0FF',
            'font-family': 'Inter, sans-serif',
            'font-size': 11,
            'font-weight': 600,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
            'text-max-width': '84px',
            'cursor': 'pointer',
            'transition-property': 'background-color, border-color, border-width',
            'transition-duration': 0.2,
          } as any,
        },
        // Standby bypass node for reviews-v1
        {
          selector: 'node[type = "reroute-service"]',
          style: {
            'width': 92,
            'height': 80,
            'shape': 'round-rectangle',
            'background-color': '#142A38',
            'background-opacity': 0.5,
            'border-width': 2,
            'border-color': COLOR_REROUTE,
            'border-style': 'dashed',
            'label': 'data(displayLabel)',
            'color': '#34D6B0',
            'font-family': 'Inter, sans-serif',
            'font-size': 10,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-wrap': 'wrap',
          } as any,
        },
        // Culprit pulsing node
        {
          selector: '.is-culprit',
          style: {
            'border-width': 4.5,
            'border-color': COLOR_CULPRIT,
          } as any,
        },
        // Selected node
        {
          selector: '.is-selected',
          style: {
            'border-width': 4,
            'border-color': '#6D4AFF',
          } as any,
        },
        // Telemetry Edges: labels hidden by default to prevent node collision
        {
          selector: 'edge[type = "telemetry"]',
          style: {
            'width': 'data(edgeWidth)',
            'line-color': 'data(edgeColor)',
            'target-arrow-color': 'data(edgeColor)',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'line-style': 'dashed',
            'line-dash-pattern': [6, 4],
            'cursor': 'pointer',
          } as any,
        },
        // Reroute overlay edge
        {
          selector: 'edge[type = "reroute"]',
          style: {
            'width': 3.5,
            'line-color': COLOR_REROUTE,
            'target-arrow-color': COLOR_REROUTE,
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'line-style': 'dashed',
            'line-dash-pattern': [8, 4],
          } as any,
        },
      ],
      elements: [
        // Compound Regions
        {
          data: {
            id: 'region-aws',
            type: 'region',
            label: 'aws-us-east',
          },
        },
        {
          data: {
            id: 'region-gcp',
            type: 'empty-region',
            label: 'gcp-asia\nnamespace only, no workloads',
          },
          position: { x: 580, y: 110 },
        },
        {
          data: {
            id: 'region-azure',
            type: 'empty-region',
            label: 'azure-eu\nnamespace only, no workloads',
          },
          position: { x: 580, y: 270 },
        },
        // Services inside AWS
        {
          data: {
            id: 'productpage',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'productpage\n● 0.08',
            borderColor: COLOR_OK,
          },
          position: { x: 100, y: 190 },
        },
        {
          data: {
            id: 'details',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'details\n● 0.07',
            borderColor: COLOR_OK,
          },
          position: { x: 260, y: 100 },
        },
        {
          data: {
            id: 'reviews',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'reviews\n● 0.11',
            borderColor: COLOR_OK,
          },
          position: { x: 260, y: 280 },
        },
        {
          data: {
            id: 'ratings',
            parent: 'region-aws',
            type: 'service',
            displayLabel: 'ratings\n● 0.08',
            borderColor: COLOR_OK,
          },
          position: { x: 420, y: 280 },
        },
        // Standby bypass reviews-v1
        {
          data: {
            id: 'reviews-v1',
            parent: 'region-aws',
            type: 'reroute-service',
            displayLabel: 'reviews-v1\n(bypass)',
          },
          position: { x: 420, y: 150 },
        },
        // Edges
        {
          data: {
            id: 'edge-p-d',
            source: 'productpage',
            target: 'details',
            type: 'telemetry',
            edgeWidth: 2.5,
            edgeColor: COLOR_OK,
          },
        },
        {
          data: {
            id: 'edge-p-r',
            source: 'productpage',
            target: 'reviews',
            type: 'telemetry',
            edgeWidth: 3,
            edgeColor: COLOR_OK,
          },
        },
        {
          data: {
            id: 'edge-r-r',
            source: 'reviews',
            target: 'ratings',
            type: 'telemetry',
            edgeWidth: 2.8,
            edgeColor: COLOR_OK,
          },
        },
        {
          data: {
            id: 'edge-reroute-overlay',
            source: 'productpage',
            target: 'reviews-v1',
            type: 'reroute',
          },
        },
      ],
      layout: {
        name: 'preset',
      },
    });

    cy.fit(undefined, 30);

    // Node click -> open detail drawer
    cy.on('tap', 'node[type = "service"]', (evt) => {
      const node = evt.target;
      setSelectedNode(node.id() as NodeId);
    });

    // Edge hover -> show floating pill badge (Fix 1: prevents node collision)
    cy.on('mouseover', 'edge[type = "telemetry"]', (evt) => {
      const edge = evt.target;
      const s = edge.source().id() as NodeId;
      const d = edge.target().id() as NodeId;
      const snap = useStore.getState().simulationState.snapshot;
      const found = snap.edges.find((e) => e.source === s && e.destination === d);
      const renderedPos = edge.midpoint();
      if (found) {
        setHoveredEdge({
          source: s,
          target: d,
          p95: found.latency_p95,
          rate: found.request_rate,
          err: found.error_rate,
          x: renderedPos.x,
          y: renderedPos.y,
        });
      }
    });

    cy.on('mouseout', 'edge[type = "telemetry"]', () => {
      setHoveredEdge(null);
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [setSelectedNode]);

  // Update Cytoscape when simulation state changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Update Nodes: single risk number e.g. 0.88, no duplicated percentage
    ALL_SERVICES.forEach((nodeId) => {
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

      if (selectedNode === nodeId) {
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

      const edgeWidth = Math.max(2, Math.min(6, edge.request_rate * 9));
      const edgeColor = getLatencyColor(edge.latency_p95);

      edgeElem.data('edgeWidth', edgeWidth);
      edgeElem.data('edgeColor', edgeColor);
    });
  }, [snapshot, risk, selectedNode, culpritNode, activeReroute]);

  // Dash animation loop (stops when paused or prefers-reduced-motion)
  useEffect(() => {
    const isReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (isReducedMotion || !isPlaying) return;

    let lastTime = performance.now();

    const animate = (time: number) => {
      const dt = (time - lastTime) / 1000;
      lastTime = time;

      dashOffsetRef.current = (dashOffsetRef.current - dt * 20) % 20;

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
      elementId: 'topology-stage-card',
      fileName: `MeshHeal_Topology_${scenarioId}`,
      scenarioTitle: scenarioId,
      timeSeconds: t,
      isReplay: scenarioId === 'F',
    });
  };

  const handleFit = () => {
    if (cyRef.current) cyRef.current.fit(undefined, 30);
  };

  return (
    <div
      id="topology-stage-card"
      className="card-stage p-6 sm:p-8 flex flex-col h-full relative transition-all"
    >
      {/* Stage Header */}
      <div className="flex items-center justify-between pb-4 border-b border-border flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-base sm:text-lg font-semibold tracking-tight text-text">
            Service Mesh Topology
          </h2>
          <span className="text-xs text-muted font-mono hidden sm:inline">
            3 simulated regions • 4 services
          </span>
        </div>

        <div className="flex items-center gap-2.5">
          {activeReroute && (
            <span className="flex items-center gap-1.5 text-xs font-mono px-3 py-1 rounded-pill bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Shifted to reviews-v1</span>
            </span>
          )}

          <button
            onClick={handleFit}
            className="p-2 rounded-pill border border-border bg-surface-2 hover:bg-surface text-muted hover:text-text transition-all"
            title="Fit topology view"
            aria-label="Fit topology view"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={handleExportPng}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-pill text-xs font-medium border border-border bg-surface-2 hover:bg-surface text-muted hover:text-text transition-all"
            title="Export 2x PNG with honesty badge"
            aria-label="Export topology PNG"
          >
            <Camera className="w-3.5 h-3.5" />
            <span>Export PNG</span>
          </button>
        </div>
      </div>

      {/* Keyboard-accessible Service List Bar (Fix 2: full names, replaces truncated tabs) */}
      <div
        className="flex items-center justify-between pt-3 pb-2 text-xs"
        role="region"
        aria-label="Keyboard accessible service selector"
      >
        <span className="text-muted text-[11px] font-mono">Select service to inspect:</span>
        <div className="flex items-center gap-1.5">
          {ALL_SERVICES.map((id) => (
            <button
              key={id}
              onClick={() => setSelectedNode(id)}
              className={`px-3 py-1 rounded-pill text-xs font-mono font-medium transition-all ${
                selectedNode === id
                  ? 'bg-primary text-white font-semibold shadow-sm'
                  : 'bg-surface-2 text-muted hover:text-text border border-border'
              }`}
              title={`Inspect ${id} telemetry and safety guardrails`}
            >
              {id}
            </button>
          ))}
        </div>
      </div>

      {/* Cytoscape Canvas */}
      <div className="flex-1 relative w-full min-h-[380px] my-2">
        <div ref={containerRef} className="absolute inset-0 w-full h-full" />

        {/* Floating Edge Telemetry Pill on Hover (Fix 1: prevents node collisions) */}
        {hoveredEdge && (
          <div
            className="absolute pointer-events-none z-30 font-mono text-xs px-3 py-1.5 rounded-pill bg-surface border border-border shadow-card flex items-center gap-2 transform -translate-x-1/2 -translate-y-8 animate-pulse-subtle"
            style={{ left: hoveredEdge.x, top: hoveredEdge.y }}
          >
            <span className="font-semibold text-text">{hoveredEdge.source} &rarr; {hoveredEdge.target}</span>
            <span className="text-muted">|</span>
            <span className="text-ok font-bold">{hoveredEdge.p95} ms</span>
            <span className="text-muted">|</span>
            <span className="text-text">{hoveredEdge.rate} r/s</span>
          </div>
        )}
      </div>

      {/* Footer Legend (Fix 7: below 0.60 = OK, 0.60-0.85 = WARN, above 0.85 = CRITICAL) */}
      <div className="pt-3 border-t border-border flex flex-wrap items-center justify-between gap-3 text-xs text-muted font-mono">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-semibold text-text">Threshold bands:</span>
          <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-pill bg-teal-500/10 border border-teal-500/20 text-teal-300">
            <span className="w-2 h-2 rounded-full bg-ok" />
            <span>● OK (&lt;0.60)</span>
          </span>
          <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-pill bg-amber-500/10 border border-amber-500/20 text-amber-300">
            <span className="w-2 h-2 rounded-full bg-warn" />
            <span>▲ WARN (0.60–0.85)</span>
          </span>
          <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-pill bg-rose-500/10 border border-rose-500/20 text-rose-300">
            <span className="w-2 h-2 rounded-full bg-critical" />
            <span>✖ CRITICAL (&gt;0.85)</span>
          </span>
          <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-pill bg-rose-500/20 border border-rose-500/40 text-rose-300 font-bold">
            <Zap className="w-3 h-3 text-critical" />
            <span>⚡ Culprit</span>
          </span>
        </div>

        <div className="text-[11px] text-muted">
          Click node to open detail drawer • Hover edges for metrics
        </div>
      </div>
    </div>
  );
};
