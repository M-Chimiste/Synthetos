"""Tests for autonomous loop completion report generation."""

from __future__ import annotations

from pathlib import Path

import jinja2


class TestCompletionReportTemplate:
    def test_template_renders(self) -> None:
        """Verify the Jinja2 template renders without errors."""
        template_path = Path(
            "prompts/reporting/v1/autonomous_completion.md",
        )
        assert template_path.exists(), f"Missing template: {template_path}"

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_path.parent)),
            autoescape=False,
            undefined=jinja2.StrictUndefined,
        )
        template = env.get_template(template_path.name)
        rendered = template.render(
            charter_title="Test Charter",
            problem_statement="Test problem",
            total_iterations=5,
            total_runs=10,
            termination_reason="Budget exhausted",
            compute_used_minutes=120.5,
            compute_budget_minutes=480,
            runs_used=10,
            runs_budget=50,
            hypotheses=[
                {
                    "title": "Hypothesis A",
                    "status": "stalled",
                    "run_count": 3,
                    "best_metric": "0.85",
                    "last_signal": "stalled",
                },
            ],
            frontiers=[
                {
                    "metric_name": "accuracy",
                    "best_value": 0.85,
                    "best_run_public_id": "run-123",
                    "runs_since_improvement": 2,
                },
            ],
        )
        assert "Test Charter" in rendered
        assert "Budget exhausted" in rendered
        assert "Hypothesis A" in rendered
        assert "accuracy" in rendered

    def test_parameter_variation_template_renders(self) -> None:
        """Verify the parameter variation Jinja2 template renders."""
        template_path = Path(
            "prompts/ideation/v1/parameter_variation.md",
        )
        assert template_path.exists(), f"Missing template: {template_path}"

        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_path.parent)),
            autoescape=False,
            undefined=jinja2.StrictUndefined,
        )
        template = env.get_template(template_path.name)
        rendered = template.render(
            hypothesis_title="Test Hypothesis",
            objective="Classify images",
            method_description="Train ResNet-18",
            current_controls=[{"name": "lr", "value": 0.01}],
            recent_runs=[
                {
                    "public_id": "run-1",
                    "metrics": {"accuracy": 0.85},
                    "signal": "stalled",
                },
            ],
            directional_signal="stalled",
            hypothesis_run_count=3,
            variation_hints=[{"reason": "stall_break"}],
        )
        assert "Test Hypothesis" in rendered
        assert "stalled" in rendered
