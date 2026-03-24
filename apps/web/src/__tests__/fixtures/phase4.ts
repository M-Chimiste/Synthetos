import type {
  ReportDetail,
  TimelineEntry,
} from "../../lib/types";

export const sampleTimelineEntries: TimelineEntry[] = [
  {
    timestamp: "2026-03-23T10:00:00Z",
    event_type: "cycle_created",
    category: "state_change",
    summary: "Cycle created",
    details: {},
  },
  {
    timestamp: "2026-03-23T10:01:00Z",
    event_type: "job_claimed",
    category: "operator",
    summary: "Started operator: initialize_cycle",
    details: { operator_name: "initialize_cycle" },
  },
  {
    timestamp: "2026-03-23T10:05:00Z",
    event_type: "run_command_received",
    category: "run",
    summary: "Run command: retry",
    details: { command: "retry" },
  },
  {
    timestamp: "2026-03-23T10:10:00Z",
    event_type: "report_created",
    category: "report",
    summary: "Report generated: Verification Report",
    details: { title: "Verification Report" },
  },
  {
    timestamp: "2026-03-23T10:12:00Z",
    event_type: "run_verified",
    category: "run",
    summary: "Run verified with frontier progress",
    details: { outcome: "tentative" },
    directional_signal: "advancing",
    verification_outcome: "tentative",
    frontier_snapshot: {
      metric_name: "accuracy",
      current_value: 0.91,
      best_value: 0.91,
      best_run_public_id: "run_5",
      runs_since_improvement: 0,
      series_tail: [0.82, 0.85, 0.87, 0.91],
    },
  },
];

export const sampleReport: ReportDetail = {
  public_id: "report_abc123",
  cycle_public_id: "cycle_xyz",
  report_type: "verification_report",
  title: "Verification Report — Run 1",
  artifact_path: "/artifacts/reports/report_abc123.md",
  created_at: "2026-03-23T10:10:00Z",
  markdown: `# Verification Report

## Outcome
Run verified as **robust**.

## Checks
| Check | Status |
|-------|--------|
| Artifact presence | Pass |
| Metric sanity | Pass |
| Leakage | Clean |

## Summary
All verification checks passed with score 0.95.
`,
  quality_metadata: {
    structural_score: 0.85,
    word_count: 45,
    section_checklist: {
      Outcome: true,
      Checks: true,
      Summary: true,
    },
    has_tables: true,
    has_metrics: true,
  },
};

export const sampleReportLowQuality: ReportDetail = {
  public_id: "report_low",
  cycle_public_id: "cycle_xyz",
  report_type: "cycle_summary",
  title: "Incomplete Report",
  artifact_path: "/artifacts/reports/report_low.md",
  created_at: "2026-03-23T10:10:00Z",
  markdown: "Brief notes.",
  quality_metadata: {
    structural_score: 0.2,
    word_count: 2,
    section_checklist: {},
    has_tables: false,
    has_metrics: false,
  },
};
