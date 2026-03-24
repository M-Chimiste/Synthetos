You are consolidating repeated signal interpretation observations into a canonical signal pattern.

## Signal Cluster

- **Observation count:** {{ cluster_size }} across {{ charter_count }} research charters

## Individual Observations

{% for obs in observations %}
### Observation {{ loop.index }} (charter: {{ obs.charter_public_id }})

- **Metric behaviour:** {{ obs.metric_summary }}
- **Directional signal assigned:** {{ obs.directional_signal }}
- **Verification outcome:** {{ obs.verification_outcome }}
- **Context:** {{ obs.context_summary }}
{% endfor %}

{% if existing_categories %}
## Existing Pattern Categories

The following categories already exist in the knowledge base. Reuse one if this pattern fits:

{{ existing_categories | join(', ') }}
{% endif %}

## Instructions

Extract a generalizable canonical signal pattern from these observations. The pattern should:

1. Describe the metric behaviour or signal that was repeatedly observed
2. Explain the correct interpretation (what this signal actually indicates)
3. Identify trigger conditions (when to expect this signal)
4. Note proven interpretation actions and any disproven (misleading) interpretations
5. Assign a hierarchical category (2-3 levels, slash-separated) — reuse an existing category if appropriate

## Output Format

Return a single JSON object:

```json
{
  "title": "Short descriptive title (under 100 chars)",
  "description": "2-3 sentence abstract of the signal pattern",
  "category": "signal/subcategory/detail",
  "polarity": "positive or negative",
  "trigger_conditions": ["when this signal pattern is expected"],
  "proven_actions": [
    {"action": "correct interpretation or response", "success_rate": 0.9, "evidence_count": 3}
  ],
  "disproven_actions": ["misleading interpretation to avoid"],
  "staleness_context": {
    "framework_versions": "relevant version constraints",
    "hardware": "relevant hardware context"
  }
}
```
