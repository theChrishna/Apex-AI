# Data provenance

Where every dataset in this project comes from and how it was labelled. **None of it is company or production traffic.**
Say so in any report. All faults were injected on purpose by us (Istio `fault.delay`, 100% of requests) because real incidents
are rare and unlabelled; that is how ground truth is obtained for this kind of work.

| Dataset | Origin | Traffic | Faults and labels | Size | Date |
|---|---|---|---|---|---|
| `snapshots.jsonl`, `fault_log.jsonl` (+ `labeled_dataset*.jsonl`) | **Real app, test cluster**: Istio Bookinfo on k3d | `traffic_gen.py`, about 0.3 req/s | 8 delay episodes (50 to 200 ms on ratings, details, reviews), labelled with the Bookinfo rules (lag 90 s excluded, steady positive on the faulted service only, recovery 90 s excluded) | 808 snapshots | Sep to Oct 2026 |
| `topo/boutique_snapshots_clean.jsonl` + `topo/boutique_fault_log.jsonl` | **Real app, test cluster**: Online Boutique v0.10.7 (12 services, gRPC) on k3d (k3s v1.33.5), Istio 1.32.0 demo profile, Prometheus addon | The app's own Locust load generator, `USERS=3` (about 0.6 req/s end to end) | 10 episodes of 5 min, one per service (payment +100, recommendation +50, shipping +200, productcatalog +50, frontend +200, currency +200, ad +50, email +200, cart +150, checkout +100 ms), same labelling rules as above | 354 snapshots; 139 steady and 27 normal after labelling | 2026-11-24, 08:10 to 09:28 UTC |
| `topo/boutique_snapshots_normal.jsonl` | Same Online Boutique, **no faults** | Same load generator | All snapshots normal, all labels 0 (first 2 dropped: rate window warming up) | 140 snapshots (138 used), continuous at 15 s from 09:32 to 10:07 UTC; collection ended early when the machine slept | 2026-11-24, 09:32 to 10:07 UTC |

The real-Boutique evaluation (`topo/results/phase3_boutique_run1.md`) therefore tests on 304 snapshots: 139 steady (10 episodes) and 165 normal (27 from the fault run plus 138 from the fault-free file).
| Simulated corpus (`python -m topo.generate`; evaluation corpus seed 0) | **Synthetic**: `topo/sim.py` | Simulated request counts | Simulated delay faults with the same labelling rule | 5,760 snapshots, 40 random topologies of 4 to 25 services | generated on demand |

## Quality checks that were run
- `python -m topo.check_boutique` on the Boutique fault run: 10/10 faults visible on a culprit edge, 10/10 isolated (no unrelated edge rose by half the injected delay or more).
- `python -m topo.calibrate`: simulated Bookinfo against real Bookinfo (normal-phase quartiles and rates match closely; a nominal 100 ms delay on a fast service reads 97.5 ms in real data, so the simulator draws a 0 to 8 ms shortfall per episode instead of a fixed number).

## Discarded data (not used, kept locally and not committed)
- `topo/boutique_*_saturated_DISCARDED*`: a first Boutique run with `USERS=10`. The frontend's server container ran at 197m of its 200m CPU limit, so the whole app was slow (about 2.3 s on `loadgenerator -> frontend`) before and during the fault, and the labels (only one service faulty) did not describe what the data showed. Detected by comparing edges before and during the fault; fixed by lowering the load to `USERS=3` and re-running.

## Known limits (state these)
- Traffic is load-generated, not human and not production. Faults are delay only: no error, CPU, memory or crash faults.
- Bucketed p95: values such as 97.5 and 242.5 ms come from Istio's histogram buckets. With few requests per window, one slow request moves p95 to the next bucket.
- Online Boutique's checkout path (payment, email, shipping, checkout) gets only about 0.04 to 0.1 req/s, so p95 on those edges rests on a few samples per minute and is noisy.
- Online Boutique has no versions, so only detection and root-cause finding can be evaluated on it, not a reroute.
- The simulator was calibrated on Bookinfo, so results on simulated data and on Bookinfo are optimistic. Online Boutique was not used for calibration, which is why it is the independent real test.
- Few real topologies: Bookinfo (4 services) and Online Boutique (11 active services).
