You are debugging a failed ML experiment run. The failure has been classified as **{{ failure_classification }}**.

Your job is to diagnose the root cause and produce a targeted fix. Be specific and concise.

## Research Problem

{{ charter_problem }}

## Experiment

**Title:** {{ experiment_title }}
**Method:** {{ method_description }}

## Failure Details

- **Classification:** {{ failure_classification }}
- **Exit Code:** {{ exit_code }}
- **Last Error:** {{ last_error }}

## Stderr (last {{ max_stderr_chars }} chars)

```
{{ stderr_excerpt }}
```

## Generated Code

```python
{{ generated_code }}
```

{% if prior_attempts %}
## Prior Remediation Attempts (this is attempt {{ attempt_number }})

The following fixes were already tried and DID NOT resolve the issue. You MUST try a different approach.

{% for attempt in prior_attempts %}
### Attempt {{ attempt.attempt_number }}
- **Diagnosis:** {{ attempt.diagnosis }}
- **Fix type:** {{ attempt.fix_type }}
- **Fix applied:** {{ attempt.fix_description }}
- **Outcome:** {{ attempt.outcome }}
{% endfor %}
{% endif %}

{% if canonical_fix_hints %}
## Known Canonical Patterns for This Failure Type

These patterns have been learned from prior research runs across different projects:

{% for hint in canonical_fix_hints %}
- **{{ hint.title }}**: {{ hint.description }}
  - Proven fixes: {{ hint.proven_actions | join(', ') }}
{% if hint.disproven_actions %}  - Approaches that did NOT work: {{ hint.disproven_actions | join(', ') }}{% endif %}
{% endfor %}

Consider applying these known fixes first before attempting a novel diagnosis.
{% endif %}

## Instructions

{% if failure_classification == "dependency_failure" %}
The run failed due to a missing or incompatible Python dependency. Identify which package is missing from the stderr, determine the correct version (considering CUDA compatibility, framework versions, etc.), and provide the fix. Do not blindly install — check what the code actually needs.
{% elif failure_classification == "runtime_exception" %}
The run failed with a runtime error. Read the stack trace carefully, identify the root cause (shape mismatch, type error, index out of range, etc.), and produce a minimal code patch that fixes the issue without changing the experiment's intent.
{% elif failure_classification == "metric_parse_failure" %}
The run completed but metrics could not be parsed. Check how the code writes metrics output and ensure it matches the expected JSON format: `{"metric_name": numeric_value, ...}` written to the metrics output path.
{% elif failure_classification == "invalid_artifact_output" %}
The run completed but required artifacts were not produced. Check the output paths and file-writing logic. Ensure the code writes `artifact_manifest.json` with the correct structure.
{% else %}
Analyze the failure evidence and produce a targeted fix.
{% endif %}

If you need to change runtime settings, use `run_mutations` only with these keys:
- `execution_profile`
- `timeout_seconds`
- `memory_limit_mb`
- `cpu_limit`
- `gpu_enabled`

Use `spec_mutations` only for experiment-spec fields that need the run harness restaged into `run_config.json`.

Respond with a single JSON object:

```json
{
  "diagnosis": "2-3 sentence root cause analysis",
  "fix_type": "code_patch | dependency_add | env_change | spec_mutation",
  "fix_description": "What this fix does in one sentence",
  "code_patch": "Full corrected Python code to replace the run script. Only include if fix_type is code_patch. Otherwise null.",
  "dependency_adds": ["package==version"],
  "env_changes": {"KEY": "value"},
  "run_mutations": {"timeout_seconds": 900},
  "spec_mutations": {"field_name": "new_value"}
}
```
