"""Scorers map per-node stats -> risk in [0,1]. The GNN plugs in behind the same interface."""
import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass


@dataclass
class ScoreResult:
    scores: dict
    source: str          # "primary" | "fallback"
    note: str = ""


class RuleScorer:
    """Culprit rule: a node is suspect when latency *into* it is high and is NOT explained by its own
    downstream calls (in_lat - out_lat). A victim (e.g. reviews waiting on ratings) cancels out."""
    name = "rule"

    def __init__(self, full_ms=100.0):
        self.full_ms = full_ms

    def score(self, stats):
        return {n: min(1.0, max(0.0, (s["in_lat"] - s["out_lat"]) / self.full_ms))
                for n, s in stats.items()}


def _score(scorer, stats, snap):
    """Scorers that set needs_snapshot (the GNN) also get the raw snapshot."""
    return scorer.score(stats, snap) if getattr(scorer, "needs_snapshot", False) else scorer.score(stats)


class ResilientScorer:
    """FR-4.1: use the primary scorer inside a time budget, else the fallback; never raise."""
    needs_snapshot = True

    def __init__(self, primary, fallback, timeout_s=0.5):
        self.primary, self.fallback, self.timeout_s = primary, fallback, timeout_s
        self._pool = ThreadPoolExecutor(max_workers=1)
        self.name = f"{getattr(primary, 'name', 'primary')}+fallback"

    def score(self, stats, snap=None):
        try:
            fut = self._pool.submit(_score, self.primary, stats, snap)
            scores = fut.result(timeout=self.timeout_s)
            if not scores or any((v is None) or math.isnan(v) for v in scores.values()):
                raise ValueError("non-finite scores")
            return ScoreResult(scores, "primary")
        except FutTimeout:
            return ScoreResult(_score(self.fallback, stats, snap), "fallback", f"primary timeout >{self.timeout_s}s")
        except Exception as e:  # primary crashed / bad output
            return ScoreResult(_score(self.fallback, stats, snap), "fallback", f"primary error: {e!r}")


def as_result(scorer, stats, snap=None):
    r = _score(scorer, stats, snap)
    return r if isinstance(r, ScoreResult) else ScoreResult(r, "primary")
