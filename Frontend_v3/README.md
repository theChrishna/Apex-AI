# MeshHeal AI dashboard (Frontend_v3)

A restyled copy of `Frontend_v2`: light card layout with a left sidebar, dark mode kept. Same pages, same read-only API, same LIVE and REPLAY behaviour. `api/meshheal_api.py` is an unchanged copy of the Frontend_v2 file; it serves this folder's `dist/`.

```bash
npm run build
```

Run from the project root. Port 8766 keeps it clear of a Frontend_v2 API on the default 8765.

```bash
.venv/bin/python Frontend_v3/api/meshheal_api.py --mode replay --speed 10 --port 8766
```

Then open http://127.0.0.1:8766. For `npm run dev`, run the API on its default port 8765: the Vite proxy points there.

## Layout and type

The visual system (tokens, type, components, motion, and how it was derived) is in [DESIGN.md](DESIGN.md).


- Pages: Home, Overview, Incidents, Evaluation, How it works, in a horizontal bar. Overview is the old Overview and Live mesh merged; `#/mesh` still opens it.
- Fonts, all bundled (no CDN): Inter for text (Regular 400, Medium 500, SemiBold 600), Inter Display for headings and big numbers (the same variable file at optical size 32, `font-variation-settings: "opsz" 32`), JetBrains Mono (variable) for code, and Tiempos Text Regular for the editorial lines (hero line, page intros).
- Tiempos Text is a licensed font and is not in this repo. The CSS lists it first and falls back to Georgia, so it appears only where it is installed. To bundle it, add the licensed files and an `@font-face` for `"Tiempos Text"` in `src/styles.css`.

## Where the Overview data comes from

| Card | Source |
| --- | --- |
| Mode, snapshot age | `/api/state` → `mode`, `status` |
| Scorer in use | `streams`: a fresh `gnn` stream decides, else `status.scorer_in_use`. Both controllers can be fresh, and the API then names whichever scored last |
| Incidents | REROUTE and ACTION_BLOCKED rows in `events`, counted per controller. The big number is the larger count, not the sum: both controllers watch the same mesh. These are decisions, not faults: an ACTION_BLOCKED is logged again every 60 s while a fault lasts |
| Risk per service | `series`: the rule score, not GNN output, which the audit files do not hold per node |
| Latency per edge | `snapshot.edges`: latest snapshot only, the API has no edge history |
| Service graph | `snapshot` (nodes, edges), `streams` and `mesh` for the controller state, the same status logic as the Services list. Entry = a service with no incoming edge |
| Incident log | `events` without fallback SCORED rows, newest 7. Status is mapped from the event type in `src/derive.ts` |
| Services | Rerouted from `mesh`, Slow and Healthy from `snapshot.nodes` |

Slow means p95 in or out of a service at 50 ms or more. That cut-off is a display choice made here (`SLOW_MS` in `src/derive.ts`), the same 50 ms as the 0.5 amber level on the service graph. It is not a control-plane setting.
