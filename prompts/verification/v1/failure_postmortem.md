You are generating a structured failure postmortem for an ML experiment run that failed or was rejected during verification.

## Research Problem

{{ charter_problem }}

## Experiment

**Title:** {{ experiment_title }}
**Objective:** {{ experiment_objective }}
**Method:** {{ method_description }}

## Run Details

**Status:** {{ run_status }}
**Failure Classification:** {{ failure_classification }}
**Failure Stage:** {{ failure_stage }}
**Exit Code:** {{ exit_code }}
**Last Error:** {{ last_error }}

## Stderr Excerpt

```
{{ stderr_excerpt }}
```

## Verification Results (if available)

{{ verification_summary }}

## Similar Prior Failures

{% for pm in similar_prior_failures %}
- **{{ pm.failure_class }}**: {{ pm.root_cause_summary }}
{% endfor %}
{% if not similar_prior_failures %}
No similar prior failures found.
{% endif %}

## Instructions

Analyze this failure and produce a structured postmortem with:

1. **root_cause_summary**: 2-3 sentence description of the most likely root cause
2. **contributing_factors**: List of factors that contributed, each with `factor` (description), `evidence` (what pointed to this), and `severity` (critical/major/minor)
3. **remediation_suggestions**: List of actions to fix, each with `suggestion` (what to do), `category` (code_fix/config_change/data_issue/resource_limit/protocol_revision), and `actionable` (true/false)
4. **retrieval_hints**: Literature search queries that might help address this failure, each with `query` and `rationale`
5. **protocol_update_hints**: Suggestions for changing the experiment spec, each with `field` (which spec field) and `suggestion` (what to change)

## Output Format

```json
{
  "root_cause_summary": "...",
  "contributing_factors": [
    {"factor": "...", "evidence": "...", "severity": "critical"}
  ],
  "remediation_suggestions": [
    {"suggestion": "...", "category": "code_fix", "actionable": true}
  ],
  "retrieval_hints": [
    {"query": "...", "rationale": "..."}
  ],
  "protocol_update_hints": [
    {"field": "...", "suggestion": "..."}
  ]
}
```
