"""Output contract verification for experiment runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ArtifactCheck:
    """Result of checking one expected artifact."""

    name: str
    expected: bool
    found: bool
    required: bool
    passed: bool
    detail: str


def check_artifact_contract(
    artifact_manifest: list[dict[str, Any]],
    expected_artifacts: list[dict[str, Any]],
) -> list[ArtifactCheck]:
    """Verify that expected artifacts are present in the manifest.

    For each expected artifact:
    - Check it exists in manifest by name
    - If required=True and missing -> failed
    - If present -> passed, include size_bytes and hash
    """
    manifest_names = {a["name"] for a in artifact_manifest}
    checks = []

    for expected in expected_artifacts:
        name = expected.get("name", "")
        required = expected.get("required", True)
        found = name in manifest_names

        if found:
            manifest_entry = next(a for a in artifact_manifest if a["name"] == name)
            detail = (
                f"found: size={manifest_entry.get('size_bytes', '?')} bytes, "
                f"hash={manifest_entry.get('hash', '?')[:12]}"
            )
        else:
            detail = "not found in artifact manifest"

        passed = found or not required

        checks.append(ArtifactCheck(
            name=name,
            expected=True,
            found=found,
            required=required,
            passed=passed,
            detail=detail,
        ))

    return checks
