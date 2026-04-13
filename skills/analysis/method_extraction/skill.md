---
skill_id: analysis.method_extraction
version: "0.1"
phase: analysis
trust_tier: first_party_trusted
allowed_operators:
  - analysis_graph_extract
description: Guidance for method characterization from research papers
---

# Method Extraction Guidance

## Identifying methods

A method node represents an algorithm, technique, model architecture, or
systematic approach described in the paper. Look for:

- Named algorithms (e.g., "Adam optimizer", "BERT fine-tuning")
- Novel architectures or components proposed by the paper
- Training procedures and optimization strategies
- Evaluation protocols and metrics computation methods
- Data preprocessing or augmentation pipelines

## Characterization

For each method, capture:
- **Method family**: What broader category does it belong to?
- **Key parameters**: What are the critical hyperparameters?
- **Baseline comparisons**: What is it compared against?
- **Novelty claim**: Is this proposed as new, or applied from prior work?

## Relations

- `proposes`: The paper introduces this method
- `uses`: An experiment applies this method
- `compares`: This method is benchmarked against another
- `depends_on`: This method requires another as a component
