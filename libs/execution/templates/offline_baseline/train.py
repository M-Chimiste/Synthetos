from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_dataset(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _torch_baseline(rows: list[dict[str, object]], artifact_dir: Path) -> dict[str, object]:
    try:
        import torch
    except ImportError:
        return _fallback_baseline(rows, artifact_dir)

    xs = torch.tensor([row["features"] for row in rows], dtype=torch.float32)
    ys = torch.tensor([row["label"] for row in rows], dtype=torch.float32).unsqueeze(1)
    model = torch.nn.Sequential(torch.nn.Linear(xs.shape[1], 1))
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    loss_fn = torch.nn.BCEWithLogitsLoss()

    for _ in range(25):
        optimizer.zero_grad()
        logits = model(xs)
        loss = loss_fn(logits, ys)
        loss.backward()
        optimizer.step()

    with torch.no_grad():
        probs = torch.sigmoid(model(xs)).squeeze(1)
        preds = (probs >= 0.5).to(torch.int64)
        accuracy = float((preds == ys.squeeze(1).to(torch.int64)).float().mean().item())
        loss_value = float(loss_fn(model(xs), ys).item())

    checkpoint_path = artifact_dir / "model_checkpoint.pt"
    torch.save(model.state_dict(), checkpoint_path)
    predictions = [
        {"id": row["id"], "prediction": int(pred.item())}
        for row, pred in zip(rows, preds, strict=False)
    ]
    return {
        "framework": "torch",
        "metrics": {"accuracy": accuracy, "loss": loss_value},
        "checkpoint_path": str(checkpoint_path),
        "predictions": predictions,
    }


def _fallback_baseline(rows: list[dict[str, object]], artifact_dir: Path) -> dict[str, object]:
    predictions = []
    correct = 0
    for row in rows:
        score = sum(float(value) for value in row["features"])
        prediction = 1 if score > 1.0 else 0
        predictions.append({"id": row["id"], "prediction": prediction})
        correct += int(prediction == int(row["label"]))
    accuracy = correct / max(len(rows), 1)
    checkpoint_path = artifact_dir / "model_checkpoint.json"
    checkpoint_path.write_text(
        json.dumps({"rule": "sum(features) > 1.0"}, indent=2),
        encoding="utf-8",
    )
    return {
        "framework": "fallback",
        "metrics": {"accuracy": accuracy, "loss": 0.0},
        "checkpoint_path": str(checkpoint_path),
        "predictions": predictions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = Path(args.config).parent / config["dataset_path"]
    rows = _load_dataset(dataset_path)
    result = _torch_baseline(rows, artifact_dir)

    metrics_path = artifact_dir / "metrics.json"
    metrics_path.write_text(json.dumps(result["metrics"], indent=2), encoding="utf-8")
    predictions_path = artifact_dir / "predictions.json"
    predictions_path.write_text(json.dumps(result["predictions"], indent=2), encoding="utf-8")
    manifest = {
        "run_public_id": config["run_public_id"],
        "manifest_path": str(artifact_dir / "artifact_manifest.json"),
        "metrics_path": str(metrics_path),
        "checkpoint_path": result["checkpoint_path"],
        "predictions_path": str(predictions_path),
        "artifacts": [
            {"name": "metrics", "path": str(metrics_path)},
            {"name": "checkpoint", "path": result["checkpoint_path"]},
            {"name": "predictions", "path": str(predictions_path)},
        ],
        "framework": result["framework"],
    }
    (artifact_dir / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
