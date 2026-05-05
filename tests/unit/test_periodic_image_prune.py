"""Periodic image GC keeps the N newest synthetos-exp-* images and
removes the rest. Pre-existing orchestration images are filtered out by
the tag-prefix on `images.list`, so we only need to verify the sort +
slice + remove flow against a fake docker client.
"""

from __future__ import annotations

from apps.worker import periodic


class _FakeImage:
    def __init__(self, id_: str, created: str) -> None:
        self.id = id_
        self.attrs = {"Created": created}


class _FakeImagesAPI:
    def __init__(self, images: list[_FakeImage]) -> None:
        self._images = images
        self.list_calls: list[dict] = []
        self.removed: list[str] = []

    def list(self, **kwargs) -> list[_FakeImage]:
        self.list_calls.append(kwargs)
        return list(self._images)

    def remove(self, image: str, force: bool = False) -> None:
        self.removed.append(image)


class _FakeClient:
    def __init__(self, images: list[_FakeImage]) -> None:
        self.images = _FakeImagesAPI(images)


def _patch_docker(monkeypatch, client: _FakeClient) -> None:
    import docker

    monkeypatch.setattr(docker, "from_env", lambda: client)


def test_prune_keeps_newest_n(monkeypatch) -> None:
    # 8 images, monotonic Created timestamps. Newest first when sorted.
    images = [
        _FakeImage(f"sha256:img{i}", f"2026-05-{(i + 1):02d}T00:00:00Z")
        for i in range(8)
    ]
    client = _FakeClient(images)
    _patch_docker(monkeypatch, client)

    result = periodic._prune_experiment_images(keep=5)

    # 3 oldest removed, 5 newest kept.
    assert result == {"images_pruned": 3, "images_kept": 5}
    # Removed images are img0..img2 (the 3 with smallest Created timestamps).
    assert sorted(client.images.removed) == [
        "sha256:img0",
        "sha256:img1",
        "sha256:img2",
    ]
    # Filter restricted the listing to exp-tagged images.
    assert client.images.list_calls == [{"filters": {"reference": "synthetos-exp-*"}}]


def test_prune_under_keep_threshold_is_noop(monkeypatch) -> None:
    images = [
        _FakeImage(f"sha256:img{i}", f"2026-05-{(i + 1):02d}T00:00:00Z")
        for i in range(3)
    ]
    client = _FakeClient(images)
    _patch_docker(monkeypatch, client)

    result = periodic._prune_experiment_images(keep=5)

    assert result == {"images_pruned": 0, "images_kept": 3}
    assert client.images.removed == []


def test_prune_skips_image_in_use(monkeypatch) -> None:
    """If `images.remove` raises (in-use, concurrent delete, etc.), we log
    and move on — the next periodic tick will retry. We never want to
    interrupt an in-flight experiment."""
    from docker.errors import APIError

    images = [
        _FakeImage(f"sha256:img{i}", f"2026-05-{(i + 1):02d}T00:00:00Z")
        for i in range(8)
    ]
    client = _FakeClient(images)

    in_use_id = "sha256:img0"  # the oldest, would be the first to remove

    def remove_raising_for_inuse(image: str, force: bool = False) -> None:
        if image == in_use_id:
            raise APIError("conflict: in use by container")
        client.images.removed.append(image)

    client.images.remove = remove_raising_for_inuse  # type: ignore[assignment]
    _patch_docker(monkeypatch, client)

    result = periodic._prune_experiment_images(keep=5)

    # Two of the three "to remove" got pruned; the in-use one was skipped.
    assert result["images_pruned"] == 2
    assert result["images_kept"] == 5
    assert in_use_id not in client.images.removed
