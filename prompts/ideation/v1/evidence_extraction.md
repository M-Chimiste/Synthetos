You are extracting structured research evidence from a paper for the following research problem.

## Research Problem

{{ charter_problem }}

## Success Criteria

{% for key, value in charter_criteria.items() %}
- **{{ key }}**: {{ value }}
{% endfor %}

## Paper

**Title:** {{ title }}

**Abstract:** {{ abstract }}

{% if fulltext_excerpt %}
**Full-text excerpt (first section):**
{{ fulltext_excerpt }}
{% endif %}

## Instructions

Extract all relevant evidence claims from this paper. For each claim, provide:

1. **claim**: A concise statement of the finding, method, metric, baseline, limitation, or dataset described
2. **evidence_type**: One of `finding`, `method`, `metric`, `baseline`, `limitation`, `dataset`
3. **strength**: One of `strong` (well-supported, replicated), `moderate` (reasonable but limited), `weak` (preliminary or indirect), `anecdotal` (single mention, no support)
4. **relevance_score**: Float 0.0–1.0 indicating relevance to the research problem
5. **relevance_rationale**: Brief explanation of why this evidence matters for the problem
6. **source_section**: Which part of the paper this came from (e.g., `abstract`, `methods`, `results`, `introduction`) or null
7. **source_quote**: A direct quote if available, or null

Focus on evidence that is directly relevant to the research problem. Ignore tangential claims.

## Output Format

Return a JSON array of evidence objects:

```json
[
  {
    "claim": "...",
    "evidence_type": "finding",
    "strength": "strong",
    "relevance_score": 0.85,
    "relevance_rationale": "...",
    "source_section": "results",
    "source_quote": "..."
  }
]
```
