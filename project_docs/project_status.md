# Project status

_Last updated: 2026-04-22_

## Current focus

Frontend redesign: **Calm Console** variant from the Claude Design handoff
bundle (`Synthetos Redesign.html`) has been implemented in [apps/web/](../apps/web/).
This is the "safe" Linear/Notion-like direction — warm neutral palette, hairline
tables, pipeline rail as the hero metaphor. The "Research Notebook" and
"Flight Deck" variants from the same bundle were not implemented.

## Recently shipped

### Calm Console frontend (2026-04-22)

- **Design tokens** in [apps/web/src/styles/tokens.css](../apps/web/src/styles/tokens.css):
  oklch warm-neutral light palette, dark theme, density variants, shared
  atoms (`.chip`, `.dot`, `.btn`, `.card`, `.kbd`, `.section-label`).
- **Typography** from Google Fonts via [apps/web/index.html](../apps/web/index.html):
  Inter (UI), JetBrains Mono (IDs/metrics), Instrument Serif (reserved for
  future Notebook variant).
- **Shared UI atoms** in `apps/web/src/components/`:
  - [Icon.tsx](../apps/web/src/components/Icon.tsx) — 27 stroke icons
  - [StatusBadge.tsx](../apps/web/src/components/StatusBadge.tsx) — 5-tone status
    palette mapping (ok/accent/err/warn/slate + violet); replaces the previous
    rainbow of tailwind color classes
  - [StatusDot.tsx](../apps/web/src/components/StatusDot.tsx),
    [Sparkline.tsx](../apps/web/src/components/Sparkline.tsx)
  - [PipelineRail.tsx](../apps/web/src/components/PipelineRail.tsx) — 6-phase rail
    (Discovery → Analysis → Ideation → Protocol → Execution → Verification) plus
    `progressFromCycleStatus()` mapping the domain state machine
    (`created → discovery_ready → … → closed`) onto rail phase states.
- **Shell** — [Layout.tsx](../apps/web/src/components/Layout.tsx) rebuilt as a
  240 px sidebar with the Synthetos mark, ⌘K search affordance, icon nav,
  live "Active cycles" list, and worker/jobs heartbeat in the footer.
- **Pages rewritten** (all wired to the real API, not mock data):
  - [routes/index.tsx](../apps/web/src/routes/index.tsx) — greeting, stat cards
    with sparklines, Active cycles list with per-row pipeline rail, Recent
    jobs + Recent charters panes.
  - [routes/charters/index.tsx](../apps/web/src/routes/charters/index.tsx) —
    hairline table with per-charter pipeline rail column.
  - [routes/charters/$charterId.tsx](../apps/web/src/routes/charters/$charterId.tsx)
    — breadcrumb, hero pipeline banner for the active cycle, mini-stat grid
    (cycles / events / jobs / active jobs), tabs (overview / cycles / jobs /
    events / autonomy). `AutonomyPanel` is rendered inside the autonomy tab.
  - [routes/charters/new.tsx](../apps/web/src/routes/charters/new.tsx),
    [routes/patterns/index.tsx](../apps/web/src/routes/patterns/index.tsx),
    [routes/events.tsx](../apps/web/src/routes/events.tsx),
    [routes/skills.tsx](../apps/web/src/routes/skills.tsx).
  - [EventStream.tsx](../apps/web/src/components/EventStream.tsx) — reskinned
    from the old dark terminal look to the calm panel styling.

### Out of scope for the redesign pass

The following routes still use the pre-redesign Tailwind styling and will need
a follow-up pass before the UI is fully consistent:

- [routes/charters/$charterId/discovery/](../apps/web/src/routes/charters/$charterId/discovery/)
  (discovery session pages)
- [routes/cycles/$cycleId/](../apps/web/src/routes/cycles/$cycleId/)
- [routes/analysis/](../apps/web/src/routes/analysis/)
- [routes/experiment/](../apps/web/src/routes/experiment/)
- [routes/patterns/$patternId.tsx](../apps/web/src/routes/patterns/$patternId.tsx)
- [components/AutonomyPanel.tsx](../apps/web/src/components/AutonomyPanel.tsx)

## Build status

- `cd apps/web && npm run build` — passes (tsc + vite).
- `cd apps/web && npm run lint` — **broken**, pre-existing: ESLint v9 expects
  `eslint.config.js` but the repo still has the old flat-config style (or
  none). Not caused by the redesign; should be fixed separately.

## Verification notes

- The redesign was shipped code-complete but **not visually verified in a
  browser**. Running `cd apps/web && npm run dev` (with the API on
  `localhost:8000`) is required to confirm layout, spacing, and data wiring.
- No backend code changed in this pass; existing API contracts are preserved.

## Next steps

1. Browser-verify the Calm Console against the design file across all five
   primary pages (dashboard, charters list, charter detail, patterns, events,
   skills).
2. Port the remaining routes listed above to the calm tokens so the UI is
   consistent end-to-end.
3. Decide whether to implement the Notebook or Flight Deck variants, or close
   them out (chat transcript suggests the user may want to keep Calm as the
   shell and sprinkle in Notebook/Flight treatments for specific surfaces).
4. Restore `npm run lint` (ESLint v9 flat config).
