# Shortlist Ranking

Rank the following screened papers by their relevance and value to the research problem.

## Research Problem
{{ charter_problem }}

## Screened Papers
{% for paper in papers %}
### {{ paper.title }}
- Score: {{ paper.triage_score }}
- Rationale: {{ paper.triage_rationale }}
{% endfor %}

## Instructions

Order these papers from most to least relevant. For each, provide:
- A rank number (1 = most relevant)
- A brief reason for the ranking
