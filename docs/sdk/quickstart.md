# Synthetos SDK Quickstart

## Installation

The SDK is included in the monorepo at `libs/sdk/`. Ensure the project dependencies are installed:

```bash
uv sync
```

## Basic Usage

The current SDK covers the core non-streaming orchestrator API used by the web app and test flows: cycles, runs, reports, skills, verification summaries/details, timeline, literature lists, evidence lists, hypothesis lists, portfolio, and health checks. Admin endpoints and SSE streaming endpoints are intentionally not wrapped in the SDK yet.

### Sync Client

```python
from libs.sdk import SynthetoClient

with SynthetoClient(base_url="http://127.0.0.1:8000", token="lab-local-admin") as client:
    # Create a research cycle
    result = client.create_cycle({
        "title": "My Research Problem",
        "problem_statement": "Investigate whether X improves Y.",
        "success_criteria": {"target_metric": "accuracy > 0.9"},
        "budget_envelope": {"timebox_hours": 4},
        "source_scope": {"mode": "internal+arxiv"},
        "stop_conditions": {"summary": "3 verified runs"},
        "constraints": {},
    })
    cycle_id = result["cycle"]["public_id"]
    print(f"Created cycle: {cycle_id}")

    # Check health
    print(client.health())

    # List cycles
    cycles = client.list_cycles()
    print(f"Total cycles: {len(cycles['items'])}")

    # Get timeline
    timeline = client.get_timeline(cycle_id)
    for entry in timeline["items"]:
        print(f"  {entry['timestamp']}: {entry['summary']}")
```

### Async Client

```python
import asyncio
from libs.sdk import AsyncSynthetoClient

async def main():
    async with AsyncSynthetoClient() as client:
        health = await client.health()
        print(health)

        cycles = await client.list_cycles()
        print(f"Cycles: {len(cycles['items'])}")

asyncio.run(main())
```

## Error Handling

```python
from libs.sdk import SynthetoClient, SynthetoNotFoundError, SynthetoAuthError

with SynthetoClient() as client:
    try:
        client.get_cycle("nonexistent")
    except SynthetoNotFoundError:
        print("Cycle not found")
    except SynthetoAuthError:
        print("Authentication failed - check your token")
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_url` | `http://127.0.0.1:8000` | API server URL |
| `token` | `lab-local-admin` | Bearer token for authentication |
| `timeout` | `30.0` | Request timeout in seconds |
