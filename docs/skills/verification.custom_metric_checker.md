# verification.custom_metric_checker

## Manifest

- **ID:** verification.custom_metric_checker
- **Version:** 0.1.0
- **Phase:** verification
- **Risk Level:** low
- **Allowed Operators:** run_verify
- **Outputs:** custom_metric_report
- **Capabilities:** metrics.read, artifacts.read
- **Valid:** Yes
- **Hook Exports:** post_operator

## Documentation

# Custom Metric Checker

## Purpose
Demonstrate a custom verification skill that checks domain-specific metrics beyond the built-in sanity checks.

## When to use
Bind this skill when your experiments produce custom metrics (e.g., FID score for generative models, BLEU for NLP) that need domain-specific validation thresholds.

## Required behavior
- Read the `metrics.json` artifact from the run.
- Check each declared custom metric against a configurable threshold.
- Return a structured report indicating which metrics passed and which failed.
- Flag any metric that is suspiciously close to a known benchmark ceiling.

## Example configuration
```yaml
custom_metrics:
  fid_score:
    lower_is_better: true
    warn_threshold: 50.0
    fail_threshold: 100.0
  bleu:
    lower_is_better: false
    warn_threshold: 0.3
    fail_threshold: 0.1
```
