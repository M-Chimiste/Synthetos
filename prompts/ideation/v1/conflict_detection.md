Compare the following two evidence claims and determine if they conflict or are redundant.

## Evidence A

{{ evidence_a.claim }}
- Type: {{ evidence_a.evidence_type }}
- Strength: {{ evidence_a.strength }}

## Evidence B

{{ evidence_b.claim }}
- Type: {{ evidence_b.evidence_type }}
- Strength: {{ evidence_b.strength }}

## Instructions

Determine:
1. **is_conflict**: Do these claims contradict each other? (true/false)
2. **is_redundant**: Do these claims say the same thing? (true/false)
3. **notes**: Brief explanation of the relationship

## Output Format

```json
{
  "is_conflict": false,
  "is_redundant": false,
  "notes": "..."
}
```
