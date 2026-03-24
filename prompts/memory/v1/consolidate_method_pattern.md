You are consolidating repeated successful experimental approaches into a canonical method pattern.

## Success Cluster

- **Observation count:** {{ cluster_size }} successful runs across {{ charter_count }} research charters
- **Representative method:** {{ method_summary }}

## Individual Observations

{% for run in runs %}
### Run {{ loop.index }} (charter: {{ run.charter_public_id }})

- **Method:** {{ run.method_description }}
- **Primary metric:** {{ run.primary_metric_name }} = {{ run.primary_metric_value }}
- **Verification outcome:** {{ run.verification_outcome }}
- **Directional signal:** {{ run.directional_signal }}
{% if run.controls %}
- **Key controls:** {{ run.controls | tojson }}
{% endif %}
{% endfor %}

{% if existing_categories %}
## Existing Pattern Categories

The following categories already exist in the knowledge base. Reuse one if this pattern fits:

{{ existing_categories | join(', ') }}
{% endif %}

## Instructions

Extract a generalizable canonical method pattern from these successful runs. The pattern should:

1. Abstract away charter-specific details to capture the reusable method knowledge
2. Identify clear trigger conditions (when should this method be considered?)
3. Describe proven actions with estimated success rates
4. Note any environmental assumptions that may affect applicability
5. Assign a hierarchical category (2-3 levels, slash-separated) — reuse an existing category if appropriate

## Output Format

Return a single JSON object:

```json
{
  "title": "Short descriptive title (under 100 chars)",
  "description": "2-3 sentence abstract of the pattern",
  "category": "method/subcategory/detail",
  "polarity": "positive",
  "trigger_conditions": ["when this method should be considered"],
  "proven_actions": [
    {"action": "the effective approach", "success_rate": 0.85, "evidence_count": 4}
  ],
  "disproven_actions": [],
  "staleness_context": {
    "framework_versions": "relevant version constraints",
    "hardware": "relevant hardware context"
  }
}
```
