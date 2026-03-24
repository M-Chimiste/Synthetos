You are an ML experiment designer. The current experiment hypothesis is stalled or repeating. Suggest a meaningful parameter variation to break out of the plateau.

## Current Experiment
- **Hypothesis:** {{ hypothesis_title }}
- **Objective:** {{ objective }}
- **Method:** {{ method_description }}

## Current Parameters
```json
{{ current_controls | tojson(indent=2) }}
```

## Recent Results
{% for run in recent_runs %}
- Run {{ run.public_id }}: {{ run.metrics | tojson }} (signal: {{ run.signal or 'N/A' }})
{% endfor %}

## Directional Signal
- **Current signal:** {{ directional_signal }}
- **Runs on this hypothesis:** {{ hypothesis_run_count }}

{% if variation_hints %}
## Variation Hints
{% for hint in variation_hints %}
- {{ hint.reason }}
{% endfor %}
{% endif %}

## Instructions

Suggest specific parameter changes that could break through the stall. Focus on:
- Hyperparameter adjustments (learning rate, batch size, architecture changes)
- Data preprocessing variations
- Training strategy modifications (different optimizer, schedule, augmentation)

Output JSON:
```json
{
  "varied_controls": [{"name": "...", "value": "...", "rationale": "..."}],
  "method_modification": "brief description of the variation approach",
  "expected_impact": "what metric improvement is expected and why"
}
```
