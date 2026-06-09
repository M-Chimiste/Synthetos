# Goal Mode UI Evaluation Checklist

Use this checklist before merging goal-oriented research mode UI changes.

## Charter Detail

- Active goals are visible on the charter overview without hiding active cycle controls.
- The Goals tab appears alongside Overview, Cycles, Jobs, Events, and Autonomy.
- Goal status is visible as one of running, satisfied, exhausted, stopped, or failed.
- Long goal titles and long criteria names truncate or wrap cleanly at desktop widths.

## Attempts And Reports

- A user can see attempt history without opening every cycle.
- Each attempt row shows attempt number, status, cycle link, criteria pass count, and creation date.
- Each attempt links to the existing cycle timeline.
- A generated goal report can be opened and read in the Goals tab.
- Failed and exhausted states remain legible with many attempts.

## Autonomy Interaction

- Goal controls do not duplicate cycle autonomy controls.
- Stopping a goal is visually distinct from stopping an individual autonomous cycle.
- Cycle autonomy reports remain available from existing cycle surfaces.
- `goal.*` events appear in the cycle timeline under a Goals filter.

## Required Validation

- `npm run typecheck`
- `npm run build`
- Vitest coverage for empty, running, satisfied, exhausted, and report-rendering goal states.
