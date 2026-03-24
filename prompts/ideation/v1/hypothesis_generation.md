You are generating candidate research hypotheses based on extracted evidence.

## Research Problem

{{ charter_problem }}

## Success Criteria

{% for key, value in charter_criteria.items() %}
- **{{ key }}**: {{ value }}
{% endfor %}

## Extracted Evidence

{% for e in evidence_summary %}
- **[{{ e.public_id }}]** {{ e.claim }} (type: {{ e.evidence_type }}, strength: {{ e.strength }}, relevance: {{ e.relevance_score }})
{% endfor %}

{% if method_hints %}
## Canonical Method Patterns (from prior research)

These methods have proven effective in similar research contexts:

{% for hint in method_hints %}
- **{{ hint.title }}**: {{ hint.description }}
{% if hint.proven_actions %}  Proven actions: {% for a in hint.proven_actions %}{{ a.action }}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
{% endfor %}
{% endif %}

{% if failure_warnings %}
## Canonical Failure Warnings (from prior research)

These approaches have consistently failed in similar contexts — avoid them or explicitly justify diverging:

{% for warn in failure_warnings %}
- **{{ warn.title }}**: {{ warn.description }}
{% if warn.disproven_actions %}  Disproven approaches: {% for a in warn.disproven_actions %}{{ a }}{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
{% endfor %}
{% endif %}

## Instructions

Generate exactly {{ num_hypotheses }} candidate research hypotheses. Each hypothesis should:

1. Be grounded in the evidence above — cite specific evidence IDs
2. Propose a testable approach to the research problem
3. Be distinct from the other hypotheses (explore different angles)
4. Consider both supporting and counter-evidence

For each hypothesis, provide:

- **title**: A concise name (under 100 chars)
- **statement**: The full hypothesis statement
- **rationale**: Why this hypothesis is worth testing, citing evidence
- **approach_summary**: A sketch of how you would test this hypothesis
- **supporting_evidence_ids**: List of evidence public_ids that support it
- **counter_evidence_ids**: List of evidence public_ids that argue against it

## Output Format

Return a JSON array:

```json
[
  {
    "title": "...",
    "statement": "...",
    "rationale": "...",
    "approach_summary": "...",
    "supporting_evidence_ids": ["evidence_xxx", "evidence_yyy"],
    "counter_evidence_ids": ["evidence_zzz"]
  }
]
```
