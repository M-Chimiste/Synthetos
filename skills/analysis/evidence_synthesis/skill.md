---
skill_id: analysis.evidence_synthesis
version: "0.1"
phase: analysis
trust_tier: first_party_trusted
allowed_operators:
  - analysis_evidence
description: Guidance for evidence synthesis, contradiction detection, and redundancy handling
---

# Evidence Synthesis Guidance

## Integrating contradictions

When two evidence claims appear to contradict each other:

1. **Verify the scope**: Are they actually about the same phenomenon?
2. **Check conditions**: Do they apply under different conditions (dataset, scale, domain)?
3. **Note the strength**: Which claim has stronger supporting evidence?
4. **Flag clearly**: Mark the contradiction with specific reasoning

## Aggregating redundancy

When multiple papers support the same finding:

1. **Group by claim**: Cluster evidence that makes the same assertion
2. **Note convergence**: Multiple independent sources increase confidence
3. **Identify the primary**: Which paper provides the strongest evidence?
4. **Track variations**: Note subtle differences in how the claim is stated

## Confidence calibration

- **High confidence (0.8-1.0)**: Clear empirical result, well-supported
- **Medium confidence (0.5-0.8)**: Plausible finding, some caveats
- **Low confidence (0.2-0.5)**: Preliminary or contested result
- **Very low (0.0-0.2)**: Speculative or contradicted by stronger evidence
