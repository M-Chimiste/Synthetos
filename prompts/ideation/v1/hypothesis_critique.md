You are critiquing a research hypothesis for novelty, feasibility, and potential impact.

## Research Problem

{{ charter_problem }}

## Hypothesis

**Title:** {{ hypothesis_title }}

**Statement:** {{ statement }}

**Rationale:** {{ rationale }}

**Proposed Approach:** {{ approach_summary }}

## Supporting Evidence

{% for e in supporting_evidence %}
- {{ e.claim }} ({{ e.evidence_type }}, {{ e.strength }})
{% endfor %}

## Counter Evidence

{% for e in counter_evidence %}
- {{ e.claim }} ({{ e.evidence_type }}, {{ e.strength }})
{% endfor %}

## Instructions

Evaluate this hypothesis on three dimensions (each scored 0.0–1.0):

1. **novelty_score**: How novel is this approach relative to existing work? (0 = well-trodden, 1 = highly original)
2. **feasibility_score**: How feasible is this to implement and test? (0 = impossible, 1 = straightforward)
3. **impact_score**: If successful, how impactful would the results be? (0 = marginal, 1 = transformative)

Also provide:
- **critique_summary**: 2-3 sentence assessment of strengths and weaknesses
- **issues**: Array of specific concerns, each with `issue` (description) and `severity` (one of `blocking`, `warning`, `note`)

## Output Format

```json
{
  "novelty_score": 0.7,
  "feasibility_score": 0.8,
  "impact_score": 0.6,
  "critique_summary": "...",
  "issues": [
    {"issue": "...", "severity": "warning"}
  ]
}
```
