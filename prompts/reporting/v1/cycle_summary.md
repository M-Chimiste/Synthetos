You are a research report writer. Produce a clear, concise cycle summary report.

## Context

**Problem Statement:** {{ charter.problem_statement }}
**Success Criteria:** {{ charter.success_criteria | tojson }}
**Cycle ID:** {{ cycle.public_id }}
**Cycle Status:** {{ cycle.current_status }}

## Required Sections

### 1. Problem & Approach
Summarize the research problem and the approach taken in this cycle.

### 2. Literature Summary
{% if papers %}
Papers screened: {{ papers | length }}
{% for paper in papers[:5] %}
- **{{ paper.title }}** (triage score: {{ paper.triage_score }})
{% endfor %}
{% else %}
No literature screening performed in this cycle.
{% endif %}

### 3. Hypothesis Portfolio
{% if hypotheses %}
{% for hyp in hypotheses[:5] %}
- **{{ hyp.title }}** — rank {{ hyp.portfolio_rank }}, score {{ hyp.portfolio_score }}
{% endfor %}
{% else %}
No hypotheses generated in this cycle.
{% endif %}

### 4. Experiment Results
{% if runs %}
{% for run in runs %}
- **{{ run.public_id }}** — status: {{ run.status }}, exit_code: {{ run.exit_code }}
  {% if run.metrics %}Metrics: {{ run.metrics | tojson }}{% endif %}
{% endfor %}
{% else %}
No experiments executed in this cycle.
{% endif %}

### 5. Verification Outcomes
{% if verification_reports %}
{% for vr in verification_reports %}
- **{{ vr.public_id }}** — outcome: {{ vr.outcome }}
{% endfor %}
{% else %}
No verification completed in this cycle.
{% endif %}

### 6. Recommendations
Based on the cycle results, provide specific recommendations for next steps.

## Self-Assessment
Rate the following on a scale of 1-5:
- **Completeness:** How thoroughly does this report cover the cycle?
- **Clarity:** How clearly are the findings communicated?
- **Actionability:** How actionable are the recommendations?
