# ideation.evidence_extraction

## Manifest

- **ID:** ideation.evidence_extraction
- **Version:** 0.1.0
- **Phase:** ideation
- **Risk Level:** low
- **Allowed Operators:** evidence_extraction
- **Outputs:** evidence_cards
- **Capabilities:** source.read_metadata, source.read_fulltext
- **Valid:** Yes
- **Hook Exports:** shape_context

## Documentation

# Evidence Extraction

## Purpose
Extract structured evidence claims from shortlisted papers.

## When to use
Use after full-text content has been retrieved for shortlisted papers.

## Required behavior
- Extract discrete, falsifiable claims from each paper
- Tag each claim with its source location (section, paragraph)
- Classify evidence by type (empirical result, theoretical argument, methodological insight)
- Link evidence back to the research charter objectives
