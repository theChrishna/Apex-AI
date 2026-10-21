import { describe, it, expect } from 'vitest';
import {
  computeSimulationState,
  DEFAULT_POLICY,
} from './simulatedDataSource';
import { NodeId } from './types';

describe('MeshHeal AI Scenario Engine Unit Tests', () => {
  // Test 1: Scenario engine is deterministic for a fixed seed
  it('is deterministic for a fixed seed across multiple runs', () => {
    const seed = 42;
    const scenarios = ['A', 'B', 'C', 'D', 'E'];
    const timepoints = [0, 60, 120, 180, 240, 300, 420, 495, 600];

    for (const sc of scenarios) {
      for (const t of timepoints) {
        const run1 = computeSimulationState(sc, t, DEFAULT_POLICY, seed);
        const run2 = computeSimulationState(sc, t, DEFAULT_POLICY, seed);

        // Snapshots must match exactly
        expect(run1.snapshot.t).toBe(run2.snapshot.t);
        expect(run1.snapshot.edges).toEqual(run2.snapshot.edges);

        // Risk scores must match exactly
        expect(run1.risk.t).toBe(run2.risk.t);
        expect(run1.risk.risk).toEqual(run2.risk.risk);
        expect(run1.risk.source).toBe(run2.risk.source);

        // Audit logs must match exactly
        expect(run1.audit).toEqual(run2.audit);

        // Safety checks must match exactly
        expect(run1.safetyCheck).toEqual(run2.safetyCheck);
      }
    }
  });

  // Test 2: Risk never exceeds [0, 1]
  it('guarantees risk scores strictly remain in [0, 1] across all scenarios and times', () => {
    const scenarios = ['A', 'B', 'C', 'D', 'E'];
    const nodes: NodeId[] = ['productpage', 'details', 'reviews', 'ratings'];

    for (const sc of scenarios) {
      // Sample every 5 seconds across the entire 600s scenario
      for (let t = 0; t <= 600; t += 5) {
        const state = computeSimulationState(sc, t, DEFAULT_POLICY, 1337);

        for (const node of nodes) {
          const score = state.risk.risk[node];
          expect(score).toBeGreaterThanOrEqual(0);
          expect(score).toBeLessThanOrEqual(1);
          expect(Number.isFinite(score)).toBe(true);
        }
      }
    }
  });

  // Test 3: The audit log is time-ordered
  it('ensures the audit trail is strictly time-ordered (t_i >= t_{i-1})', () => {
    const scenarios = ['A', 'B', 'C', 'D', 'E'];
    const checkTimes = [100, 180, 250, 450, 600];

    for (const sc of scenarios) {
      for (const t of checkTimes) {
        const state = computeSimulationState(sc, t, DEFAULT_POLICY, 1337);
        const audit = state.audit;

        for (let i = 1; i < audit.length; i++) {
          expect(audit[i].t).toBeGreaterThanOrEqual(audit[i - 1].t);
          // Also verify each audit event time does not exceed the current snapshot time
          expect(audit[i].t).toBeLessThanOrEqual(t);
        }
      }
    }
  });
});
