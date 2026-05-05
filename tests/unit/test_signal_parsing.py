"""Container → worker signal channel: SDK template + parser round-trip.

Two independent surfaces under test:

1.  The in-container SDK (libs/execution/sdk_template.SDK_SOURCE) emits
    one line per call, prefixed with SIGNAL_PREFIX, body is JSON. We exec
    the SDK source in a subprocess and capture stdout to make sure the
    runtime parser will actually see what the SDK actually emits — i.e.
    the prefix and JSON shape stay in sync.

2.  The parser logic inside the worker's telemetry callback. We can't
    easily import the closure, so we replicate the same parsing branch
    against the same SIGNAL_PREFIX constant. If that branch ever drifts
    in run.py, this test still pins the contract; the real callback is
    exercised live in the experiment runner.
"""

from __future__ import annotations

import json
import subprocess
import sys

from libs.execution.sdk_template import SDK_SOURCE, SIGNAL_PREFIX


def _parse_line(message: str) -> tuple[str, dict[str, object]]:
    """Re-implementation of the run.py callback's signal-parse branch.
    Kept in sync with libs/execution/operators/run.py so this test pins
    the contract end-to-end (same constant, same parser shape)."""
    payload: dict[str, object] = {}
    signal_start = message.find(SIGNAL_PREFIX)
    if signal_start >= 0:
        try:
            data = json.loads(message[signal_start + len(SIGNAL_PREFIX):])
            if isinstance(data, dict):
                event_name = str(data.get("event", "unknown"))
                return f"signal.{event_name}", {
                    k: v for k, v in data.items() if k != "event"
                }
        except (json.JSONDecodeError, ValueError):
            pass
    return "log", payload


def test_plain_log_stays_log() -> None:
    event_type, payload = _parse_line("training started, batch_size=32")
    assert event_type == "log"
    assert payload == {}


def test_valid_signal_line_classifies_as_signal_dot_event() -> None:
    line = SIGNAL_PREFIX + json.dumps(
        {"event": "checkpoint", "epoch": 5, "loss": 0.23}
    )
    event_type, payload = _parse_line(line)
    assert event_type == "signal.checkpoint"
    assert payload == {"epoch": 5, "loss": 0.23}


def test_timestamped_docker_log_signal_classifies_as_signal_dot_event() -> None:
    line = (
        "2026-05-05T01:23:45.678901234Z "
        + SIGNAL_PREFIX
        + json.dumps({"event": "metric", "name": "loss", "value": 0.23})
    )
    event_type, payload = _parse_line(line)
    assert event_type == "signal.metric"
    assert payload == {"name": "loss", "value": 0.23}


def test_malformed_signal_falls_back_to_log() -> None:
    """Garbage after the prefix must not crash the worker callback."""
    event_type, payload = _parse_line(SIGNAL_PREFIX + "this is not json")
    assert event_type == "log"
    assert payload == {}


def test_signal_with_no_event_field_uses_unknown() -> None:
    line = SIGNAL_PREFIX + json.dumps({"value": 42})
    event_type, payload = _parse_line(line)
    assert event_type == "signal.unknown"
    assert payload == {"value": 42}


def test_signal_with_non_dict_body_falls_back_to_log() -> None:
    """The SDK only emits dicts, but the parser must reject [1,2,3] etc.
    rather than crash on .get('event')."""
    line = SIGNAL_PREFIX + json.dumps([1, 2, 3])
    event_type, payload = _parse_line(line)
    assert event_type == "log"
    assert payload == {}


def test_sdk_subprocess_emits_parseable_lines() -> None:
    """End-to-end: exec the SDK source as if it were dropped into the
    worktree, call signal() with a few payloads, capture stdout, and feed
    it through the same parser. Pins the SDK and parser to the same wire
    format."""
    user_program = (
        SDK_SOURCE
        + "\n"
        + "signal('checkpoint', epoch=5, loss=0.23)\n"
        + "signal('metric', name='val_acc', value=0.91)\n"
        + "print('plain log line')\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", user_program],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line for line in result.stdout.splitlines() if line]
    parsed = [_parse_line(line) for line in lines]

    # 3 input lines → 3 outputs in order.
    assert len(parsed) == 3

    event_type_a, payload_a = parsed[0]
    assert event_type_a == "signal.checkpoint"
    assert payload_a == {"epoch": 5, "loss": 0.23}

    event_type_b, payload_b = parsed[1]
    assert event_type_b == "signal.metric"
    assert payload_b == {"name": "val_acc", "value": 0.91}

    event_type_c, _ = parsed[2]
    assert event_type_c == "log"
