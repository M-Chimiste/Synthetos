---
id: ideation.evidence_extraction
version: 0.1.0
phase: ideation
allowed_operators:
  - evidence_extraction
preferred_models:
  - evidence_extractor
context_inputs:
  - research_charter
  - shortlisted_papers
  - fulltext_content
outputs:
  - evidence_cards
capabilities:
  - source.read_metadata
  - source.read_fulltext
risk_level: low
---

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
