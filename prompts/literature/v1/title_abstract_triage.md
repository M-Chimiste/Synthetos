# Title and Abstract Triage

You are evaluating a research paper for relevance to a specific research problem.
Review the title and abstract together and assess the paper's potential value.

## Research Problem
{{ charter_problem }}

## Success Criteria
{{ charter_criteria }}

## Paper to Evaluate
**Title:** {{ title }}
**Abstract:** {{ abstract }}

## Instructions

Evaluate this paper's relevance to the research problem above. Consider:
1. **Direct relevance** to the problem statement and success criteria
2. **Methodological contribution** — does it propose or validate methods useful for this problem?
3. **Baseline or comparison value** — could this serve as a baseline or reference point?
4. **Recency and novelty** — does it present recent or novel findings?

Make your decision:
- **advance**: The paper is clearly relevant and worth shortlisting
- **reject**: The paper is not relevant to this research problem
- **uncertain**: Borderline relevance; keep for now but rank lower

Respond with a single JSON object:
```json
{
  "decision": "advance" | "reject" | "uncertain",
  "score": <float between 0.0 and 1.0>,
  "rationale": "<2-3 sentence explanation of your decision>"
}
```
