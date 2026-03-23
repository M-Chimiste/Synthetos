You are a research report writer. Produce a clear evidence synthesis summary.

## Context

**Cycle ID:** {{ cycle.public_id }}
**Evidence Cards:** {{ evidence | length }}

## Required Sections

### 1. Evidence Overview
Summarize the body of evidence collected during this cycle.

{% for card in evidence %}
### Evidence: {{ card.claim }}
- **Type:** {{ card.evidence_type }}
- **Strength:** {{ card.strength }}
- **Relevance:** {{ card.relevance }}
- **Source:** {{ card.source }}
- **Read Depth:** {{ card.read_depth }}
{% if card.conflicts %}
- **Conflicts:** {{ card.conflicts | tojson }}
{% endif %}
{% endfor %}

### 2. Synthesis
Identify key themes, agreements, and contradictions across the evidence.

### 3. Gaps
Identify areas where evidence is missing or weak.

### 4. Implications for Hypotheses
How does this evidence inform the hypothesis portfolio?

## Self-Assessment
Rate the following on a scale of 1-5:
- **Completeness:** How thoroughly does this report cover the evidence?
- **Clarity:** How clearly is the synthesis communicated?
- **Actionability:** How useful is this for hypothesis generation?
