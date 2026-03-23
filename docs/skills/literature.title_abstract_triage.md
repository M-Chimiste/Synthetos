# literature.title_abstract_triage

## Manifest

- **ID:** literature.title_abstract_triage
- **Version:** 0.1.0
- **Phase:** literature
- **Risk Level:** low
- **Allowed Operators:** literature_screen
- **Outputs:** screening_decisions
- **Capabilities:** source.read_metadata, source.request_fulltext
- **Valid:** Yes

## Documentation

# Title and Abstract Triage

## Purpose
Screen title and abstract together before any deeper paper read.

## When to use
Use after metadata retrieval and before escalation to HTML or PDF content.

## Required behavior
- Consider title and abstract jointly.
- Produce shortlist rationale for any promoted item.
- Escalate to deeper reads only when a clear reason exists.
