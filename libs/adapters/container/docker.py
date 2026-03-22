from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from libs.schemas.domain import RunSpec


@dataclass
class ContainerExecutionResult:
    exit_code: int | None
    interrupted_status: str | None
    latest_resource_snapshot: dict[str, object]


def build_docker_run_command(container_name: str, spec: RunSpec) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none" if spec.network_mode == "disabled" else spec.network_mode,
        "--memory",
        f"{spec.memory_limit_mb}m",
    ]
    if spec.cpu_limit:
        command.extend(["--cpus", spec.cpu_limit])
    if spec.gpu_enabled:
        command.extend(["--gpus", "all"])
    for mount in spec.mounts:
        source = mount["source_path"]
        target = mount["target_path"]
        mode = "ro" if mount.get("read_only", False) else "rw"
        command.extend(["-v", f"{source}:{target}:{mode}"])
    for key, value in spec.env_vars.items():
        command.extend(["-e", f"{key}={value}"])
    command.append(spec.image)
    command.extend(spec.command)
    return command


class DockerContainerAdapter:
    def __init__(self, poll_interval_seconds: float = 1.0):
        self.poll_interval_seconds = poll_interval_seconds

    def run(
        self,
        *,
        spec: RunSpec,
        stdout_path: Path,
        stderr_path: Path,
        telemetry_callback: Callable[[str, dict[str, object], str | None, str | None], None],
        status_checker: Callable[[], str | None] | None = None,
        container_name: str,
    ) -> ContainerExecutionResult:
        if shutil.which("docker") is None:
            raise RuntimeError("Docker CLI is not available on PATH")

        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        command = build_docker_run_command(container_name, spec)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        latest_resource_snapshot: dict[str, object] = {}
        interrupted_status: str | None = None

        def _stream_reader(stream_name: str, handle, path: Path) -> None:
            with path.open("a", encoding="utf-8") as sink:
                if handle is None:
                    return
                for line in iter(handle.readline, ""):
                    sink.write(line)
                    sink.flush()
                    telemetry_callback(
                        "log",
                        {"line": line.rstrip("\n")},
                        stream_name,
                        line.rstrip("\n"),
                    )

        stdout_thread = threading.Thread(
            target=_stream_reader, args=("stdout", process.stdout, stdout_path), daemon=True
        )
        stderr_thread = threading.Thread(
            target=_stream_reader, args=("stderr", process.stderr, stderr_path), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()

        while process.poll() is None:
            requested_status = status_checker() if status_checker else None
            if requested_status == "cancel_requested":
                subprocess.run(["docker", "stop", container_name], check=False, capture_output=True)
                interrupted_status = "cancelled"
                break
            if requested_status == "pause_requested":
                subprocess.run(["docker", "stop", container_name], check=False, capture_output=True)
                interrupted_status = "paused"
                break
            snapshot = self.sample_resources(container_name)
            if snapshot:
                latest_resource_snapshot = snapshot
                telemetry_callback("resource", snapshot, None, None)
            time.sleep(self.poll_interval_seconds)

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        exit_code = process.poll()
        if interrupted_status is not None and exit_code is None:
            process.wait(timeout=5)
            exit_code = process.returncode
        return ContainerExecutionResult(
            exit_code=exit_code,
            interrupted_status=interrupted_status,
            latest_resource_snapshot=latest_resource_snapshot,
        )

    def sample_resources(self, container_name: str) -> dict[str, object]:
        completed = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                container_name,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}
        try:
            return json.loads(completed.stdout.strip())
        except json.JSONDecodeError:
            return {}
