# Skills

Synthetos skills are optional capability packages that augment operator prompts.

## Layout

- `literature/` powers discovery and analysis guidance.
- `ideation/` biases hypothesis generation and experiment planning.
- `coding/` constrains experiment code generation and runtime outputs.
- `verification/` shapes evaluation and postmortem review.
- `analysis/` supports Phase 2 paper-structure extraction and synthesis.

Each skill is a `skill.md` package with front matter describing:

- `id`
- `allowed_operators`
- `preferred_models`
- `context_inputs`
- `outputs`
- `capabilities`
- `risk_level`
- `trust_tier_required`

## Runtime Gate

Capabilities such as `fs.write`, `network.access`, `run.control`, and
`python.hooks` are treated as elevated. Third-party untrusted skills cannot
declare them. Validation happens through
[/Users/c/software_projects/Synthetos/libs/skills/validator.py](/Users/c/software_projects/Synthetos/libs/skills/validator.py).

## Examples

- Low-risk catalog example:
  [skills/example/skill.md](/Users/c/software_projects/Synthetos/skills/example/skill.md)
- Elevated-capability example with a runtime gate:
  [skills/examples/elevated_capability/skill.md](/Users/c/software_projects/Synthetos/skills/examples/elevated_capability/skill.md)
