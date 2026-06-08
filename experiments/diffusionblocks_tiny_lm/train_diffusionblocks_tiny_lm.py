"""Tiny DiffusionBlocks-style causal LM training payload.

This script is intentionally self-contained: PyTorch plus stdlib, deterministic
synthetic data, and flat JSON metrics for experiment runners.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F


@dataclass(frozen=True)
class ExperimentConfig:
    seed: int
    vocab_size: int
    seq_len: int
    batch_size: int
    eval_batches: int
    d_model: int
    n_heads: int
    n_layers: int
    dropout: float
    baseline_steps: int
    block_steps: int
    lr: float
    quick: bool
    device: str


class TinyTransformerBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, dropout: float) -> None:
        super().__init__()
        self.ln_attn = nn.LayerNorm(d_model)
        self.attn = nn.MultiheadAttention(
            d_model,
            n_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.ln_ff = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, 4 * d_model),
            nn.GELU(),
            nn.Linear(4 * d_model, d_model),
            nn.Dropout(dropout),
        )

    def forward(self, x: Tensor, causal_mask: Tensor) -> Tensor:
        attn_in = self.ln_attn(x)
        attn_out, _ = self.attn(
            attn_in,
            attn_in,
            attn_in,
            attn_mask=causal_mask,
            need_weights=False,
        )
        x = x + attn_out
        return x + self.ff(self.ln_ff(x))


class BaselineTinyLM(nn.Module):
    def __init__(self, cfg: ExperimentConfig) -> None:
        super().__init__()
        self.token_emb = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos_emb = nn.Embedding(cfg.seq_len, cfg.d_model)
        self.blocks = nn.ModuleList(
            [
                TinyTransformerBlock(cfg.d_model, cfg.n_heads, cfg.dropout)
                for _ in range(cfg.n_layers)
            ]
        )
        self.ln_f = nn.LayerNorm(cfg.d_model)
        self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size)

    def forward(self, tokens: Tensor, causal_mask: Tensor) -> Tensor:
        positions = torch.arange(tokens.size(1), device=tokens.device)
        x = self.token_emb(tokens) + self.pos_emb(positions).unsqueeze(0)
        for block in self.blocks:
            x = block(x, causal_mask)
        return self.lm_head(self.ln_f(x))


class SigmaConditioner(nn.Module):
    def __init__(self, d_model: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(2, d_model),
            nn.SiLU(),
            nn.Linear(d_model, d_model),
        )

    def forward(self, log_sigma: Tensor) -> Tensor:
        sigma = log_sigma.exp()
        features = torch.stack((log_sigma, sigma), dim=-1)
        return self.net(features).unsqueeze(1)


class BlockwiseTinyLM(nn.Module):
    def __init__(self, cfg: ExperimentConfig) -> None:
        super().__init__()
        self.token_emb = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos_emb = nn.Embedding(cfg.seq_len, cfg.d_model)
        self.blocks = nn.ModuleList(
            [
                TinyTransformerBlock(cfg.d_model, cfg.n_heads, cfg.dropout)
                for _ in range(cfg.n_layers)
            ]
        )
        self.conditioners = nn.ModuleList(
            [SigmaConditioner(cfg.d_model) for _ in range(cfg.n_layers)]
        )
        self.local_norms = nn.ModuleList([nn.LayerNorm(cfg.d_model) for _ in range(cfg.n_layers)])
        self.local_heads = nn.ModuleList(
            [nn.Linear(cfg.d_model, cfg.vocab_size) for _ in range(cfg.n_layers)]
        )

    def embed(self, tokens: Tensor) -> Tensor:
        positions = torch.arange(tokens.size(1), device=tokens.device)
        return self.token_emb(tokens) + self.pos_emb(positions).unsqueeze(0)

    def forward_to_block_input(
        self,
        tokens: Tensor,
        block_index: int,
        causal_mask: Tensor,
    ) -> Tensor:
        x = self.embed(tokens)
        for i in range(block_index):
            log_sigma = torch.full((tokens.size(0),), -4.0, device=tokens.device)
            x = self.blocks[i](x + self.conditioners[i](log_sigma), causal_mask)
        return x

    def block_logits(
        self,
        block_index: int,
        hidden_input: Tensor,
        log_sigma: Tensor,
        causal_mask: Tensor,
        *,
        add_noise: bool,
    ) -> Tensor:
        sigma = log_sigma.exp().view(-1, 1, 1)
        noise = (
            torch.randn_like(hidden_input) * sigma
            if add_noise
            else torch.zeros_like(hidden_input)
        )
        conditioned = hidden_input + noise + self.conditioners[block_index](log_sigma)
        hidden = self.blocks[block_index](conditioned, causal_mask)
        return self.local_heads[block_index](self.local_norms[block_index](hidden))

    def final_logits(self, tokens: Tensor, causal_mask: Tensor) -> Tensor:
        with torch.no_grad():
            x = self.embed(tokens)
            for i, block in enumerate(self.blocks):
                log_sigma = torch.full((tokens.size(0),), -4.0, device=tokens.device)
                x = block(x + self.conditioners[i](log_sigma), causal_mask)
        return self.local_heads[-1](self.local_norms[-1](x))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a faster smoke-test configuration.",
    )
    parser.add_argument("--artifact-dir", default=os.environ.get("ARTIFACTS_PATH", "/artifacts"))
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--baseline-steps", type=int, default=None)
    parser.add_argument("--block-steps", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--seq-len", type=int, default=32)
    parser.add_argument("--d-model", type=int, default=32)
    parser.add_argument("--n-layers", type=int, default=3)
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> ExperimentConfig:
    if args.threads > 0:
        torch.set_num_threads(args.threads)
    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda requested, but CUDA is not available")

    return ExperimentConfig(
        seed=args.seed,
        vocab_size=29,
        seq_len=args.seq_len,
        batch_size=args.batch_size if args.batch_size is not None else (12 if args.quick else 24),
        eval_batches=3 if args.quick else 6,
        d_model=args.d_model,
        n_heads=4,
        n_layers=args.n_layers,
        dropout=0.0,
        baseline_steps=(
            args.baseline_steps
            if args.baseline_steps is not None
            else (10 if args.quick else 60)
        ),
        block_steps=args.block_steps if args.block_steps is not None else (8 if args.quick else 35),
        lr=3e-3,
        quick=args.quick,
        device=device,
    )


def set_determinism(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def make_batch(
    cfg: ExperimentConfig,
    batch_index: int,
    device: torch.device,
) -> tuple[Tensor, Tensor]:
    """Create deterministic synthetic causal-LM examples.

    The rule mixes modular arithmetic, previous-token recurrence, position, and
    a per-example style token. It is easy enough for tiny models but not a simple
    unigram lookup.
    """

    total_len = cfg.seq_len + 1
    row = torch.arange(cfg.batch_size, device=device)
    seq = torch.empty((cfg.batch_size, total_len), dtype=torch.long, device=device)
    style = (row * 7 + batch_index * 3 + 5) % cfg.vocab_size
    seq[:, 0] = (style + row + 1) % cfg.vocab_size
    seq[:, 1] = (style * 2 + batch_index + row * 3 + 2) % cfg.vocab_size
    for pos in range(2, total_len):
        seq[:, pos] = (
            seq[:, pos - 1] * 2
            + seq[:, pos - 2] * 3
            + style
            + pos * 5
            + (row % 4)
        ) % cfg.vocab_size
    return seq[:, :-1], seq[:, 1:]


def causal_mask(seq_len: int, device: torch.device) -> Tensor:
    return torch.triu(torch.ones(seq_len, seq_len, dtype=torch.bool, device=device), diagonal=1)


def ce_loss(logits: Tensor, targets: Tensor) -> Tensor:
    return F.cross_entropy(logits.reshape(-1, logits.size(-1)), targets.reshape(-1))


def count_parameters(module: nn.Module, *, trainable_only: bool = False) -> int:
    params = module.parameters()
    if trainable_only:
        return sum(p.numel() for p in params if p.requires_grad)
    return sum(p.numel() for p in params)


def set_block_trainable(model: BlockwiseTinyLM, block_index: int) -> None:
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    for module in (
        model.blocks[block_index],
        model.conditioners[block_index],
        model.local_norms[block_index],
        model.local_heads[block_index],
    ):
        for parameter in module.parameters():
            parameter.requires_grad_(True)


def make_log_sigma(batch_size: int, step: int, block_index: int, device: torch.device) -> Tensor:
    # Deterministic log-noise schedule spanning low to moderate corruption.
    phase = torch.arange(batch_size, device=device, dtype=torch.float32)
    phase = (phase + step * 0.37 + block_index * 0.19).fmod(1.0)
    return -3.0 + phase * 2.4


def train_baseline(
    cfg: ExperimentConfig,
    device: torch.device,
    mask: Tensor,
) -> tuple[BaselineTinyLM, dict[str, float]]:
    model = BaselineTinyLM(cfg).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=0.01)
    losses: list[float] = []
    start = time.perf_counter()
    model.train()
    for step in range(cfg.baseline_steps):
        inputs, targets = make_batch(cfg, step, device)
        optimizer.zero_grad(set_to_none=True)
        loss = ce_loss(model(inputs, mask), targets)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
    elapsed = time.perf_counter() - start
    metrics = {
        "baseline_train_loss_last": losses[-1],
        "baseline_train_seconds": elapsed,
        "baseline_total_params": float(count_parameters(model)),
        "baseline_memory_proxy_trainable_params": float(
            count_parameters(model, trainable_only=True)
        ),
        "baseline_memory_proxy_activation_elements": float(
            cfg.batch_size * cfg.seq_len * cfg.d_model * cfg.n_layers
        ),
    }
    return model, metrics


def train_blockwise(
    cfg: ExperimentConfig,
    device: torch.device,
    mask: Tensor,
) -> tuple[BlockwiseTinyLM, dict[str, float]]:
    model = BlockwiseTinyLM(cfg).to(device)
    all_losses: list[float] = []
    metrics: dict[str, float] = {
        "blockwise_total_params": float(count_parameters(model)),
        "blockwise_memory_proxy_activation_elements": float(
            cfg.batch_size * cfg.seq_len * cfg.d_model
        ),
    }
    max_trainable = 0
    start = time.perf_counter()

    for block_index in range(cfg.n_layers):
        set_block_trainable(model, block_index)
        max_trainable = max(max_trainable, count_parameters(model, trainable_only=True))
        optimizer = torch.optim.AdamW(
            [p for p in model.parameters() if p.requires_grad],
            lr=cfg.lr,
            weight_decay=0.01,
        )
        block_losses: list[float] = []
        model.train()
        for step in range(cfg.block_steps):
            inputs, targets = make_batch(cfg, 10_000 + block_index * cfg.block_steps + step, device)
            with torch.no_grad():
                hidden_input = model.forward_to_block_input(inputs, block_index, mask).detach()
            log_sigma = make_log_sigma(cfg.batch_size, step, block_index, device)
            optimizer.zero_grad(set_to_none=True)
            logits = model.block_logits(block_index, hidden_input, log_sigma, mask, add_noise=True)
            loss = ce_loss(logits, targets)
            loss.backward()
            optimizer.step()
            block_losses.append(float(loss.detach().cpu()))
            all_losses.append(block_losses[-1])
        metrics[f"blockwise_block{block_index}_train_loss_last"] = block_losses[-1]

    elapsed = time.perf_counter() - start
    metrics["blockwise_train_loss_last"] = all_losses[-1]
    metrics["blockwise_train_seconds"] = elapsed
    metrics["blockwise_memory_proxy_max_trainable_params"] = float(max_trainable)
    return model, metrics


@torch.no_grad()
def evaluate_baseline(
    model: BaselineTinyLM,
    cfg: ExperimentConfig,
    device: torch.device,
    mask: Tensor,
) -> tuple[float, float]:
    model.eval()
    losses = []
    for batch_index in range(cfg.eval_batches):
        inputs, targets = make_batch(cfg, 50_000 + batch_index, device)
        losses.append(float(ce_loss(model(inputs, mask), targets).cpu()))
    loss = sum(losses) / len(losses)
    return loss, math.exp(min(loss, 20.0))


@torch.no_grad()
def evaluate_blockwise(
    model: BlockwiseTinyLM,
    cfg: ExperimentConfig,
    device: torch.device,
    mask: Tensor,
) -> dict[str, float]:
    model.eval()
    metrics: dict[str, float] = {}
    final_losses = []
    for batch_index in range(cfg.eval_batches):
        inputs, targets = make_batch(cfg, 60_000 + batch_index, device)
        final_losses.append(float(ce_loss(model.final_logits(inputs, mask), targets).cpu()))
    final_loss = sum(final_losses) / len(final_losses)
    metrics["blockwise_eval_loss"] = final_loss
    metrics["blockwise_eval_ppl"] = math.exp(min(final_loss, 20.0))

    for block_index in range(cfg.n_layers):
        block_losses = []
        for batch_index in range(cfg.eval_batches):
            inputs, targets = make_batch(cfg, 70_000 + block_index * 100 + batch_index, device)
            hidden_input = model.forward_to_block_input(inputs, block_index, mask).detach()
            log_sigma = torch.full((cfg.batch_size,), -4.0, device=device)
            logits = model.block_logits(block_index, hidden_input, log_sigma, mask, add_noise=False)
            block_losses.append(float(ce_loss(logits, targets).cpu()))
        block_loss = sum(block_losses) / len(block_losses)
        metrics[f"blockwise_block{block_index}_eval_loss"] = block_loss
        metrics[f"blockwise_block{block_index}_eval_ppl"] = math.exp(min(block_loss, 20.0))
    return metrics


def flatten_config(cfg: ExperimentConfig) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, value in asdict(cfg).items():
        if isinstance(value, bool | int | float):
            values[f"config_{key}"] = float(value)
    values["config_device_is_cuda"] = float(cfg.device == "cuda")
    return values


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    cfg = build_config(args)
    set_determinism(cfg.seed)
    device = torch.device(cfg.device)
    mask = causal_mask(cfg.seq_len, device)

    artifact_dir = Path(args.artifact_dir)
    if cfg.device == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    baseline, metrics = train_baseline(cfg, device, mask)
    baseline_eval_loss, baseline_eval_ppl = evaluate_baseline(baseline, cfg, device, mask)
    metrics["baseline_eval_loss"] = baseline_eval_loss
    metrics["baseline_eval_ppl"] = baseline_eval_ppl

    blockwise, block_metrics = train_blockwise(cfg, device, mask)
    metrics.update(block_metrics)
    metrics.update(evaluate_blockwise(blockwise, cfg, device, mask))

    if cfg.device == "cuda":
        metrics["cuda_peak_memory_mb"] = float(
            torch.cuda.max_memory_allocated(device) / (1024 * 1024)
        )
    else:
        metrics["cuda_peak_memory_mb"] = 0.0
    metrics["memory_proxy_trainable_param_ratio"] = (
        metrics["blockwise_memory_proxy_max_trainable_params"]
        / metrics["baseline_memory_proxy_trainable_params"]
    )
    metrics["loss_delta_blockwise_minus_baseline"] = (
        metrics["blockwise_eval_loss"] - metrics["baseline_eval_loss"]
    )
    metrics.update(flatten_config(cfg))
    metrics["success"] = 1.0

    # Keep metrics.json flat and numeric for runners that scrape it.
    numeric_metrics = {key: float(value) for key, value in metrics.items()}
    write_json(artifact_dir / "metrics.json", numeric_metrics)
    write_json(
        artifact_dir / "summary.json",
        {
            "success": True,
            "artifact": "diffusionblocks_tiny_lm",
            "device": cfg.device,
            "quick": cfg.quick,
            "baseline_eval_loss": baseline_eval_loss,
            "blockwise_eval_loss": numeric_metrics["blockwise_eval_loss"],
            "notes": (
                "Baseline trains end-to-end CE. Blockwise trains one sigma-conditioned "
                "transformer block and local head at a time with detached inputs."
            ),
        },
    )
    print(json.dumps(numeric_metrics, sort_keys=True))


if __name__ == "__main__":
    main()
