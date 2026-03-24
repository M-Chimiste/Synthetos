"""Tests for self-critic pre-check: fast LLM pass before full verification."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from libs.verification.self_critic import run_self_critic_precheck


class TestSelfCriticPrecheck:
    def test_passes_good_run(self) -> None:
        gateway = MagicMock()
        gateway.call_structured.return_value = {
            "passed": True,
            "flags": [],
            "rationale": "All metrics look reasonable.",
        }

        result = run_self_critic_precheck(
            gateway=gateway,
            metrics_summary={"accuracy": 0.85, "loss": 0.3},
            baseline_comparison={"metric": "accuracy", "delta_pct": 5.0, "passed": True},
            spec_metrics=[{"name": "accuracy", "higher_is_better": True}],
            charter_problem="Classify images",
            experiment_title="ResNet baseline",
        )

        assert result["passed"] is True
        assert result["flags"] == []

    def test_flags_issues(self) -> None:
        gateway = MagicMock()
        gateway.call_structured.return_value = {
            "passed": False,
            "flags": [
                {"issue": "Accuracy of 1.0 is suspiciously perfect", "severity": "critical"},
            ],
            "rationale": "Perfect accuracy suggests data leakage.",
        }

        result = run_self_critic_precheck(
            gateway=gateway,
            metrics_summary={"accuracy": 1.0},
            baseline_comparison={},
            spec_metrics=[{"name": "accuracy"}],
            charter_problem="Classify images",
            experiment_title="Leaky model",
        )

        assert result["passed"] is False
        assert len(result["flags"]) == 1
        assert result["flags"][0]["severity"] == "critical"

    def test_handles_gateway_failure(self) -> None:
        gateway = MagicMock()
        gateway.call_structured.side_effect = RuntimeError("LLM unavailable")

        result = run_self_critic_precheck(
            gateway=gateway,
            metrics_summary={"accuracy": 0.85},
            baseline_comparison={},
            spec_metrics=[],
            charter_problem="Test",
            experiment_title="Test",
        )

        # Fail-open: returns passed=True
        assert result["passed"] is True
        assert result["rationale"] == "skipped"

    def test_uses_critic_route(self) -> None:
        gateway = MagicMock()
        gateway.call_structured.return_value = {
            "passed": True, "flags": [], "rationale": "OK",
        }

        run_self_critic_precheck(
            gateway=gateway,
            metrics_summary={"accuracy": 0.85},
            baseline_comparison={},
            spec_metrics=[],
            charter_problem="Test",
            experiment_title="Test",
        )

        gateway.call_structured.assert_called_once()
        call_args = gateway.call_structured.call_args
        assert call_args[0][0] == "critic"

    def test_prompt_template_renders(self) -> None:
        """Verify the Jinja2 template renders without errors."""
        import jinja2

        template_path = Path("prompts/verification/v1/self_critic_precheck.md")
        assert template_path.exists(), f"Missing template: {template_path}"

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_path.parent)),
            autoescape=False,
            undefined=jinja2.StrictUndefined,
        )
        template = env.get_template(template_path.name)
        rendered = template.render(
            charter_problem="Test problem",
            experiment_title="Test experiment",
            metrics_summary={"accuracy": 0.85},
            baseline_comparison={"metric": "accuracy", "run_value": 0.85, "baseline_value": 0.80},
            spec_metrics=[{"name": "accuracy", "higher_is_better": True}],
        )
        assert "Test problem" in rendered
        assert "Test experiment" in rendered
