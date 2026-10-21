import { create } from 'zustand';
import {
  NodeId,
  PolicyConfig,
  ScenarioMeta,
  SimulationState,
} from './data/types';
import {
  computeSimulationState,
  DEFAULT_POLICY,
  SimulatedDataSource
} from './data/simulatedDataSource';
import { SCENARIOS } from './data/scenarios';
import { ReplayAdapter, ReplayEpisodeMeta } from './data/replayAdapter';

interface AppState {
  // Navigation & Display
  view: 'overview' | 'evaluation';
  theme: 'dark' | 'light';
  chrome: number; // 0 = minimal print/export mode, 1 = full controls
  
  // Playback & Scenarios
  scenarioId: string;
  t: number; // 0 - 600 seconds
  isPlaying: boolean;
  speed: 1 | 2 | 4;
  policy: PolicyConfig;
  
  // Replay integration
  replayEpisodes: Map<string, ReplayEpisodeMeta> | null;
  selectedReplayEpisode: string | null;
  
  // Selection
  selectedNode: NodeId | null;
  selectedEdge: { source: NodeId; destination: NodeId } | null;
  
  // Computed simulation data
  simulationState: SimulationState;
  
  // Actions
  setView: (view: 'overview' | 'evaluation') => void;
  setTheme: (theme: 'dark' | 'light') => void;
  setChrome: (chrome: number) => void;
  setScenario: (id: string) => void;
  setReplayEpisode: (episode: string) => void;
  setTime: (t: number) => void;
  togglePlay: () => void;
  setPlaying: (playing: boolean) => void;
  setSpeed: (speed: 1 | 2 | 4) => void;
  setSelectedNode: (node: NodeId | null) => void;
  setSelectedEdge: (edge: { source: NodeId; destination: NodeId } | null) => void;
  updatePolicy: (policy: Partial<PolicyConfig>) => void;
  tick: (deltaSeconds: number) => void;
  checkReplay: () => Promise<void>;
}

// Compute state helper
function getStateFor(
  scenarioId: string,
  t: number,
  policy: PolicyConfig,
  replayEpisodes: Map<string, ReplayEpisodeMeta> | null,
  selectedReplayEpisode: string | null
): SimulationState {
  if (scenarioId === 'F' && replayEpisodes && selectedReplayEpisode) {
    const epMeta = replayEpisodes.get(selectedReplayEpisode);
    if (epMeta) {
      return ReplayAdapter.computeReplayState(epMeta, t);
    }
  }
  return computeSimulationState(scenarioId, t, policy);
}

// URL sync helper
function updateUrlParams(scenario: string, t: number, view: string, theme: string, chrome: number) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  url.searchParams.set('scenario', scenario);
  url.searchParams.set('t', Math.round(t).toString());
  url.searchParams.set('view', view);
  url.searchParams.set('theme', theme);
  url.searchParams.set('chrome', chrome.toString());
  window.history.replaceState({}, '', url.toString());
}

export const useStore = create<AppState>((set, get) => {
  // Read initial query params if present
  let initialScenario = 'A';
  let initialT = 0;
  let initialView: 'overview' | 'evaluation' = 'overview';
  let initialTheme: 'dark' | 'light' = 'dark';
  let initialChrome = 1;
  let autoPlay = true;

  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    if (params.has('scenario')) initialScenario = params.get('scenario')!;
    if (params.has('t')) {
      initialT = Math.max(0, Math.min(600, Number(params.get('t')) || 0));
      autoPlay = false; // Freeze if t was explicitly requested
    }
    if (params.get('view') === 'evaluation') initialView = 'evaluation';
    if (params.get('theme') === 'light') initialTheme = 'light';
    if (params.has('chrome')) initialChrome = Number(params.get('chrome')) || 0;
  }

  const initialSimState = computeSimulationState(initialScenario, initialT, DEFAULT_POLICY);

  return {
    view: initialView,
    theme: initialTheme,
    chrome: initialChrome,
    scenarioId: initialScenario,
    t: initialT,
    isPlaying: autoPlay,
    speed: 1,
    policy: { ...DEFAULT_POLICY },
    replayEpisodes: null,
    selectedReplayEpisode: null,
    selectedNode: null, // null defaults to highest risk
    selectedEdge: null,
    simulationState: initialSimState,

    setView: (view) => {
      set({ view });
      const { scenarioId, t, theme, chrome } = get();
      updateUrlParams(scenarioId, t, view, theme, chrome);
    },

    setTheme: (theme) => {
      set({ theme });
      if (typeof document !== 'undefined') {
        if (theme === 'light') {
          document.documentElement.classList.add('light');
        } else {
          document.documentElement.classList.remove('light');
        }
      }
      const { scenarioId, t, view, chrome } = get();
      updateUrlParams(scenarioId, t, view, theme, chrome);
    },

    setChrome: (chrome) => {
      set({ chrome });
      const { scenarioId, t, view, theme } = get();
      updateUrlParams(scenarioId, t, view, theme, chrome);
    },

    setScenario: (scenarioId) => {
      const { policy, replayEpisodes, selectedReplayEpisode, view, theme, chrome } = get();
      const sim = getStateFor(scenarioId, 0, policy, replayEpisodes, selectedReplayEpisode);
      set({
        scenarioId,
        t: 0,
        simulationState: sim,
        selectedNode: null,
        selectedEdge: null,
      });
      updateUrlParams(scenarioId, 0, view, theme, chrome);
    },

    setReplayEpisode: (episode) => {
      const { scenarioId, policy, replayEpisodes, view, theme, chrome } = get();
      const sim = getStateFor(scenarioId, 0, policy, replayEpisodes, episode);
      set({
        selectedReplayEpisode: episode,
        t: 0,
        simulationState: sim,
      });
      updateUrlParams(scenarioId, 0, view, theme, chrome);
    },

    setTime: (newT) => {
      const boundedT = Math.max(0, Math.min(600, newT));
      const { scenarioId, policy, replayEpisodes, selectedReplayEpisode, view, theme, chrome } = get();
      const sim = getStateFor(scenarioId, boundedT, policy, replayEpisodes, selectedReplayEpisode);
      set({ t: boundedT, simulationState: sim });
      updateUrlParams(scenarioId, boundedT, view, theme, chrome);
    },

    togglePlay: () => {
      set((state) => ({ isPlaying: !state.isPlaying }));
    },

    setPlaying: (isPlaying) => {
      set({ isPlaying });
    },

    setSpeed: (speed) => {
      set({ speed });
    },

    setSelectedNode: (selectedNode) => {
      set({ selectedNode, selectedEdge: null });
    },

    setSelectedEdge: (selectedEdge) => {
      set({ selectedEdge, selectedNode: null });
    },

    updatePolicy: (policyUpdates) => {
      set((state) => {
        const newPolicy = { ...state.policy, ...policyUpdates };
        const sim = getStateFor(
          state.scenarioId,
          state.t,
          newPolicy,
          state.replayEpisodes,
          state.selectedReplayEpisode
        );
        return { policy: newPolicy, simulationState: sim };
      });
    },

    tick: (deltaSeconds) => {
      const { t, isPlaying, speed, scenarioId, policy, replayEpisodes, selectedReplayEpisode, view, theme, chrome } = get();
      if (!isPlaying) return;

      let nextT = t + deltaSeconds * speed;
      if (nextT > 600) {
        nextT = 0; // loop
      }

      const sim = getStateFor(scenarioId, nextT, policy, replayEpisodes, selectedReplayEpisode);
      set({ t: nextT, simulationState: sim });
      // Throttle URL update to integer seconds
      if (Math.floor(nextT) !== Math.floor(t)) {
        updateUrlParams(scenarioId, nextT, view, theme, chrome);
      }
    },

    checkReplay: async () => {
      const episodes = await ReplayAdapter.loadEpisodes();
      if (episodes && episodes.size > 0) {
        const firstEp = Array.from(episodes.keys())[0];
        set({ replayEpisodes: episodes, selectedReplayEpisode: firstEp });
      } else {
        set({ replayEpisodes: null });
      }
    },
  };
});
