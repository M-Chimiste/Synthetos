"""Source for the in-container signal SDK.

`execution_setup` writes ``SDK_SOURCE`` to ``synthetos_signal.py`` in the
experiment's worktree before the container is started. User code in
``code_plan.files`` can then::

    from synthetos_signal import signal
    signal("checkpoint", epoch=5, loss=0.23)

Each call prints one tagged JSON line to stdout. The worker's telemetry
callback (libs/execution/operators/run.py) detects the
``SYNTHETOS_SIGNAL: `` prefix, parses the payload, and persists the row
to ``RunTelemetry`` with ``event_type='signal.<event>'`` instead of the
generic ``log``.

Keep ``SDK_SOURCE`` self-contained: it runs inside arbitrary experiment
images that may not have any of Synthetos's deps installed. Stdlib only.
"""

from __future__ import annotations

# The exact prefix the worker callback looks for. Kept on its own line so
# the regression test can assert the runtime parser and the SDK agree.
SIGNAL_PREFIX = "SYNTHETOS_SIGNAL: "

SDK_FILENAME = "synthetos_signal.py"

SDK_SOURCE = '''"""Synthetos in-container signal SDK (auto-injected, do not edit).

Emit one structured event per call. Each call prints a single tagged JSON
line to stdout; the orchestration worker parses it and persists a
RunTelemetry row keyed on the event name.

Usage:

    from synthetos_signal import signal
    signal("checkpoint", epoch=5, loss=0.23)
    signal("metric", name="val_acc", value=0.91)
    signal("phase", phase="training_done")

The first positional arg names the event (becomes ``signal.<event>`` on
the dashboard). All keyword args become payload fields.
"""

from __future__ import annotations

import json
import sys


SIGNAL_PREFIX = "SYNTHETOS_SIGNAL: "


def signal(event: str, **payload: object) -> None:
    """Emit one structured signal back to the Synthetos worker."""
    record = {"event": event, **payload}
    line = SIGNAL_PREFIX + json.dumps(record, default=str)
    print(line, flush=True)
    # Belt-and-suspenders: if stdout is line-buffered behind something
    # weird, force a flush again so the worker callback sees this line
    # promptly rather than after a buffer fills.
    sys.stdout.flush()
'''
