from libs.execution.artifacts import classify_failure, collect_artifact_manifest
from libs.execution.policy import ExecutionPolicyDecision, evaluate_run_policy
from libs.execution.runner import (
    build_run_spec,
    determine_run_paths,
    preflight_run_spec,
    stage_execution_harness,
)

# Failure classifications that are transient and safe for automatic retry.
# Non-transient failures (timeout, oom_or_resource_limit) require user intervention.
TRANSIENT_FAILURES: set[str] = {
    "runtime_exception",
    "dependency_failure",
    "metric_parse_failure",
    "invalid_artifact_output",
}

__all__ = [
    "ExecutionPolicyDecision",
    "TRANSIENT_FAILURES",
    "build_run_spec",
    "classify_failure",
    "collect_artifact_manifest",
    "determine_run_paths",
    "evaluate_run_policy",
    "preflight_run_spec",
    "stage_execution_harness",
]
