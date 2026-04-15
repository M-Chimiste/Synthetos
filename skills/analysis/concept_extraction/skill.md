---
skill_id: analysis.concept_extraction
version: "0.1"
phase: analysis
trust_tier: first_party_trusted
allowed_operators:
  - analysis_graph_extract
description: Guidance for concept and entity extraction from research papers
---

# Concept Extraction Guidance

## What constitutes a concept node

A concept is a named idea, theory, principle, or domain term that:
- Has a specific, established meaning in the paper's field
- Is used repeatedly or defined explicitly
- Would help a reader understand the paper's contributions

## Granularity guidelines

- **Too broad**: "machine learning" (unless the paper is introducing ML itself)
- **Right level**: "attention mechanism", "contrastive loss", "knowledge distillation"
- **Too narrow**: "the specific learning rate schedule used in experiment 3"

## When to merge vs split

- **Merge** when two terms refer to the same concept (e.g., "self-attention" and "scaled dot-product attention" in context)
- **Split** when a compound concept has independently meaningful parts (e.g., "multi-head cross-attention" → "multi-head attention" + "cross-attention")

## Labels

- Use the most commonly used name in the paper
- Prefer established terminology over paper-specific jargon
- Include abbreviations in the description, not the label
