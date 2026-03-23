---
id: literature.data_profiler
version: 0.1.0
phase: literature
allowed_operators:
  - source_retrieval
outputs:
  - dataset_profile
capabilities:
  - datasets.read
risk_level: low
---

# Data Profiler

## Purpose
Profile dataset characteristics during the literature/source retrieval phase to inform downstream hypothesis generation.

## When to use
Bind this skill when working with tabular or structured datasets where understanding feature distributions, missing values, and correlations is important before formulating hypotheses.

## Required behavior
- Load the target dataset from the configured source.
- Compute basic statistics: row count, column count, types, missing values per column.
- Identify high-cardinality categorical columns.
- Flag potential data quality issues (>50% missing, constant columns, duplicate rows).
- Return a structured profile summary.
