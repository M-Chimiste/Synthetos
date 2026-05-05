"""Docker runner control-flow tests."""

from __future__ import annotations

from pathlib import Path

from libs.adapters.container import docker_runner
from libs.core import config as config_module


class _FakeContainer:
    def __init__(self) -> None:
        self.id = "container-1"
        self.status = "running"
        self.pause_called = False
        self.unpause_called = False
        self.kill_called = False
        self.remove_called = False
        self.started = False

    def start(self) -> None:
        self.started = True

    def unpause(self) -> None:
        self.unpause_called = True

    def pause(self) -> None:
        self.pause_called = True
        self.status = "paused"

    def kill(self) -> None:
        self.kill_called = True
        self.status = "dead"

    def remove(self, force: bool = False) -> None:
        self.remove_called = force

    def logs(self, **_kwargs) -> bytes:
        return b""

    def reload(self) -> None:
        return None

    def wait(self, timeout: int = 30) -> dict[str, int]:
        return {"StatusCode": 0}

    def stats(self, stream: bool = False) -> dict[str, dict[str, int]]:
        return {"memory_stats": {"max_usage": 1024 * 1024}}


class _FakeContainerManager:
    def __init__(self, container: _FakeContainer) -> None:
        self.container = container
        self.create_kwargs: dict | None = None

    def create(self, **kwargs) -> _FakeContainer:
        self.create_kwargs = kwargs
        return self.container

    def get(self, _container_id: str) -> _FakeContainer:
        return self.container


class _FakeClient:
    def __init__(self, container: _FakeContainer) -> None:
        self.containers = _FakeContainerManager(container)
        self.images = type("Images", (), {"build": lambda *args, **kwargs: None})()


def _run_spec(tmp_path: Path) -> docker_runner.RunSpec:
    return docker_runner.RunSpec(
        workspace_path=tmp_path,
        image="python:3.12-slim",
        command=["python", "run_experiment.py"],
        artifact_output_path=tmp_path / "artifacts",
    )


def test_docker_runner_pause_preserves_container(monkeypatch, tmp_path: Path) -> None:
    container = _FakeContainer()
    monkeypatch.setattr(
        docker_runner.docker,
        "from_env",
        lambda: _FakeClient(container),
    )

    runner = docker_runner.DockerRunner()
    outcome = runner.run(
        _run_spec(tmp_path),
        control_callback=lambda: "pause",
    )

    assert outcome.terminal_state == "paused"
    assert container.pause_called is True
    assert container.remove_called is False


def test_docker_runner_cancel_removes_container(monkeypatch, tmp_path: Path) -> None:
    container = _FakeContainer()
    monkeypatch.setattr(
        docker_runner.docker,
        "from_env",
        lambda: _FakeClient(container),
    )

    runner = docker_runner.DockerRunner()
    outcome = runner.run(
        _run_spec(tmp_path),
        control_callback=lambda: "cancel",
    )

    assert outcome.terminal_state == "cancelled"
    assert container.kill_called is True
    assert container.remove_called is True


def test_docker_runner_named_volume_mode_uses_volume_mount(
    monkeypatch, tmp_path: Path
) -> None:
    """When container_data_volume is set, sibling containers receive a named
    volume mount instead of host-path bind mounts, and working_dir resolves
    to the workspace path inside that volume."""
    container = _FakeContainer()
    fake_client = _FakeClient(container)
    monkeypatch.setattr(docker_runner.docker, "from_env", lambda: fake_client)

    data_root = tmp_path / "lab_data"
    workspace = data_root / "workspaces" / "cycle_xyz" / "run_1"
    workspace.mkdir(parents=True)
    artifacts = data_root / "artifacts" / "run_1"

    settings = config_module.Settings(
        data_root=data_root,
        container_data_volume="lab_data",
    )
    monkeypatch.setattr(config_module, "_settings", settings)

    runner = docker_runner.DockerRunner()
    spec = docker_runner.RunSpec(
        workspace_path=workspace,
        image="python:3.12-slim",
        command=["python", "run.py"],
        artifact_output_path=artifacts,
    )
    # control_callback="cancel" exits the polling loop cleanly; we only need
    # to assert the container.create kwargs (set before the loop starts).
    runner.run(spec, control_callback=lambda: "cancel")

    create_kwargs = fake_client.containers.create_kwargs
    assert create_kwargs is not None

    mounts = create_kwargs["mounts"]
    assert len(mounts) == 1
    mount_spec = mounts[0]
    # docker-py Mount is a dict-like spec
    assert mount_spec["Type"] == "volume"
    assert mount_spec["Source"] == "lab_data"
    assert mount_spec["Target"] == str(data_root.resolve())

    expected_workdir = str(data_root.resolve() / "workspaces" / "cycle_xyz" / "run_1")
    assert create_kwargs["working_dir"] == expected_workdir
    assert spec.env["WORKSPACE_PATH"] == expected_workdir
    assert spec.env["ARTIFACTS_PATH"] == str(data_root.resolve() / "artifacts" / "run_1")


def test_docker_runner_host_mode_keeps_bind_mounts(monkeypatch, tmp_path: Path) -> None:
    """Host mode (default settings, container_data_volume=None) preserves
    the original bind-mount path for backwards compatibility."""
    container = _FakeContainer()
    fake_client = _FakeClient(container)
    monkeypatch.setattr(docker_runner.docker, "from_env", lambda: fake_client)

    settings = config_module.Settings()  # container_data_volume defaults to None
    monkeypatch.setattr(config_module, "_settings", settings)

    runner = docker_runner.DockerRunner()
    runner.run(_run_spec(tmp_path), control_callback=lambda: "cancel")

    create_kwargs = fake_client.containers.create_kwargs
    assert create_kwargs is not None
    mounts = create_kwargs["mounts"]
    assert len(mounts) == 2
    types = {m["Type"] for m in mounts}
    assert types == {"bind"}
    assert create_kwargs["working_dir"] == "/workspace"
