"""Docker SDK runner for experiment container execution."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docker.errors import NotFound
from docker.types import DeviceRequest, Mount

import docker
from libs.core.logging import get_logger

log = get_logger("adapters.container.docker_runner")


@dataclass
class RunSpec:
    """Fully resolved spec for container execution."""

    workspace_path: Path
    image: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    gpu_enabled: bool = False
    gpu_count: int = 1
    memory_limit: str = "16g"
    timeout_seconds: int = 3600
    artifact_output_path: Path = field(default_factory=lambda: Path("/tmp/artifacts"))
    network_mode: str = "none"


@dataclass
class RunOutcome:
    """Result of a container execution."""

    exit_code: int
    wall_time_s: float
    resource_usage: dict[str, Any] = field(default_factory=dict)
    container_id: str = ""
    terminal_state: Literal["completed", "paused", "cancelled", "failed"] = "completed"
    status_message: str | None = None


TelemetryCallback = Callable[[str, str, dict[str, Any]], None]
"""(event_type, message, payload) -> None"""

ControlActionCallback = Callable[[], Literal["pause", "cancel"] | None]
"""Returns a control action for the active run, if any."""


class DockerRunner:
    """Manages sibling Docker containers for experiment execution."""

    def __init__(self) -> None:
        self.client = docker.from_env()

    def build_image(
        self,
        *,
        dockerfile_content: str,
        tag: str,
        context_path: Path,
    ) -> str:
        """Build a Docker image on-demand. Returns the image tag."""
        dockerfile_path = context_path / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)

        log.info("docker.building_image", tag=tag, context=str(context_path))
        self.client.images.build(
            path=str(context_path),
            tag=tag,
            dockerfile="Dockerfile",
            rm=True,
        )
        return tag

    def run(
        self,
        spec: RunSpec,
        *,
        telemetry_callback: TelemetryCallback | None = None,
        control_callback: ControlActionCallback | None = None,
        resume_container_id: str | None = None,
    ) -> RunOutcome:
        """Execute a container and return the outcome.

        1. Creates container with mounts, env, GPU, memory limits
        2. Starts container
        3. Streams logs, calling telemetry_callback per line
        4. Waits with timeout
        5. Collects exit code
        6. Removes container
        """
        spec.artifact_output_path.mkdir(parents=True, exist_ok=True)

        mounts = [
            Mount(
                target="/workspace",
                source=str(spec.workspace_path),
                type="bind",
                read_only=False,
            ),
            Mount(
                target="/artifacts",
                source=str(spec.artifact_output_path),
                type="bind",
                read_only=False,
            ),
        ]

        device_requests = []
        if spec.gpu_enabled:
            device_requests.append(
                DeviceRequest(
                    count=spec.gpu_count,
                    capabilities=[["gpu"]],
                )
            )

        log.info(
            "docker.creating_container",
            image=spec.image,
            command=spec.command,
            gpu=spec.gpu_enabled,
        )

        if resume_container_id:
            container = self.client.containers.get(resume_container_id)
            container_id = str(container.id)
            container.unpause()
            if telemetry_callback:
                telemetry_callback(
                    "status_change",
                    "container_resumed",
                    {"container_id": container_id},
                )
        else:
            container = self.client.containers.create(
                image=spec.image,
                command=spec.command,
                environment=spec.env,
                mounts=mounts,
                device_requests=device_requests or None,
                mem_limit=spec.memory_limit,
                network_mode=spec.network_mode,
                working_dir="/workspace",
                detach=True,
            )
            container_id = str(container.id)

        start_time = time.monotonic()
        log_cursor = int(time.time()) - 1
        seen_log_lines: set[str] = set()
        terminal_state: Literal["completed", "paused", "cancelled", "failed"] = "completed"
        status_message: str | None = None

        try:
            if not resume_container_id:
                container.start()
                log.info("docker.container_started", container_id=container_id)

                if telemetry_callback:
                    telemetry_callback(
                        "status_change",
                        "container_started",
                        {"container_id": container_id},
                    )

            exit_code = -1
            while True:
                if control_callback:
                    action = control_callback()
                    if action == "pause":
                        container.pause()
                        terminal_state = "paused"
                        status_message = "container paused"
                        if telemetry_callback:
                            telemetry_callback(
                                "status_change",
                                "container_paused",
                                {"container_id": container_id},
                            )
                        break
                    if action == "cancel":
                        container.kill()
                        terminal_state = "cancelled"
                        status_message = "container cancelled"
                        if telemetry_callback:
                            telemetry_callback(
                                "status_change",
                                "container_cancelled",
                                {"container_id": container_id},
                            )
                        break

                current_epoch = max(log_cursor, int(time.time()) - 1)
                raw_logs = container.logs(
                    stdout=True,
                    stderr=True,
                    timestamps=True,
                    since=current_epoch,
                )
                decoded = raw_logs.decode("utf-8", errors="replace")
                if decoded:
                    for line in decoded.splitlines():
                        if not line or line in seen_log_lines:
                            continue
                        seen_log_lines.add(line)
                        if telemetry_callback:
                            telemetry_callback("log", line, {})
                    log_cursor = int(time.time())
                    if len(seen_log_lines) > 500:
                        seen_log_lines.clear()

                elapsed = time.monotonic() - start_time
                if elapsed > spec.timeout_seconds:
                    log.warning(
                        "docker.timeout",
                        container_id=container_id,
                        timeout=spec.timeout_seconds,
                    )
                    container.stop(timeout=10)
                    terminal_state = "failed"
                    status_message = "timeout"
                    if telemetry_callback:
                        telemetry_callback(
                            "status_change",
                            "timeout",
                            {"elapsed_s": elapsed},
                        )
                    break

                container.reload()
                if container.status in {"exited", "dead"}:
                    wait_result = container.wait(timeout=30)
                    exit_code = int(wait_result.get("StatusCode", -1))
                    terminal_state = "completed" if exit_code == 0 else "failed"
                    break

                time.sleep(1.0)

        except Exception:
            log.exception("docker.execution_error", container_id=container_id)
            with contextlib.suppress(Exception):
                container.kill()
            raise
        finally:
            wall_time = time.monotonic() - start_time

        # Collect resource stats
        resource_usage: dict[str, Any] = {"wall_time_s": round(wall_time, 2)}
        try:
            raw_stats = container.stats(stream=False)
            stats: dict[str, Any] = raw_stats if isinstance(raw_stats, dict) else {}
            mem_stats = stats.get("memory_stats")
            if isinstance(mem_stats, dict):
                max_usage = mem_stats.get("max_usage")
                if isinstance(max_usage, (int, float)):
                    resource_usage["peak_memory_mb"] = round(
                        float(max_usage) / (1024 * 1024), 1
                    )
        except Exception:
            pass

        if terminal_state != "paused":
            try:
                container.remove(force=True)
            except Exception:
                log.warning("docker.remove_failed", container_id=container_id)

        return RunOutcome(
            exit_code=exit_code,
            wall_time_s=round(wall_time, 2),
            resource_usage=resource_usage,
            container_id=container_id,
            terminal_state=terminal_state,
            status_message=status_message,
        )

    def pause(self, container_id: str) -> None:
        """Pause a running container (SIGSTOP)."""
        container = self.client.containers.get(container_id)
        container.pause()

    def unpause(self, container_id: str) -> None:
        """Unpause a paused container (SIGCONT)."""
        container = self.client.containers.get(container_id)
        container.unpause()

    def kill(self, container_id: str) -> None:
        """Force-kill a container."""
        try:
            container = self.client.containers.get(container_id)
            container.kill()
            container.remove(force=True)
        except NotFound:
            pass
