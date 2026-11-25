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


class BaselineScorer:
    """Per-service learned normal envelope of incoming and outgoing latency.

    For each service it knows the median and a high quantile (default q0.99) of normal traffic. Risk only rises when
    the incoming latency goes ABOVE that normal high value, by more than the downstream calls went above theirs (so a
    victim still cancels out, like RuleScorer's in_lat - out_lat). The excess is measured in units of the service's
    own normal spread (high - median, at least floor_ms).

    Why an envelope and not median + MAD: Istio's p95 is bucketed (values like 48.75, 97.5, 242.5). A low-traffic
    service sits on one bucket value most of the time, so its MAD is 0, yet one slow request regularly lifts it to the
    next bucket. MAD then calls a normal bucket jump a huge outlier. A first median+MAD version cut Online Boutique's
    false-alarm rate from 92% to 32% but no further (topo/results/phase4_baseline_boutique_MAD.md); the envelope keeps
    normal bucket jumps inside the normal range.

    Learn baselines with `python -m controlplane.learn_baseline` on fault-free snapshots. A service not in the file
    falls back to RuleScorer's hand-set scale.
    """
    name = "baseline"

    def __init__(self, baselines=None, full_ms=100.0, floor_ms=10.0, min_rate=0.05, saturation="soft", anchor=0.85):
        """baselines: {service: {"in_lat": {"median": ms, "high": ms}, "out_lat": {...}}}.

        saturation: how a raw excess (in units of normal spread) becomes a risk in [0, 1).
          "clamp": min(1, raw). Every large excess becomes exactly 1.0, so two services far above normal TIE and the
                   ranking between them is lost (the culprit and a victim both at 1.0; the tie breaks by name).
          "soft":  1 - (1 - anchor) ** (raw / anchor). Same value as clamp at raw = anchor, so exactly the same
                   snapshots cross the act threshold (anchor = the controller's 0.85), but a larger excess still
                   ranks higher.
        """
        if saturation not in ("clamp", "soft"):
            raise ValueError("saturation must be clamp or soft")
        self.baselines = dict(baselines or {})
        self.full_ms, self.floor_ms, self.min_rate = float(full_ms), float(floor_ms), float(min_rate)
        self.saturation, self.anchor = saturation, float(anchor)
        self.coverage = {}                      # service -> True if it has a baseline (set after the first score)

    @classmethod
    def from_file(cls, path, **kw):
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
            raise ValueError(f"{path}: expected a mapping with 'services'")
        opts = {k: data[k] for k in ("floor_ms", "min_rate", "anchor") if isinstance(data.get(k), (int, float))}
        if data.get("saturation") in ("clamp", "soft"):
            opts["saturation"] = data["saturation"]
        opts.update({k: v for k, v in kw.items() if v is not None})
        return cls(baselines=data["services"], **opts)

    def _env(self, service, kind):
        b = self.baselines.get(service, {}).get(kind)
        if not isinstance(b, dict) or "median" not in b or "high" not in b:
            return None
        med, high = float(b["median"]), float(b["high"])
        return med, high, max(high - med, self.floor_ms)

    def _saturate(self, raw):
        if raw <= 0:
            return 0.0
        if self.saturation == "clamp":
            return min(1.0, raw)
        return 1.0 - (1.0 - self.anchor) ** (raw / self.anchor)

    def score(self, stats):
        out = {}
        for n, s in stats.items():
            self.coverage[n] = n in self.baselines
            env_in = self._env(n, "in_lat")
            if env_in is None:                                     # no baseline: same shape as RuleScorer
                raw = (s["in_lat"] - s["out_lat"]) / self.full_ms
            else:
                _, high_in, spread = env_in
                excess_in = max(0.0, s["in_lat"] - high_in)
                env_out = self._env(n, "out_lat")
                excess_out = max(0.0, s["out_lat"] - env_out[1]) if env_out else 0.0
                raw = (excess_in - excess_out) / spread
            risk = self._saturate(raw)
            if s["in_rate"] < self.min_rate:                       # rate floor: an idle service cannot be the culprit
                risk = 0.0
            out[n] = risk
        return out


class EdgeScorer:
    """Per-EDGE learned envelopes of latency and error fraction (Phase 4, second step).

    Why per edge: BaselineScorer works per service, so a service's outgoing latency is a rate-weighted average over ALL
    its calls. A victim waiting on one slow but rarely called edge (Online Boutique: frontend -> shipping) barely moves
    that average, the victim does not cancel, and the victim gets blamed. Here a service cancels against its single
    worst outgoing edge. Each edge also learns its own normal range, including the noise of a rarely used edge, so the
    hard 0.05 req/s floor that blinded the scorer to Boutique's checkout path is replaced by "at least one request a
    minute".

    For each service S:
      latency: the incoming edge furthest above its normal high (in units of that edge's spread), minus, in ms, the worst
               excess on S's outgoing edges (a victim cancels against the edge it waits on). With `fanout` (default),
               the larger of that and the sum over outgoing edges of excess x calls per incoming request (capped at
               `max_calls`): a caller that calls a slow service several times per request waits several times as long
               (the live canary test, REPORT_PHASE6.md). Calls in parallel make this over-subtract, which can only
               lower the caller's score.
      errors:  the incoming error fraction above normal, minus the worst outgoing error excess (a service that only
               passes its callee's errors on cancels), in units of the edge's error spread (at least err_floor)
      risk = saturate(max(latency part, error part)), with the same act-threshold-preserving curve as BaselineScorer.

    Error fractions use the caller-side counts (src_request_rate / src_error_rate) when the snapshot has them: errors
    injected by Istio never reach the destination. Older snapshots only have destination-side counts.
    Edges without a learned envelope behave like the hand-set rule (normal high 0 ms, spread full_ms).
    """
    name = "edge"
    needs_snapshot = True

    def __init__(self, edges=None, full_ms=100.0, floor_ms=10.0, min_rate=1 / 60, err_floor=0.05,
                 saturation="soft", anchor=0.85, fanout=True, max_calls=10.0):
        if saturation not in ("clamp", "soft"):
            raise ValueError("saturation must be clamp or soft")
        self.edges = dict(edges or {})
        self.fanout, self.max_calls = bool(fanout), float(max_calls)
        self.full_ms, self.floor_ms, self.min_rate, self.err_floor = float(full_ms), float(floor_ms), float(min_rate), float(err_floor)
        self.saturation, self.anchor = saturation, float(anchor)

    @classmethod
    def from_file(cls, path, **kw):
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict) or not isinstance(data.get("edges"), dict):
            raise ValueError(f"{path}: expected a mapping with 'edges' (learn it with controlplane.learn_baseline)")
        opts = {k: data[k] for k in ("floor_ms", "anchor", "err_floor") if isinstance(data.get(k), (int, float))}
        if isinstance(data.get("edge_min_rate"), (int, float)):
            opts["min_rate"] = data["edge_min_rate"]
        opts.update({k: v for k, v in kw.items() if v is not None})
        return cls(edges=data["edges"], **opts)

    @staticmethod
    def key(src, dst):
        return f"{src}>{dst}"

    @staticmethod
    def rate(e):
        return max(e.get("request_rate") or 0.0, e.get("src_request_rate") or 0.0)

    @staticmethod
    def error_fraction(e):
        """Share of failed requests on an edge, caller-side counts preferred. 0 when there is no traffic."""
        if (e.get("src_request_rate") or 0.0) > 0:
            return min(1.0, (e.get("src_error_rate") or 0.0) / e["src_request_rate"])
        r = e.get("request_rate") or 0.0
        return min(1.0, (e.get("error_rate") or 0.0) / r) if r > 0 else 0.0

    def _lat(self, key, ms):
        b = self.edges.get(key, {}).get("lat")
        if isinstance(b, dict) and "median" in b and "high" in b:
            high, spread = float(b["high"]), max(float(b["high"]) - float(b["median"]), self.floor_ms)
        else:
            high, spread = 0.0, self.full_ms
        return max(0.0, ms - high), spread

    def _err(self, key, frac):
        b = self.edges.get(key, {}).get("err")
        if isinstance(b, dict) and "median" in b and "high" in b:
            high, spread = float(b["high"]), max(float(b["high"]) - float(b["median"]), self.err_floor)
        else:
            high, spread = 0.0, self.err_floor
        return max(0.0, frac - high), spread

    def _saturate(self, raw):
        if raw <= 0:
            return 0.0
        if self.saturation == "clamp":
            return min(1.0, raw)
        return 1.0 - (1.0 - self.anchor) ** (raw / self.anchor)

    def score(self, stats, snap=None):
        if snap is None:
            raise ValueError("EdgeScorer needs the snapshot")
        nodes = set(stats) | {n["id"] for n in snap.nodes}
        best_in = {n: (0.0, 0.0, self.full_ms) for n in nodes}       # node -> (normalised excess, excess ms, spread)
        out_ms = {n: 0.0 for n in nodes}
        best_in_err = {n: (0.0, 0.0, self.err_floor) for n in nodes}
        out_err = {n: 0.0 for n in nodes}
        in_rate = {n: 0.0 for n in nodes}
        for e in snap.edges:
            if e["destination"] in in_rate:
                in_rate[e["destination"]] += self.rate(e)
        fan_ms = {n: 0.0 for n in nodes}           # outgoing excess weighted by calls per incoming request
        for e in snap.edges:
            s, d = e["source"], e["destination"]
            if self.rate(e) < self.min_rate:
                continue
            k = self.key(s, d)
            ex_ms, spread = self._lat(k, e.get("latency_p95") or 0.0)
            ex_err, espread = self._err(k, self.error_fraction(e))
            if d in best_in and ex_ms / spread > best_in[d][0]:
                best_in[d] = (ex_ms / spread, ex_ms, spread)
            if d in best_in_err and ex_err / espread > best_in_err[d][0]:
                best_in_err[d] = (ex_err / espread, ex_err, espread)
            if s in out_ms:
                out_ms[s] = max(out_ms[s], ex_ms)
                out_err[s] = max(out_err[s], ex_err)
                if in_rate[s] > 0:
                    fan_ms[s] += min(self.rate(e) / in_rate[s], self.max_calls) * ex_ms
        out = {}
        for n in nodes:
            _, in_ms, spread = best_in[n]
            explained = max(out_ms[n], fan_ms[n]) if self.fanout else out_ms[n]
            raw_lat = (in_ms - explained) / spread
            _, in_err, espread = best_in_err[n]
            raw_err = (in_err - out_err[n]) / espread
            out[n] = self._saturate(max(raw_lat, raw_err))
        return out


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
            return ScoreResult(_score(self.fallback, stats, snap), "fallback", f"primary error: {type(e).__name__}({e})")


def as_result(scorer, stats, snap=None):
    r = _score(scorer, stats, snap)
    return r if isinstance(r, ScoreResult) else ScoreResult(r, "primary")
