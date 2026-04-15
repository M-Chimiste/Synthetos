"""Tests for the InjectionPolicy default values and config parsing."""

from __future__ import annotations

from libs.patterns.injection import InjectionPolicy


def test_defaults_match_plan() -> None:
    p = InjectionPolicy()
    assert p.min_confidence_auto == 0.7
    assert p.max_staleness_days == 90
    assert p.cross_charter_weight_boost == 1.15


def test_from_cycle_config_overrides() -> None:
    p = InjectionPolicy.from_cycle_config(
        {
            "patterns": {
                "min_confidence_auto": 0.85,
                "max_staleness_days": 30,
                "cross_charter_weight_boost": 1.5,
                "cross_charter_only": True,
                "injection_limit": 3,
            }
        }
    )
    assert p.min_confidence_auto == 0.85
    assert p.max_staleness_days == 30
    assert p.cross_charter_weight_boost == 1.5
    assert p.cross_charter_only is True
    assert p.limit == 3


def test_from_empty_config_uses_defaults() -> None:
    p = InjectionPolicy.from_cycle_config({})
    assert p.min_confidence_auto == 0.7
    p2 = InjectionPolicy.from_cycle_config(None)
    assert p2.min_confidence_auto == 0.7
