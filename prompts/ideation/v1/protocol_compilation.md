You are compiling a detailed experiment protocol from an approved hypothesis and supporting evidence.

## Research Problem

{{ charter_problem }}

## Success Criteria

{% for key, value in charter_criteria.items() %}
- **{{ key }}**: {{ value }}
{% endfor %}

## Hypothesis

**Title:** {{ hypothesis.title }}

**Statement:** {{ hypothesis.statement }}

**Approach:** {{ hypothesis.approach_summary }}

## Supporting Evidence

{% for e in evidence %}
- {{ e.claim }} ({{ e.evidence_type }}, {{ e.strength }})
{% endfor %}

## Constraints

{{ constraints }}

## Instructions

Compile a complete experiment protocol. The protocol must be specific enough to execute without further clarification. Include:

1. **title**: Descriptive experiment name
2. **objective**: What this experiment aims to demonstrate
3. **baseline_description**: What the baseline/control approach is
4. **method_description**: Step-by-step method
5. **controls**: Array of control conditions `[{name, description, type}]` where type is `positive`, `negative`, or `ablation`
6. **metrics**: Array of evaluation metrics `[{name, description, direction, threshold}]` where direction is `higher_is_better` or `lower_is_better`
7. **datasets**: Array of datasets needed `[{name, source, split}]`
8. **artifacts**: Array of expected artifacts `[{name, type, required}]` where type is `model`, `plot`, `table`, `log`, `checkpoint`
9. **stop_conditions**: Array of stopping criteria `[{condition, action}]` where action is `stop` or `warn`
10. **expected_outputs**: Array of expected outputs `[{description, format}]`
11. **estimated_runtime_minutes**: Estimated wall-clock time (integer or null)
12. **gpu_required**: Whether GPU is needed (boolean)
13. **resource_requirements**: Resource needs `{gpu_memory_gb, cpu_cores, ram_gb, disk_gb}`

## Output Format

Return a single JSON object with all fields above.
