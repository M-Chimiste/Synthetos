"""Docker runner control-flow tests."""

from __future__ import annotations

from pathlib import Path

from libs.adapters.container import docker_runner


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

    def create(self, **_kwargs) -> _FakeContainer:
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

