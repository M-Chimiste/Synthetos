You are writing a human-readable verification summary report for an ML experiment run.

## Research Problem

{{ charter_problem }}

## Experiment

**Title:** {{ experiment_title }}
**Objective:** {{ experiment_objective }}
**Hypothesis:** {{ hypothesis_statement }}

## Run Summary

**Run ID:** {{ run_public_id }}
**Status:** {{ run_status }}
**Execution Profile:** {{ execution_profile }}
**Metrics:** {{ metrics_summary }}

## Verification Outcome

**Outcome:** {{ outcome }}
**Rationale:** {{ outcome_rationale }}

## Baseline Comparison

{{ baseline_comparison }}

## Historical Comparisons

{% for c in historical_comparisons %}
- **{{ c.metric }}**: prior={{ c.prior_value }} → current={{ c.current_value }} (delta={{ c.delta }})
{% endfor %}
{% if not historical_comparisons %}
No prior runs available for comparison.
{% endif %}

## Output Contract Checks

{{ output_contract_checks }}

{% if rerun_note %}
## Replay / Rerun Guidance

{{ rerun_note }}
{% endif %}

{% if postmortem %}
## Failure Postmortem

**Failure Class:** {{ postmortem.failure_class }}
**Stage:** {{ postmortem.failure_stage }}
**Root Cause:** {{ postmortem.root_cause_summary }}

### Remediation Suggestions
{% for s in postmortem.remediation_suggestions %}
- [{{ s.category }}] {{ s.suggestion }}
{% endfor %}
{% endif %}

## Instructions

Write a concise verification report in markdown format. Include:

1. A summary paragraph stating whether the result is robust, tentative, or rejected, and why
2. Key findings from the verification checks
3. Comparison against baseline and historical runs
4. If a postmortem exists, summarize the failure and suggested next steps
5. A recommendation for what should happen next (promote result, retry, revise protocol, or abandon)

Output the report as plain markdown text (not JSON).
