# MeshHeal design system

The visual language of the MeshHeal dashboard (`Frontend_v3`). It adapts the *design principles* of two public pages, studied on 2026-10-31: attio.com (light theme, marketing) and attio.com/platform/developers (dark theme, developer platform). Nothing was copied: no code, copy, images, icons, illustrations or font files. Colours, sizes and timings below are measured design values, re-expressed under our own token names. Fonts are free (SIL OFL) and bundled from npm.

How this file was produced: computed styles, CSS custom properties, keyframes, transitions and running animations were read from both live pages in the browser. Where something could not be read (for example, the script that triggers a reveal), it is marked **inferred**. Where a value was cut off in my read, it is marked **approximated**.

## 1. What the source does, and what we keep

| Pattern seen on the source | Kept for a data-dense dashboard? |
| --- | --- |
| Neutral-first palette: cool grey ladders, one blue accent, colour used only for state | Yes |
| Hairline (1 px) borders instead of heavy fills or shadows; dark mode is flat | Yes |
| Tight display type: Inter Display 500/600, negative tracking, 1.05 to 1.1 line-height | Yes, scaled down |
| Small uppercase **bracketed labels** `[ DEVELOPER PLATFORM ]` and **numbered lists** `[ 01 ]` | Yes: panel headers |
| Blueprint grid: hairline cells with small dots at the intersections | Optional, only on the hero metric |
| One large hero statement, then dense cells | Yes: one hero metric |
| Scroll-reveal sections, parallax-free but scripted per section | **No.** No scroll-driven effects. |
| Large illustrated loops (radar, workflow, roller) | No. Only the ring-pulse idea survives (section 8) |
| Body copy at weight 500 | Adapted: UI text 500, prose 400 |

## 2. Colour

Two cool-grey ladders (`ink` = the dark scale, `paper` = the light scale), one accent hue, and three status hues. Hex values are the sRGB conversion of the source's CIE-Lab tokens.

### Ladders

| Token | Hex | Use |
| --- | --- | --- |
| `ink-0` | `#000000` | Announcement strip only |
| `ink-50` | `#101010` | Dark page background |
| `ink-100` | `#1c1d1f` | Dark surface; light-theme primary text |
| `ink-200` | `#202124` | Dark raised surface |
| `ink-300` | `#232529` | Dark weak stroke, chart grid |
| `ink-400` | `#2e3238` | Dark default hairline, button fill |
| `ink-500` | `#383e47` | Dark hover fill, chart axis |
| `ink-600` | `#505967` | Light-theme muted text; dark-theme dim numerals `[ 01 ]` |
| `ink-700` | `#6f7988` | Disabled foreground, strong stroke |
| `ink-800` | `#8f99a8` | Dark muted text, bracketed labels |
| `ink-900` | `#a4adba` | Dark secondary text |
| `paper-100` | `#ffffff` | Light page and card surface; dark primary text |
| `paper-200` | `#fafafb` | Light section tint |
| `paper-300` | `#f3f4f6` | Light sunken surface |
| `paper-400` | `#edeff3` | Light hover fill, border |
| `paper-500` | `#e4e7ec` | Light default hairline |
| `paper-600` | `#dee2e7` | Light strong hairline |
| `paper-700` | `#d3d8df` | Light chart axis |
| `paper-800` | `#cad0d9` | Light hover border |
| `paper-900` | `#b5bdc9` | Disabled |

### Accent and status

| Token | Hex | Use |
| --- | --- | --- |
| `blue-100` | `#e8f0ff` | Accent wash (light) |
| `blue-200` | `#c8dcff` | Accent border (light) |
| `blue-400` | `#709ff5` | Accent on dark; link; focus ring (60 % mix) |
| `blue-450` | `#538bf3` | Hover on dark |
| `blue-500` | `#266df0` | Accent on light |
| `blue-600` | `#245bc2` | Accent pressed |
| `blue-800` | `#1a2233` | Accent wash (dark) |
| `green-500` | `#0fc27b` | Healthy dot and fill |
| `yellow-500` | `#f5b900` | Slow / warning dot and fill |
| `red-500` | `#ff5b59` | Critical dot and fill |

Status colour rule (ours): hue means state, never decoration. Status **text** on a light surface uses a darker derived step for contrast (not observed on the source): healthy `#0b7a52`, warning `#8a5a00`, critical `#c0263f`. Dark theme uses the 500 steps for text.

### Semantic roles (what the CSS actually uses)

| Role | Light | Dark |
| --- | --- | --- |
| `--bg` | `paper-200` (the source's section tint; cards stay `paper-100`) | `ink-50` |
| `--surface` | `paper-100` | `ink-100` |
| `--surface-2` | `paper-300` | `ink-200` |
| `--text` | `ink-100` | `paper-100` |
| `--muted` | `ink-600` | `ink-800` |
| `--border` | `paper-500` | `ink-400` |
| `--grid` | `paper-400` | `ink-300` |
| `--axis` | `paper-700` | `ink-500` |
| `--accent` | `blue-500` | `blue-400` |
| `--accent-soft` | `blue-100` | `blue-800` |
| `--faint` (index numerals, decoration only) | `ink-700` | `ink-700` |
| `--btn-bg` / `--btn-bg-hover` / `--btn-text` | `ink-200` / `ink-400` / `paper-100` | `ink-400` / `ink-500` / `paper-400` |

Chart series colours (`--series-1..4`) are not from the source. They keep the colour-blind-validated set chosen earlier so four services stay distinguishable.

## 3. Typography

| Face | Source uses | We use (free) | Where |
| --- | --- | --- | --- |
| Inter | UI and body, weight 500 | Inter Variable, `@fontsource-variable/inter` (OFL) | Text, controls, tables |
| Inter Display | Headings, labels, weights 500/600 | The same variable file at `opsz 32` | Headings, big numbers, bracketed labels |
| JetBrains Mono | Code, stat captions | JetBrains Mono Variable (OFL) | Code, timestamps, numerals in tables |
| Editorial serif | not used by the source | Tiempos Text if installed, else Georgia (your earlier choice) | Hero line and page intros only |

### Scale (measured on the source) and our adaptation

| Step | Source size / line / weight / tracking | Dashboard |
| --- | --- | --- |
| Display XL | 72 / 72 / 600 / -0.024em | Not used |
| Hero | 64 / 60.8 / 600 / -0.02em (home); 56 / 60 / 600 / -0.015em (developers) | Landing page only |
| Heading MD | 40 / 44 / 500 / -0.01em | Landing sections |
| Heading XS | 28 / 34 / 600 / -0.01em | Page title |
| Title | 24 / 27.6 / 500 / -0.01em | Hero metric label |
| Lead | 18 / 24 / 500 / -0.01em | Landing lead |
| Base | 16 / 22 / 500 / -0.01em | Prose |
| **Small (UI)** | 14 / 20 / 500 / -0.005em | **Dashboard default** |
| **XS** | 12 / 18 / 500 / 0 | Table cells, notes |
| **Label** | 12 / 14 / 600 / +0.06em, uppercase, Inter Display | Panel headers |
| **Hero metric** | not on the source | 56 / 56 / 600 / -0.03em, Inter Display |

Weights: 400 prose, 500 UI, 600 headings and labels. Nothing bolder.

## 4. Spacing, layout, radii

- Base unit **4 px** (the source sets `--spacing: .25rem`). Scale: 4, 8, 12, 16, 20, 24, 32, 40, 56.
- Container: source max 1440 px with 24 px gutters. Dashboard: **1200 px**, 24 px gutters (16 px below 900 px).
- Control height **36 px**, horizontal padding **12 px**.
- Panel gap 16 px, panel padding 20 px. Table row padding 9 px vertical.
- Hairline grid (source: developers page): 1 px cells with ~4 px dots at the intersections. Optional here.

| Radius token | Value | Use |
| --- | --- | --- |
| `r-xs` | 4 px | Inline tags |
| `r-sm` | 8 px | Small controls, table header ends |
| `r-control` | 10 px | Buttons, inputs, chips (source: all 36 px buttons) |
| `r-card` | 12 px | Cards, panels |
| `r-panel` | 16 px | Hero metric, canvas |
| `r-pill` | 9999 px | Badges, dots |

## 5. Borders and shadows

- **Borders**: always 1 px solid. Dark: `ink-400` default, `ink-300` weak, `ink-700` strong. Light: `paper-500` (source also uses `rgba(0,0,0,.05)` and `.06` on cards).
- **Dark is flat.** No shadows on cards.
- **Light shadows** (source values, **approximated** where cut off):
  - card: `0 0 0 1px rgba(0,22,62,.01), 0 4px 12px -1px rgba(0,22,62,.04), 0 1px 2px rgba(0,22,62,.18)`
  - small card: `0 1px 3px rgba(0,0,0,.04), 0 0 2px rgba(28,40,64,.18)`
  - primary button: `inset .2px .2px 2px rgba(255,255,255,.1), 0 1.5px 1.5px rgba(0,0,0,.25)`
- Ours (light): cards use the small-card shadow plus the hairline; popovers use the card shadow.
- **Focus ring**: `0 0 0 2px bg, 0 0 0 4px color-mix(in oklab, blue-400 60%, transparent)`.

## 6. Components

| Component | Spec |
| --- | --- |
| Primary button | 36 px, r-control, fill `ink-400` (dark) or `ink-100` (light), 1 px `ink-600` @ 50 % border, text 14/500, no shadow on dark |
| Outline button | transparent, 1 px `--border`, text `--text`, hover fill `--surface-2` |
| Chip / badge | pill, 12/600, state hue at 12 % fill, text in the state's text colour, never colour alone (icon or label) |
| Nav | one sticky bar, 52 px, hairline bottom, 15/500 text links, active = text colour plus 2 px accent underline |
| Card | `--surface`, 1 px `--border`, r-card, padding 20, no heavy shadow |
| Table | 12/500 cells, header row 11/600 uppercase muted on `--surface-2`, 1 px row hairlines, numerals tabular in mono |
| Panel header | the bracketed, numbered pattern in section 7 |

## 7. Panel headers: bracketed labels and numbered lists

Adapted from `[ DEVELOPER PLATFORM ]` and the `[ 01 ]`, `[ 02 ]` cells.

```
[ 01 ]  [ SERVICE GRAPH ]
```

- Index `[ 01 ]`: 12/14, Inter Display 600, +0.06em, `--faint` (`ink-700` in both themes; `ink-600` on the dark surface was only 2.2:1). Numbering is a CSS counter per page, so reordering panels renumbers them and no data code is involved.
- Title: the panel's `<h2>`, same type, uppercase, `--muted`; the brackets are `::before`/`::after`, so the text content stays intact.
- One **hero metric** per page, set at 56 px in its own panel; the other stats become compact cells. On Overview it is the **highest rule risk** in the latest snapshot (the same values the graph cards show), with a bar and a tick at the 0.85 action threshold. It is the only number computed for display; `api.ts` and `derive.ts` are untouched.

## 8. Motion

### Tokens

| Token | Value | Source |
| --- | --- | --- |
| `--ease-standard` | `cubic-bezier(.2, 0, 0, 1)` | the source's `ease-in-out` and `emphasized` |
| `--ease-out` | `cubic-bezier(.33, 1, .68, 1)` | out-cubic; 84 elements |
| `--ease-reveal` | `cubic-bezier(0, 0, .58, 1)` | the source's reveal ease |
| `--ease-hero` | `cubic-bezier(.23, 1, .32, 1)` | hero rise |
| `--ease-link` | `cubic-bezier(.65, 0, .35, 1)` | underline growth |
| `--dur-instant` | 50 ms | nav item colour |
| `--dur-fast` | 150 ms | text colour |
| `--dur-base` | 200 ms | hover fill, border |
| `--dur-slow` | 300 ms | buttons |
| `--dur-reveal` | 600 ms | entrances |

### What the source animates, and what triggers it

| Effect | Timing | Trigger |
| --- | --- | --- |
| Colour / background / border on controls | 0.2 s `ease-out` (cards, links), 0.3 s `standard` (buttons), 0.05 s on nav items | `:hover`, `:focus-visible` (observed) |
| Link underline | `background-size` 0.4 s `link` | hover (**inferred** from the property) |
| Dropdown items | `opacity, translate` 0.05 s `standard` | menu open (**inferred**) |
| Hero rise | 0.9 s `hero`; from opacity 0, blur 6 px, translateY 16 px; staggered by a delay variable; a reduced-motion variant fades only | page load (observed in CSS) |
| Section reveals | 600/750/900 ms `reveal`, plus 595 to 680 ms `out` | start at load or on entering view, run by script (**inferred**; the script is not readable) |
| Radar ring pulse | border colour mixes 32 % blue, then back, within the first 26 % of a cycle | each sweep of the loop |
| Radar blip | scale 0.4 → 2.2 → 1, then fade out at the end of the cycle | each sweep |
| Ambient loops | rings 3.6 s, bob 3.8 to 4.85 s, roller 24 s, shimmer 1.8 s, spin 1 s, all `linear` or `ease-in-out`, infinite | always on |
| Workflow status | chip slides 28 px up and fades; border draws by stroke offset | scripted cycle (**inferred**) |

Findings: **no scroll-driven CSS** (zero rules use `animation-timeline`); a `prefers-reduced-motion` branch exists; motion on the developers page is mostly canvas and script.

### What we use: two signature animations, nothing else

1. **Rise-in.** Panels fade in with a small upward move and blur-off: `opacity 0 → 1`, `translateY(12px → 0)`, `blur(6px → 0)`, 600 ms, `--ease-reveal`, staggered 50 ms per panel (capped at the eighth). `animation-fill-mode: backwards`, so no filter is left on the element afterwards. Trigger: first render of a page only (load or route change). Never on scroll. Reduced motion: none.
2. **Status ring pulse.** A soft ring radiates from a state dot: `box-shadow` spread 0 → 8 px while its opacity goes 0.35 → 0, 3.6 s `--ease-out`, infinite. Trigger: state, not time. It runs only on the LIVE or REPLAY chip dot and on a graph node chip that is Rerouted or at the action threshold, and only while `/api/state` reports a controller scoring. Reduced motion: none. The 0 to 8 px ring is spent in the first 30 % of each 3.6 s cycle and then rests.

Everything else is a plain hover or focus transition (section 6). No parallax, no scroll-linked effects, no looping illustrations: the Home hero illustration is static (it shows the final frame, traffic moved to reviews v1).

Under `prefers-reduced-motion: reduce`, `*`, `::before` and `::after` all get `animation: none` and `transition: none`. The pseudo-element selectors matter: the pulse lives on `::before`, and a bare `*` does not match it.

## 9. Rules

- Colour carries state only. Decoration is neutral.
- One accent. Status hues never double as series colours.
- Every state chip has an icon or a label next to the colour.
- Data first: no change to data logic, API calls, derived values or caveat text for visual reasons.
- Prose at weight 400, UI at 500, headings and labels at 600.

## 10. Layers, checks and status

| Layer | Scope | Check after the layer |
| --- | --- | --- |
| 1. Tokens | CSS variables only: colours, fonts, radii, shadows, motion tokens. No rule changes | `npm run build`; all pages load, no console errors, no horizontal overflow, light and dark |
| 2. Components | Cards, nav, tables, buttons, panel headers, hero metric | Same checks; screenshot comparison; text of every data value unchanged |
| 3. Motion | The two signature animations | Same checks; animations start once, stop under reduced motion, no scroll listeners |

`src/api.ts`, `src/derive.ts` and the facts script must be byte-identical before and after.

### Status (2026-10-31)

All three layers are built and were checked by script in a real browser (headless Chrome against the REPLAY API), light, dark and mobile:

- **Layer 1, tokens**: 12 page loads, 0 console errors, 0 horizontal overflow, variable fonts loaded; text fingerprints stable across themes.
- **Layer 2, components**: text fingerprints equal to Layer 1 once case and the new hero panel are neutralised (the headings became uppercase and innerText reflects that); 0 errors, 0 overflow.
- **Layer 3, motion**: 11 of 11 checks: only the two animations exist, rise-in runs once at 600 ms with the reveal ease and staggered delays, nothing starts on scroll, reduced motion leaves 0 running animations, the pulse stops when no controller runs, and a rerouted node chip pulses in the fault window. The audit found and fixed two real defects: a reduced-motion rule broken by a bad edit, and a `*` selector that missed the pulse on `::before`.
- `src/api.ts`, `src/derive.ts` and `scripts/extract-facts.mjs` are byte-identical to before the restyle.

Not verified: LIVE mode with a running controller, browsers other than Chrome, and `npm run dev`.
