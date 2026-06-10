# Prompt Templates

Versioned system-prompt templates loaded by `libs/prompts/`. Layout:

```
prompts/<domain>/<name>/v<N>.md            # version N of prompt "<domain>.<name>"
prompts/<domain>/<name>/v<N>.<model>.md    # optional per-model variant (slugified model id)
```

The highest `v<N>.md` wins unless a version is pinned at the call site. When
`load_prompt(..., model="qwen3-6-35b")` is passed and a matching
`v<N>.qwen3-6-35b.md` exists, the variant is used — this is how prompts get
tuned per local model without code changes.

## File format

YAML frontmatter + markdown body. The body is the **system message** and is a
jinja2 template (`{{ variable }}` substitution and `{% if %}` blocks only —
no loops or macros, by convention).

```markdown
---
id: ideation.hypothesis_generate        # must match the directory path
version: 1
description: One-line purpose.
role: hypothesis_generation             # informational ModelRole hint
variables: [max_hypotheses]             # required render variables
optional_variables: []
response_schema: "libs.ideation.operators.generate:_HypothesisSet"
---
You are a ... {{ max_hypotheses }} ...
```

## Rules

- **Every structured-output prompt carries ONE compact JSON output example**
  under a heading "Output example (illustrative content — do not copy):"
  inside a ```json fence. Keep examples minimal — they're paid for on every
  call at 8–32K context windows.
- The example **must validate** against the `response_schema` model:
  `tests/unit/test_prompt_schema_sync.py` fails CI the moment a prompt
  example and its pydantic schema diverge. Change them together.
- Edits that change meaning bump the version (add `v2.md`, keep `v1.md`).
  Wording-only fixes may edit in place.
- User messages stay code-assembled (they are data-heavy and flow through
  the token budgeter in `libs/core/tokens.py`); these templates are system
  messages only.
