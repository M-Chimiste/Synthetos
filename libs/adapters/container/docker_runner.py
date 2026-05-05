"""Docker SDK runner for experiment container execution."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docker.errors import BuildError, NotFound
from docker.types import DeviceRequest, Mount

import docker
from libs.core.config import get_settings
from libs.core.logging import get_logger


class BuildImageError(Exception):
    """Raised when ``DockerRunner.build_image`` fails. Carries the captured
    build log and the underlying cause so the execution_setup operator can
    persist them and route the failure through the auto-remediation loop.
    """

    def __init__(
        self,
        tag: str,
        log_text: str,
        cause: BaseException | str,
    ) -> None:
        self.tag = tag
        self.log_text = log_text
        self.cause = cause
        super().__init__(f"image build failed for tag {tag}: {cause}")

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
        """Build a Docker image on-demand. Returns the image tag.

        The build output stream is consumed line-by-line so we can surface
        useful diagnostics on failure. On error we raise
        :class:`BuildImageError` carrying the captured log text and the
        underlying cause; ``execution_setup`` persists those alongside the
        ``RunRecord`` and routes the failure through auto-remediation.
        """
        dockerfile_path = context_path / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)

        log.info("docker.building_image", tag=tag, context=str(context_path))

        log_lines: list[str] = []
        try:
            _image, build_log = self.client.images.build(
                path=str(context_path),
                tag=tag,
                dockerfile="Dockerfile",
                rm=True,
            )
            for chunk in build_log:
                if not isinstance(chunk, dict):
                    continue
                if "stream" in chunk:
                    log_lines.append(str(chunk["stream"]).rstrip("\n"))
                elif "error" in chunk:
                    # Some daemons emit an `error` chunk before raising.
                    log_lines.append(f"ERROR: {chunk['error']}")
        except BuildError as exc:
            # docker-py's BuildError exposes the build log on `.build_log`,
            # an iterable of dicts. Drain it into our captured tail.
            for chunk in getattr(exc, "build_log", []) or []:
                if not isinstance(chunk, dict):
                    continue
                if "stream" in chunk:
                    log_lines.append(str(chunk["stream"]).rstrip("\n"))
                elif "error" in chunk:
                    log_lines.append(f"ERROR: {chunk['error']}")
            raise BuildImageError(
                tag=tag,
                log_text="\n".join(log_lines),
                cause=exc,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive for daemon errors
            raise BuildImageError(
                tag=tag,
                log_text="\n".join(log_lines),
                cause=exc,
            ) from exc

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

        # Path / mount strategy:
        # - Host mode (default): bind-mount the worktree and artifact dirs.
        #   `spec.workspace_path` is a host-resolvable path.
        # - Containerized worker mode: when LAB_CONTAINER_DATA_VOLUME is set,
        #   the worker is itself a container and bind-mount sources inside it
        #   are not visible to the host Docker daemon. Mount the named volume
        #   instead and address the workspace/artifact dirs by their path
        #   within that volume (relative to LAB_DATA_ROOT).
        settings = get_settings()
        volume_name = settings.container_data_volume

        if volume_name:
            data_root = Path(settings.data_root).resolve()
            try:
                workspace_rel = spec.workspace_path.resolve().relative_to(data_root)
                artifact_rel = spec.artifact_output_path.resolve().relative_to(data_root)
            except ValueError as exc:
                raise RuntimeError(
                    "container_data_volume is set but workspace_path "
                    f"({spec.workspace_path}) or artifact_output_path "
                    f"({spec.artifact_output_path}) is outside data_root "
                    f"({data_root}). All paths must live under data_root in "
                    "containerized worker mode."
                ) from exc
            mounts = [
                Mount(
                    target=str(data_root),
                    source=volume_name,
                    type="volume",
                    read_only=False,
                ),
            ]
            workspace_in_container = str(data_root / workspace_rel)
            artifact_in_container = str(data_root / artifact_rel)
            spec.env.setdefault("WORKSPACE_PATH", workspace_in_container)
            spec.env.setdefault("ARTIFACTS_PATH", artifact_in_container)
            container_working_dir = workspace_in_container
        else:
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
            container_working_dir = "/workspace"

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
                working_dir=container_working_dir,
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
