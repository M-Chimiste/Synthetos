You are consolidating repeated failure observations into a canonical failure pattern.

## Failure Cluster

- **Failure class:** {{ failure_class }}
- **Observation count:** {{ cluster_size }} across {{ charter_count }} research charters

## Individual Observations

{% for pm in postmortems %}
### Observation {{ loop.index }} (charter: {{ pm.charter_public_id }})

- **Root cause:** {{ pm.root_cause_summary }}
- **Contributing factors:** {{ pm.contributing_factors | join(', ') }}
- **Remediation suggestions:** {{ pm.remediation_suggestions | join(', ') }}
- **Failure stage:** {{ pm.failure_stage }}
{% endfor %}

{% if existing_categories %}
## Existing Pattern Categories

The following categories already exist in the knowledge base. Reuse one if this pattern fits:

{{ existing_categories | join(', ') }}
{% endif %}

## Instructions

Extract a generalizable canonical failure pattern from these observations. The pattern should:

1. Abstract away charter-specific details to capture the reusable failure knowledge
2. Identify clear trigger conditions that predict when this failure will occur
3. Distinguish proven remediation actions (what worked) from disproven ones (what didn't)
4. Note any environmental assumptions (framework versions, hardware, etc.) that may affect applicability
5. Assign a hierarchical category (2-3 levels, slash-separated) — reuse an existing category if appropriate

## Output Format

Return a single JSON object:

```json
{
  "title": "Short descriptive title (under 100 chars)",
  "description": "2-3 sentence abstract of the pattern",
  "category": "failure/subcategory/detail",
  "polarity": "negative",
  "trigger_conditions": ["condition that predicts this failure"],
  "proven_actions": [
    {"action": "what worked", "success_rate": 0.8, "evidence_count": 3}
  ],
  "disproven_actions": ["what did not work"],
  "staleness_context": {
    "framework_versions": "relevant version constraints",
    "hardware": "relevant hardware context"
  }
}
```
