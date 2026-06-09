"""Shared container image defaults and dependency helpers."""

from __future__ import annotations

from typing import Any

DEFAULT_CPU_IMAGE = "python:3.12-slim"
BLACKWELL_PYTORCH_IMAGE = "pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime"

_TORCH_PRELOADED_PACKAGES = {
    "numpy",
    "torch",
}


def gpu_requested(profile: dict[str, Any] | None) -> bool:
    profile = profile or {}
    return bool(profile.get("gpu_required", profile.get("gpu", False)))


def default_base_image_for_hardware(profile: dict[str, Any] | None) -> str:
    if gpu_requested(profile):
        return BLACKWELL_PYTORCH_IMAGE
    return DEFAULT_CPU_IMAGE


def is_default_cpu_image(image: str | None) -> bool:
    return image in {None, "", DEFAULT_CPU_IMAGE}


def package_name(dependency: str) -> str:
    return (
        str(dependency)
        .split("==", 1)[0]
        .split(">=", 1)[0]
        .split("<=", 1)[0]
        .split("<", 1)[0]
        .split(">", 1)[0]
        .strip()
        .lower()
    )


def dependencies_satisfied_by_base_image(
    dependencies: Any,
    base_image: str | None,
) -> bool:
    if not isinstance(dependencies, list):
        return False
    if base_image != "synthetos:latest" and not str(base_image or "").startswith(
        "pytorch/pytorch:"
    ):
        return False

    packages = {package_name(dep) for dep in dependencies}
    packages.discard("")
    return bool(packages) and packages <= _TORCH_PRELOADED_PACKAGES
