You are a research report writer. Produce a clear run summary report for an experiment execution.

## Context

**Run ID:** {{ run.public_id }}
**Experiment Spec:** {{ spec.objective }}
**Profile:** {{ run.execution_profile }}
**Status:** {{ run.status }}
**Exit Code:** {{ run.exit_code }}
**Duration:** {{ run.started_at }} to {{ run.completed_at }}

## Required Sections

### 1. Experiment Setup
Describe the experiment configuration, dataset, and methodology.
- Baseline: {{ spec.baseline | default('Not specified') }}
- Method: {{ spec.method | default('Not specified') }}
- Metrics: {{ spec.declared_metrics | tojson }}

### 2. Execution Summary
Summarize what happened during execution.
{% if run.failure_classification %}
- **Failure Classification:** {{ run.failure_classification }}
- **Error:** {{ run.last_error }}
{% else %}
- Execution completed successfully.
{% endif %}

### 3. Results
{% if run.metrics %}
{{ run.metrics | tojson }}
{% else %}
No metrics produced.
{% endif %}

### 4. Artifacts
{% if run.artifact_manifest %}
{% for key, path in run.artifact_manifest.items() %}
- {{ key }}: {{ path }}
{% endfor %}
{% else %}
No artifacts collected.
{% endif %}

### 5. Assessment
Provide a brief assessment of the run quality and results.

## Self-Assessment
Rate the following on a scale of 1-5:
- **Completeness:** How thoroughly does this report cover the run?
- **Clarity:** How clearly are the findings communicated?
- **Actionability:** How actionable are the conclusions?
