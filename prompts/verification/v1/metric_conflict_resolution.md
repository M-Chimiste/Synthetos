You are evaluating a multi-metric tradeoff in an ML experiment. The primary metric is improving, but one or more constraint metrics are moving in the wrong direction.

## Research Problem

{{ charter_problem }}

## Experiment

**Title:** {{ experiment_title }}

## Primary Metric

- **{{ primary_metric }}**: {{ primary_value }} (signal: {{ primary_signal }})
{% if primary_higher_is_better %}  Higher is better.{% else %}  Lower is better.{% endif %}

## Conflicting Constraint Metrics

{% for c in conflicts %}
- **{{ c.metric }}**: {{ c.value }} (signal: {{ c.signal }})
{% if c.get("upper_bound") is not none %}  Upper bound: {{ c.upper_bound }}{% endif %}
{% if c.get("lower_bound") is not none %}  Lower bound: {{ c.lower_bound }}{% endif %}
{% endfor %}

## Recent Metric History

{% for metric_name, series in metric_histories.items() %}
**{{ metric_name }}:** {% for point in series[-5:] %}{{ point.value }}{% if not loop.last %} → {% endif %}{% endfor %}
{% endfor %}

## Task

Decide whether the tradeoff between the improving primary metric and the regressing constraint metric(s) is acceptable. Consider:

1. How large is the regression in the constraint metric(s)?
2. Does the primary metric improvement justify the constraint regression?
3. Is there a path to improving both, or is this a fundamental tradeoff?

Respond with JSON only:

```json
{
  "resolution": "accept_tradeoff | reject_tradeoff | needs_investigation",
  "rationale": "Explain your reasoning in 2-3 sentences",
  "recommendation": "Specific next step suggestion"
}
```

- `accept_tradeoff`: The primary improvement justifies the constraint regression. Continue this approach.
- `reject_tradeoff`: The constraint regression is too severe. Pivot or revise the approach.
- `needs_investigation`: The tradeoff is ambiguous. Run more experiments to understand the relationship.
