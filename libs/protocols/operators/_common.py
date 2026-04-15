"""Shared helpers for protocol operators.

Protocol compilation reuses the hypothesis session for state tracking
(step_log, stats) since it operates on the same cycle's hypothesis cards.
For failures it sets HypothesisCard status directly.
"""
