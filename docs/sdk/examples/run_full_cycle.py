#!/usr/bin/env python3
"""Example: Create a research cycle and monitor it through the SDK."""

import time

from libs.sdk import SynthetoClient


def main() -> None:
    with SynthetoClient() as client:
        # 1. Create a research cycle
        result = client.create_cycle({
            "title": "Tabular Classification Baseline",
            "problem_statement": (
                "Establish a strong baseline for tabular classification "
                "on the Iris dataset."
            ),
            "success_criteria": {"target_metric": "accuracy > 0.95"},
            "budget_envelope": {"timebox_hours": 1},
            "source_scope": {"mode": "internal"},
            "stop_conditions": {"summary": "One verified run with accuracy > 0.95"},
            "constraints": {"dataset": "iris"},
        })
        cycle_id = result["cycle"]["public_id"]
        print(f"Created cycle: {cycle_id}")

        # 2. Monitor cycle status
        for _ in range(30):
            detail = client.get_cycle(cycle_id)
            status = detail["cycle"]["current_status"]
            print(f"  Status: {status}")
            if status in {"ready", "failed", "cancelled"}:
                break
            time.sleep(2)

        # 3. Check timeline
        timeline = client.get_timeline(cycle_id)
        print(f"\nTimeline ({len(timeline['items'])} events):")
        for entry in timeline["items"]:
            print(f"  [{entry['category']}] {entry['summary']}")

        # 4. List reports
        reports = client.list_reports()
        print(f"\nReports: {len(reports['items'])}")
        for report in reports["items"]:
            print(f"  - {report['title']} ({report['report_type']})")


if __name__ == "__main__":
    main()
