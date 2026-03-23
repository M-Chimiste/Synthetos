# Skill Authoring Guide

## Overview

Skills are pluggable units of capability that operators can invoke during research cycles. Each skill is a `skill.md` file with YAML frontmatter (the manifest) and markdown body (the documentation).

## Directory Structure

```
skills/
  {phase}/
    {skill_name}/
      skill.md      # Required: manifest + documentation
      hooks.py      # Optional: Python hooks for pre/post operator behavior
```

## Manifest Schema

The YAML frontmatter must include these fields:

```yaml
---
id: {phase}.{skill_name}           # Unique identifier (required)
version: 1.0.0                     # Semver version (required, must match X.Y.Z)
phase: literature                  # Phase: planning, literature, ideation, coding, execution, verification, reporting
allowed_operators:                 # List of operators this skill can bind to (required, non-empty)
  - initialize_cycle
outputs:                           # What this skill produces (required)
  - charter_feedback
capabilities:                      # What system capabilities this skill needs (required)
  - charter.read
risk_level: low                    # Risk level: low, medium, high (required)
requires: []                       # Optional: skill IDs this skill depends on
conflicts_with: []                 # Optional: skill IDs that cannot coexist with this skill
---
```

### Field Details

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique skill identifier, conventionally `{phase}.{name}` |
| `version` | string | Yes | Semantic version (X.Y.Z format) |
| `phase` | string | Yes | One of: planning, literature, ideation, coding, execution, verification, reporting |
| `allowed_operators` | list[str] | Yes | Must be non-empty. Operators from the registry that can use this skill |
| `outputs` | list[str] | Yes | Artifact types this skill produces |
| `capabilities` | list[str] | Yes | System capabilities required |
| `risk_level` | string | Yes | `low`, `medium`, or `high` |
| `requires` | list[str] | No | Other skill IDs that must be active for this skill to work |
| `conflicts_with` | list[str] | No | Skill IDs that cannot be active alongside this skill |

### Known Operators

```
initialize_cycle, source_retrieval, literature_screen, shortlist_rank,
fulltext_escalation, literature_report, evidence_extraction,
hypothesis_generation, hypothesis_critique, protocol_compilation,
run_prepare, run_execute, run_finalize, run_retry_repair,
run_verify, failure_postmortem, verification_report
```

## Hook Contract

Optional `hooks.py` file can export these functions:

| Hook | Signature | When Called |
|------|-----------|------------|
| `pre_operator` | `(context: dict) -> dict` | Before the operator runs |
| `post_operator` | `(context: dict) -> dict` | After the operator succeeds |
| `on_failure` | `(context: dict) -> dict` | When the operator fails |
| `shape_context` | `(context: dict) -> dict` | To modify the context pack before operator execution |

The `context` dict contains: `cycle_id`, `job_id`, `operator_name`, `metrics`, `artifacts`, `skill_config`, and other operator-specific data.

## Validation Rules

Skills are validated at load time:

1. **Frontmatter required**: File must start with `---\n`
2. **Version must be semver**: `X.Y.Z` format
3. **Phase must be known**: One of the phases listed above
4. **Operators must be non-empty**: At least one allowed operator
5. **ID must be non-empty**: Cannot be blank
6. **Unknown operators**: Warning (not error) if operators are not in the known registry
7. **Unknown hooks**: Warning if hook functions don't match known hook names
8. **Dependencies**: `requires` skills must be present and active
9. **Conflicts**: `conflicts_with` skills must not be active

In **strict** validation mode (default), any error-severity issue prevents the skill from loading.

## Testing Your Skill

```python
from pathlib import Path
from libs.skills.loader import parse_skill_file

skill = parse_skill_file(Path("skills/my_phase/my_skill/skill.md"))
assert skill.is_valid, f"Validation issues: {skill.validation_issues}"
print(f"Loaded: {skill.skill_key} v{skill.version}")
```

## Example: Minimal Skill

```markdown
---
id: verification.simple_check
version: 0.1.0
phase: verification
allowed_operators:
  - run_verify
outputs:
  - check_result
capabilities:
  - artifacts.read
risk_level: low
---

# Simple Check

Performs a basic validation check on run artifacts.
```
