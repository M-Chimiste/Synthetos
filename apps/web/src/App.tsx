import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";

import {
  API_BASE,
  API_TOKEN,
  createCycle,
  createRun,
  cycleCommand,
  eventSource,
  getCycle,
  getEvidenceSummary,
  getHistoricalComparison,
  getLiteratureTriage,
  getPostmortem,
  getPortfolio,
  getReport,
  getRun,
  getTimeline,
  getVerificationReport,
  getVerificationSummary,
  listCycles,
  listEvidence,
  listExperimentSpecs,
  listRuns,
  listSkills,
  runCommand,
  runEventSource,
  startEvidence,
  startIntake,
} from "./lib/api";
import type {
  CycleDetailResponse,
  CycleSummaryResponse,
  EvidenceCardSummary,
  EvidenceListResponse,
  EvidenceSummaryResponse,
  ExperimentSpecListResponse,
  ExperimentSpecSummary,
  FailurePostmortemDetail,
  HistoricalComparisonResponse,
  HypothesisCardSummary,
  LiteratureTriageResponse,
  PaperCardSummary,
  PortfolioRankingResponse,
  ReportDetail,
  RunDetailResponse,
  RunListResponse,
  RunSummary,
  SkillSummaryResponse,
  TimelineEntry,
  VerificationReportDetail,
  VerificationSummaryResponse,
} from "./lib/types";
import Timeline from "./components/Timeline";

const defaultForm = {
  title: "Phase 1 literature triage cycle",
  problem_statement: "Investigate efficient neural architecture search methods for practical ML research.",
  success_criteria: '{"summary":"Produce a credible literature screening report with a ranked shortlist."}',
  budget_envelope: '{"timebox_hours":4}',
  source_mode: "internal+arxiv",
  keywords: "neural architecture search, efficient deep learning",
  categories: "cs, cs.LG",
  date_from: "2024-01-01",
  date_until: "",
  max_results: "25",
  fulltext_budget: "3",
  stop_conditions: '{"summary":"Literature report generated and shortlist reviewed."}',
  constraints: '{"phase":"phase1"}',
  notes: "Created from the web intake form.",
};

function parseJsonField(value: string): Record<string, unknown> {
  return JSON.parse(value);
}

function parseListField(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function App() {
  const client = useQueryClient();
  const [selectedCycleId, setSelectedCycleId] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [form, setForm] = useState(defaultForm);

  const cyclesQuery = useQuery({
    queryKey: ["cycles"],
    queryFn: listCycles,
    refetchInterval: 10000,
  });

  const cycleDetailQuery = useQuery({
    queryKey: ["cycle", selectedCycleId],
    queryFn: () => getCycle(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
  });

  const skillsQuery = useQuery({
    queryKey: ["skills"],
    queryFn: listSkills,
    refetchInterval: 20000,
  });

  const reportQuery = useQuery({
    queryKey: ["report", selectedReportId],
    queryFn: () => getReport(selectedReportId!),
    enabled: Boolean(selectedReportId),
  });

  const runsQuery = useQuery({
    queryKey: ["runs", selectedCycleId],
    queryFn: () => listRuns(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 5000,
  });

  const runDetailQuery = useQuery({
    queryKey: ["run", selectedRunId],
    queryFn: () => getRun(selectedRunId!),
    enabled: Boolean(selectedRunId),
  });

  const verificationSummaryQuery = useQuery({
    queryKey: ["verificationSummary", selectedCycleId],
    queryFn: () => getVerificationSummary(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 5000,
  });

  const timelineQuery = useQuery({
    queryKey: ["timeline", selectedCycleId],
    queryFn: () => getTimeline(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 5000,
  });

  const verificationReportQuery = useQuery({
    queryKey: ["verificationReport", runDetailQuery.data?.verification_report?.public_id],
    queryFn: () => getVerificationReport(runDetailQuery.data!.verification_report!.public_id),
    enabled: Boolean(runDetailQuery.data?.verification_report?.public_id),
  });

  const postmortemQuery = useQuery({
    queryKey: ["postmortem", runDetailQuery.data?.postmortem?.public_id],
    queryFn: () => getPostmortem(runDetailQuery.data!.postmortem!.public_id),
    enabled: Boolean(runDetailQuery.data?.postmortem?.public_id),
  });

  const historicalComparisonQuery = useQuery({
    queryKey: ["historicalComparison", selectedRunId],
    queryFn: () => getHistoricalComparison(selectedRunId!),
    enabled: Boolean(selectedRunId),
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (!selectedCycleId && cyclesQuery.data?.items?.[0]) {
      setSelectedCycleId(cyclesQuery.data.items[0].cycle.public_id);
    }
  }, [cyclesQuery.data, selectedCycleId]);

  useEffect(() => {
    if (!selectedRunId && runsQuery.data?.items?.[0]) {
      setSelectedRunId(runsQuery.data.items[0].public_id);
    }
  }, [runsQuery.data, selectedRunId]);

  useEffect(() => {
    if (!selectedCycleId) {
      return;
    }
    const source = eventSource(selectedCycleId);
    source.onmessage = () => {
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["cycles"] });
      client.invalidateQueries({ queryKey: ["verificationSummary", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["timeline", selectedCycleId] });
    };
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [client, selectedCycleId]);

  useEffect(() => {
    if (!selectedRunId) {
      return;
    }
    const source = runEventSource(selectedRunId);
    source.onmessage = () => {
      client.invalidateQueries({ queryKey: ["run", selectedRunId] });
      client.invalidateQueries({ queryKey: ["runs", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["verificationSummary", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["historicalComparison", selectedRunId] });
      client.invalidateQueries({ queryKey: ["timeline", selectedCycleId] });
      const verificationReportId = runDetailQuery.data?.verification_report?.public_id;
      if (verificationReportId) {
        client.invalidateQueries({ queryKey: ["verificationReport", verificationReportId] });
      }
      const postmortemId = runDetailQuery.data?.postmortem?.public_id;
      if (postmortemId) {
        client.invalidateQueries({ queryKey: ["postmortem", postmortemId] });
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [client, runDetailQuery.data?.postmortem?.public_id, runDetailQuery.data?.verification_report?.public_id, selectedCycleId, selectedRunId]);

  const createMutation = useMutation({
    mutationFn: async () =>
      createCycle({
        title: form.title,
        problem_statement: form.problem_statement,
        success_criteria: parseJsonField(form.success_criteria),
        budget_envelope: parseJsonField(form.budget_envelope),
        source_scope: {
          mode: form.source_mode,
          keywords: parseListField(form.keywords),
          categories: parseListField(form.categories),
          date_from: form.date_from || null,
          date_until: form.date_until || null,
          max_results: Number(form.max_results || "25"),
          fulltext_budget: {
            max_fetches: Number(form.fulltext_budget || "3"),
          },
        },
        stop_conditions: parseJsonField(form.stop_conditions),
        constraints: parseJsonField(form.constraints),
        notes: form.notes,
      }),
    onSuccess: (payload) => {
      setSelectedCycleId(payload.cycle.public_id);
      client.invalidateQueries({ queryKey: ["cycles"] });
      client.invalidateQueries({ queryKey: ["cycle", payload.cycle.public_id] });
    },
  });

  const commandMutation = useMutation({
    mutationFn: async (command: string) => cycleCommand(selectedCycleId!, command),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["cycles"] });
      client.invalidateQueries({ queryKey: ["literature", selectedCycleId] });
    },
  });

  const intakeMutation = useMutation({
    mutationFn: async () => startIntake(selectedCycleId!),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["cycles"] });
    },
  });

  const literatureQuery = useQuery({
    queryKey: ["literature", selectedCycleId],
    queryFn: () => getLiteratureTriage(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 5000,
  });

  const evidenceQuery = useQuery({
    queryKey: ["evidence", selectedCycleId],
    queryFn: () => listEvidence(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 10000,
  });

  const evidenceSummaryQuery = useQuery({
    queryKey: ["evidenceSummary", selectedCycleId],
    queryFn: () => getEvidenceSummary(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 10000,
  });

  const portfolioQuery = useQuery({
    queryKey: ["portfolio", selectedCycleId],
    queryFn: () => getPortfolio(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 10000,
  });

  const experimentSpecsQuery = useQuery({
    queryKey: ["experimentSpecs", selectedCycleId],
    queryFn: () => listExperimentSpecs(selectedCycleId!),
    enabled: Boolean(selectedCycleId),
    refetchInterval: 10000,
  });

  const evidenceMutation = useMutation({
    mutationFn: async () => startEvidence(selectedCycleId!),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["cycles"] });
      client.invalidateQueries({ queryKey: ["evidence", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["evidenceSummary", selectedCycleId] });
    },
  });

  const createRunMutation = useMutation({
    mutationFn: async (specId: string) => createRun(specId),
    onSuccess: (payload) => {
      setSelectedRunId(payload.run.public_id);
      client.invalidateQueries({ queryKey: ["runs", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["run", payload.run.public_id] });
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
    },
  });

  const runCommandMutation = useMutation({
    mutationFn: async ({ runId, command }: { runId: string; command: "pause" | "cancel" | "retry" }) =>
      runCommand(runId, command),
    onSuccess: (_, variables) => {
      client.invalidateQueries({ queryKey: ["run", variables.runId] });
      client.invalidateQueries({ queryKey: ["runs", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
    },
  });

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(15,118,110,0.14),_transparent_35%),linear-gradient(180deg,_#f8fafc_0%,_#eef2ff_100%)] px-4 py-6 text-ink md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="panel overflow-hidden p-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Synthetos</p>
              <h1 className="text-3xl font-semibold">Phase 4 Verification Tower</h1>
              <p className="mt-2 max-w-2xl text-sm text-slate-600">
                Create a cycle, drive it through ideation, launch bounded experiment runs,
                and inspect verification outcomes, postmortems, and same-charter research memory
                from the same local-first control plane.
              </p>
            </div>
            <div className="rounded-2xl bg-slate-900 px-4 py-3 text-xs text-slate-100">
              <div>API: {API_BASE}</div>
              <div>Token: {API_TOKEN}</div>
            </div>
          </div>
        </header>

        <section className="grid gap-6 xl:grid-cols-[1.2fr,1fr]">
          <div className="panel p-5">
            <h2 className="mb-4 text-xl font-semibold">Create Research Cycle</h2>
            <form
              className="grid gap-3 md:grid-cols-2"
              onSubmit={(event: FormEvent) => {
                event.preventDefault();
                createMutation.mutate();
              }}
            >
              <label className="space-y-1 md:col-span-2">
                <span className="text-sm font-medium">Title</span>
                <input className="field" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
              </label>
              <label className="space-y-1 md:col-span-2">
                <span className="text-sm font-medium">Problem Statement</span>
                <textarea className="field min-h-24" value={form.problem_statement} onChange={(event) => setForm({ ...form, problem_statement: event.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Source Mode</span>
                <input className="field" value={form.source_mode} onChange={(event) => setForm({ ...form, source_mode: event.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Keywords</span>
                <input className="field" value={form.keywords} onChange={(event) => setForm({ ...form, keywords: event.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Categories</span>
                <input className="field" value={form.categories} onChange={(event) => setForm({ ...form, categories: event.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Max Results</span>
                <input className="field" value={form.max_results} onChange={(event) => setForm({ ...form, max_results: event.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Date From</span>
                <input className="field" value={form.date_from} onChange={(event) => setForm({ ...form, date_from: event.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Date Until</span>
                <input className="field" value={form.date_until} onChange={(event) => setForm({ ...form, date_until: event.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="text-sm font-medium">Fulltext Budget</span>
                <input className="field" value={form.fulltext_budget} onChange={(event) => setForm({ ...form, fulltext_budget: event.target.value })} />
              </label>
              {(["success_criteria", "budget_envelope", "stop_conditions", "constraints"] as const).map((key) => (
                <label className="space-y-1" key={key}>
                  <span className="text-sm font-medium">{key}</span>
                  <textarea className="field min-h-20 font-mono text-xs" value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />
                </label>
              ))}
              <label className="space-y-1 md:col-span-2">
                <span className="text-sm font-medium">Notes</span>
                <textarea className="field min-h-20" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
              </label>
              <div className="md:col-span-2 flex items-center gap-3">
                <button className="button-primary" type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? "Creating..." : "Create Cycle"}
                </button>
                {createMutation.error ? (
                  <p className="text-sm text-ember">{String(createMutation.error)}</p>
                ) : null}
              </div>
            </form>
          </div>

          <div className="panel p-5">
            <h2 className="mb-4 text-xl font-semibold">Cycle Index</h2>
            <div className="space-y-3">
              {(cyclesQuery.data?.items ?? []).map((item: CycleSummaryResponse) => (
                <button
                  key={item.cycle.public_id}
                  className={`w-full rounded-2xl border p-4 text-left transition ${
                    selectedCycleId === item.cycle.public_id
                      ? "border-accent bg-teal-50"
                      : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                  onClick={() => setSelectedCycleId(item.cycle.public_id)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold">{item.charter.title}</div>
                      <div className="text-xs text-slate-500">{item.cycle.public_id}</div>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                      {item.cycle.current_status}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.5fr,1fr]">
          <CycleDetailPanel
            detail={cycleDetailQuery.data}
            currentRun={runsQuery.data?.items?.[0]}
            onCommand={(command) => commandMutation.mutate(command)}
            onStartIntake={() => intakeMutation.mutate()}
            intakePending={intakeMutation.isPending}
            onStartEvidence={() => evidenceMutation.mutate()}
            evidencePending={evidenceMutation.isPending}
            onSelectReport={setSelectedReportId}
            verificationSummary={verificationSummaryQuery.data}
            timelineItems={timelineQuery.data?.items}
          />
          <aside className="space-y-6">
            <LiteraturePanel triage={literatureQuery.data} />
            <EvidencePanel evidence={evidenceQuery.data} summary={evidenceSummaryQuery.data} />
            <HypothesisPortfolioPanel portfolio={portfolioQuery.data} />
            <ExperimentSpecPanel
              specs={experimentSpecsQuery.data}
              onStartRun={(specId) => createRunMutation.mutate(specId)}
              startingSpecId={createRunMutation.variables ?? null}
            />
            <RunQueuePanel
              runs={runsQuery.data}
              selectedRunId={selectedRunId}
              onSelectRun={setSelectedRunId}
            />
            <RunTelemetryPanel
              detail={runDetailQuery.data}
              verificationReport={verificationReportQuery.data}
              postmortem={postmortemQuery.data}
              historicalComparison={historicalComparisonQuery.data}
              onRunCommand={(command) => {
                if (selectedRunId) {
                  runCommandMutation.mutate({ runId: selectedRunId, command });
                }
              }}
              commandPending={runCommandMutation.isPending}
              onSelectReport={setSelectedReportId}
            />
            <SkillsPanel skills={skillsQuery.data?.items ?? []} />
            <ReportPanel report={reportQuery.data} />
          </aside>
        </section>
      </div>
    </main>
  );
}

function CycleDetailPanel({
  detail,
  currentRun,
  onCommand,
  onStartIntake,
  intakePending,
  onStartEvidence,
  evidencePending,
  onSelectReport,
  verificationSummary,
  timelineItems,
}: {
  detail?: CycleDetailResponse;
  currentRun?: RunSummary;
  onCommand: (command: string) => void;
  onStartIntake: () => void;
  intakePending: boolean;
  onStartEvidence: () => void;
  evidencePending: boolean;
  onSelectReport: (reportId: string) => void;
  verificationSummary?: VerificationSummaryResponse;
  timelineItems?: TimelineEntry[] | null;
}) {
  if (!detail) {
    return <section className="panel p-6">Select a cycle to inspect Phase 0 state.</section>;
  }

  return (
    <section className="panel p-6">
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Cycle Detail</p>
          <h2 className="text-2xl font-semibold">{detail.charter.title}</h2>
          <p className="mt-1 text-sm text-slate-600">{detail.charter.problem_statement}</p>
        </div>
        <div className="flex gap-2">
          {detail.cycle.current_status === "ready" && (
            <>
              <button
                className="button-primary"
                onClick={onStartIntake}
                disabled={intakePending}
              >
                {intakePending ? "Starting..." : "Start Literature Intake"}
              </button>
              <button
                className="button-primary"
                onClick={onStartEvidence}
                disabled={evidencePending}
              >
                {evidencePending ? "Starting..." : "Start Evidence Extraction"}
              </button>
            </>
          )}
          <button className="button-secondary" onClick={() => onCommand("pause")}>Pause</button>
          <button className="button-secondary" onClick={() => onCommand("resume")}>Resume</button>
          <button className="button-secondary" onClick={() => onCommand("cancel")}>Cancel</button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <InfoCard label="Cycle ID" value={detail.cycle.public_id} />
        <InfoCard label="Current Status" value={detail.cycle.current_status} />
        <InfoCard
          label="Current Run"
          value={
            currentRun
              ? `${currentRun.status} (${currentRun.execution_profile})${
                  currentRun.verification_outcome ? ` · ${currentRun.verification_outcome}` : ""
                }`
              : "none"
          }
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          {verificationSummary ? (
            <Subsection title="Verification Summary">
              <div className="grid gap-3 md:grid-cols-2">
                <InfoCard label="Robust" value={String(verificationSummary.robust_count)} />
                <InfoCard label="Tentative" value={String(verificationSummary.tentative_count)} />
                <InfoCard label="Rejected" value={String(verificationSummary.rejected_count)} />
                <InfoCard label="Invalid" value={String(verificationSummary.invalid_count)} />
              </div>
              {verificationSummary.latest_cycle_summary_report_public_id ? (
                <button
                  className="button-secondary"
                  onClick={() =>
                    onSelectReport(verificationSummary.latest_cycle_summary_report_public_id!)
                  }
                >
                  Open Cycle Verification Summary
                </button>
              ) : null}
              {verificationSummary.next_step_recommendations.length > 0 ? (
                <div className="space-y-2">
                  {verificationSummary.next_step_recommendations.map((item) => (
                    <div key={`${item.recommendation_type}-${item.rationale}`} className="rounded-xl border border-slate-200 p-3">
                      <div className="font-medium">{item.recommendation_type}</div>
                      <div className="text-sm text-slate-600">{item.rationale}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </Subsection>
          ) : null}
          <Subsection title="Recent Jobs">
            {detail.recent_jobs.map((job) => (
              <div key={job.public_id} className="rounded-xl border border-slate-200 p-3">
                <div className="font-medium">{job.operator_name}</div>
                <div className="text-xs text-slate-500">
                  {job.public_id} · {job.status} · attempts {job.attempts}/{job.max_attempts}
                </div>
                {job.last_error ? <div className="mt-1 text-sm text-ember">{job.last_error}</div> : null}
              </div>
            ))}
          </Subsection>
          <Subsection title="Bound Skills">
            {detail.bound_skills.map((skill) => (
              <div key={skill.public_id} className="rounded-xl border border-slate-200 p-3">
                <div className="font-medium">{skill.operator_name}</div>
                <div className="text-xs text-slate-500">{skill.binding_reason}</div>
              </div>
            ))}
          </Subsection>
        </div>
        <div className="space-y-4">
          <Subsection title="Event Timeline">
            <Timeline items={timelineItems ?? []} />
          </Subsection>
          <Subsection title="Reports">
            {detail.reports.map((report) => (
              <button
                key={report.public_id}
                className="w-full rounded-xl border border-slate-200 p-3 text-left hover:bg-slate-50"
                onClick={() => onSelectReport(report.public_id)}
              >
                <div className="font-medium">{report.title}</div>
                <div className="text-xs text-slate-500">{report.report_type}</div>
              </button>
            ))}
          </Subsection>
        </div>
      </div>
    </section>
  );
}

function LiteraturePanel({ triage }: { triage?: LiteratureTriageResponse }) {
  if (!triage || triage.total_papers === 0) {
    return null;
  }
  const statusColor: Record<string, string> = {
    retrieved: "bg-slate-100 text-slate-700",
    screened: "bg-blue-100 text-blue-700",
    shortlisted: "bg-emerald-100 text-emerald-700",
    html_fetched: "bg-teal-100 text-teal-700",
    pdf_fetched: "bg-teal-100 text-teal-700",
    rejected: "bg-red-100 text-red-700",
  };
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Literature Triage</p>
        <h2 className="text-xl font-semibold">Paper Pipeline</h2>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
        <div>Total: <strong>{triage.total_papers}</strong></div>
        <div>Screened: <strong>{triage.screened_count}</strong></div>
        <div>Shortlisted: <strong>{triage.shortlisted_count}</strong></div>
        <div>Escalated: <strong>{triage.escalated_count}</strong></div>
      </div>
      <div className="max-h-80 space-y-2 overflow-y-auto">
            {triage.papers.map((paper: PaperCardSummary) => (
          <div key={paper.public_id} className="rounded-xl border border-slate-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-sm">{paper.title}</div>
                <div className="text-xs text-slate-500">
                  {paper.source_type} · {paper.external_id}
                </div>
              </div>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${statusColor[paper.lifecycle_status] ?? "bg-slate-100 text-slate-700"}`}>
                {paper.lifecycle_status}
              </span>
            </div>
            {paper.triage_score != null && (
              <div className="mt-1 text-xs text-slate-500">
                Score: {paper.triage_score.toFixed(2)}
                {paper.shortlist_rank != null && ` · Rank #${paper.shortlist_rank}`}
              </div>
            )}
            {paper.triage_rationale && (
              <div className="mt-2 text-xs text-slate-600">
                <strong>Triage:</strong> {paper.triage_rationale}
              </div>
            )}
            {paper.shortlist_reason && (
              <div className="mt-1 text-xs text-slate-600">
                <strong>Shortlist:</strong> {paper.shortlist_reason}
              </div>
            )}
            {paper.escalation_reason && (
              <div className="mt-1 text-xs text-slate-600">
                <strong>Escalation:</strong> {paper.escalation_reason}
                {paper.escalation_type ? ` (${paper.escalation_type})` : ""}
              </div>
            )}
            {paper.retrieval_provenance_summary.length > 0 && (
              <div className="mt-1 text-xs text-slate-500">
                <strong>Provenance:</strong> {paper.retrieval_provenance_summary.join(", ")}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function EvidencePanel({ evidence, summary }: { evidence?: EvidenceListResponse; summary?: EvidenceSummaryResponse }) {
  if (!evidence || evidence.total === 0) {
    return null;
  }
  const strengthColor: Record<string, string> = {
    strong: "bg-emerald-100 text-emerald-700",
    moderate: "bg-blue-100 text-blue-700",
    weak: "bg-amber-100 text-amber-700",
    conflicting: "bg-red-100 text-red-700",
  };
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Evidence Extraction</p>
        <h2 className="text-xl font-semibold">Evidence Cards</h2>
      </div>
      {summary && (
        <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
          <div>Total: <strong>{summary.total_evidence}</strong></div>
          <div>Conflicts: <strong>{summary.conflicts_detected}</strong></div>
          <div>Redundancies: <strong>{summary.redundancies_detected}</strong></div>
          {Object.entries(summary.by_type).map(([type, count]) => (
            <div key={type}>{type}: <strong>{count}</strong></div>
          ))}
        </div>
      )}
      <div className="max-h-80 space-y-2 overflow-y-auto">
        {evidence.items.map((card: EvidenceCardSummary) => (
          <div key={card.public_id} className="rounded-xl border border-slate-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{card.claim}</div>
                <div className="text-xs text-slate-500">
                  {card.evidence_type} · {card.read_depth} · paper {card.paper_public_id.slice(0, 8)}...
                </div>
              </div>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${strengthColor[card.strength] ?? "bg-slate-100 text-slate-700"}`}>
                {card.strength}
              </span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Relevance: {card.relevance_score.toFixed(2)}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function HypothesisPortfolioPanel({ portfolio }: { portfolio?: PortfolioRankingResponse }) {
  if (!portfolio || portfolio.total === 0) {
    return null;
  }
  const statusColor: Record<string, string> = {
    proposed: "bg-slate-100 text-slate-700",
    active: "bg-blue-100 text-blue-700",
    validated: "bg-emerald-100 text-emerald-700",
    rejected: "bg-red-100 text-red-700",
    parked: "bg-amber-100 text-amber-700",
  };
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Hypothesis Portfolio</p>
        <h2 className="text-xl font-semibold">Ranked Hypotheses</h2>
        <div className="mt-1 text-xs text-slate-500">
          Method: {portfolio.ranking_method} · Total: {portfolio.total}
        </div>
      </div>
      <div className="max-h-80 space-y-2 overflow-y-auto">
        {portfolio.hypotheses.map((hyp: HypothesisCardSummary) => (
          <div key={hyp.public_id} className="rounded-xl border border-slate-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">
                  {hyp.portfolio_rank != null && <span className="mr-1 text-slate-400">#{hyp.portfolio_rank}</span>}
                  {hyp.title}
                </div>
                {hyp.portfolio_score != null && (
                  <div className="text-xs text-slate-500">
                    Score: {hyp.portfolio_score.toFixed(2)}
                  </div>
                )}
              </div>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${statusColor[hyp.status] ?? "bg-slate-100 text-slate-700"}`}>
                {hyp.status}
              </span>
            </div>
            <div className="mt-1 flex gap-3 text-xs text-slate-500">
              {hyp.novelty_score != null && <span>Novelty: {hyp.novelty_score.toFixed(2)}</span>}
              {hyp.feasibility_score != null && <span>Feasibility: {hyp.feasibility_score.toFixed(2)}</span>}
              {hyp.impact_score != null && <span>Impact: {hyp.impact_score.toFixed(2)}</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ExperimentSpecPanel({
  specs,
  onStartRun,
  startingSpecId,
}: {
  specs?: ExperimentSpecListResponse;
  onStartRun: (specId: string) => void;
  startingSpecId?: string | null;
}) {
  if (!specs || specs.total === 0) {
    return null;
  }
  const statusColor: Record<string, string> = {
    draft: "bg-slate-100 text-slate-700",
    approved: "bg-blue-100 text-blue-700",
    running: "bg-amber-100 text-amber-700",
    completed: "bg-emerald-100 text-emerald-700",
    failed: "bg-red-100 text-red-700",
  };
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Experiment Specs</p>
        <h2 className="text-xl font-semibold">Planned Experiments</h2>
      </div>
      <div className="max-h-80 space-y-2 overflow-y-auto">
        {specs.items.map((spec: ExperimentSpecSummary) => (
          <div key={spec.public_id} className="rounded-xl border border-slate-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{spec.title}</div>
                <div className="text-xs text-slate-500">
                  Hypothesis: {spec.hypothesis_public_id.slice(0, 8)}...
                  {spec.estimated_runtime_minutes != null && ` · ~${spec.estimated_runtime_minutes}min`}
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor[spec.status] ?? "bg-slate-100 text-slate-700"}`}>
                  {spec.status}
                </span>
                {spec.gpu_required && (
                  <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">GPU</span>
                )}
                {(spec.status === "valid" || spec.status === "approved") && (
                  <button
                    className="button-secondary text-xs"
                    onClick={() => onStartRun(spec.public_id)}
                  >
                    {startingSpecId === spec.public_id ? "Starting..." : "Start Run"}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function RunQueuePanel({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs?: RunListResponse;
  selectedRunId?: string | null;
  onSelectRun: (runId: string) => void;
}) {
  if (!runs || runs.total === 0) {
    return null;
  }
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Run Queue</p>
        <h2 className="text-xl font-semibold">Execution Runs</h2>
      </div>
      <div className="space-y-3">
        {runs.items.map((run) => (
          <button
            key={run.public_id}
            className={`w-full rounded-xl border p-3 text-left ${
              selectedRunId === run.public_id ? "border-accent bg-teal-50" : "border-slate-200"
            }`}
            onClick={() => onSelectRun(run.public_id)}
          >
            <div className="font-medium">{run.public_id}</div>
            <div className="text-xs text-slate-500">
              {run.status} · {run.execution_profile}
              {run.verification_outcome ? ` · ${run.verification_outcome}` : ""}
              {run.failure_classification ? ` · ${run.failure_classification}` : ""}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

function RunTelemetryPanel({
  detail,
  verificationReport,
  postmortem,
  historicalComparison,
  onRunCommand,
  commandPending,
  onSelectReport,
}: {
  detail?: RunDetailResponse;
  verificationReport?: VerificationReportDetail;
  postmortem?: FailurePostmortemDetail;
  historicalComparison?: HistoricalComparisonResponse;
  onRunCommand: (command: "pause" | "cancel" | "retry") => void;
  commandPending: boolean;
  onSelectReport: (reportId: string) => void;
}) {
  if (!detail) {
    return null;
  }
  return (
    <section className="panel p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Run Verification</p>
          <h2 className="text-xl font-semibold">{detail.run.public_id}</h2>
          <p className="text-xs text-slate-500">
            {detail.run.status} · {detail.run.execution_profile}
            {detail.run.verification_outcome ? ` · ${detail.run.verification_outcome}` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <button className="button-secondary" disabled={commandPending} onClick={() => onRunCommand("pause")}>Pause</button>
          <button className="button-secondary" disabled={commandPending} onClick={() => onRunCommand("cancel")}>Cancel</button>
          <button className="button-secondary" disabled={commandPending} onClick={() => onRunCommand("retry")}>Retry</button>
        </div>
      </div>
      <div className="mb-4 grid gap-3 md:grid-cols-2">
        <InfoCard label="Artifact Root" value={detail.run.artifact_root} />
        <InfoCard label="Patch Archive" value={detail.run.patch_archive_path ?? "none"} />
      </div>
      <div className="space-y-3">
        {verificationReport ? (
          <Subsection title="Verification">
            <div className="rounded-xl border border-slate-200 p-3">
              <div className="font-medium">{verificationReport.outcome}</div>
              <div className="mt-1 text-sm text-slate-600">{verificationReport.reviewer_summary}</div>
              {verificationReport.directional_signal ? (
                <div className="mt-2 text-sm text-slate-600">
                  <strong>Directional signal:</strong> {verificationReport.directional_signal}
                </div>
              ) : null}
              {verificationReport.directional_signal_detail?.frontier ? (
                <div className="mt-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                  <div className="font-medium">
                    Frontier · {verificationReport.directional_signal_detail.frontier.metric_name ?? "primary metric"}
                  </div>
                  <div className="mt-1">
                    Current {String(verificationReport.directional_signal_detail.frontier.current_value ?? "n/a")}
                    {" "}· Best {String(verificationReport.directional_signal_detail.frontier.best_value)}
                    {" "}· Runs since improvement {String(verificationReport.directional_signal_detail.frontier.runs_since_improvement)}
                  </div>
                </div>
              ) : null}
              {verificationReport.directional_signal_detail?.threshold_warning ? (
                <div className="mt-2 text-sm text-amber-700">
                  {verificationReport.directional_signal_detail.threshold_warning}
                </div>
              ) : null}
              {(verificationReport.self_critic_result?.flags ?? []).length > 0 ? (
                <div className="mt-2 space-y-2">
                  {(verificationReport.self_critic_result?.flags ?? []).map((flag) => (
                    <div
                      key={`${flag.severity}-${flag.issue}`}
                      className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs text-slate-700"
                    >
                      <strong>{flag.severity}:</strong> {flag.issue}
                    </div>
                  ))}
                </div>
              ) : null}
              {verificationReport.rerun_note ? (
                <div className="mt-2 text-sm text-slate-600">
                  <strong>Replay guidance:</strong> {verificationReport.rerun_note}
                </div>
              ) : null}
              <pre className="mt-2 overflow-auto rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                {JSON.stringify(verificationReport.baseline_comparison, null, 2)}
              </pre>
            </div>
          </Subsection>
        ) : null}
        {historicalComparison ? (
          <Subsection title="Same-Charter History">
            <div className="rounded-xl border border-slate-200 p-3 text-sm text-slate-700">
              Compared against {historicalComparison.total_prior_runs} prior runs using
              the <strong> {historicalComparison.comparison_scope.split("_").join(" ")} </strong>
              scope.
            </div>
            {(historicalComparison.comparisons ?? []).slice(0, 6).map((item, index) => (
              <div key={`${item.prior_run_public_id}-${item.metric}-${index}`} className="rounded-xl border border-slate-200 p-3">
                <div className="font-medium">
                  {String(item.metric ?? "metric")} · prior {String(item.prior_run_public_id ?? "unknown")}
                </div>
                <div className="text-sm text-slate-600">
                  {String(item.prior_value ?? "n/a")} → {String(item.current_value ?? "n/a")}
                  {" "}({String(item.delta ?? "n/a")})
                </div>
              </div>
            ))}
            {(historicalComparison.memory_references ?? []).slice(0, 4).map((item, index) => (
              <div key={`${item.prior_run_public_id}-${index}`} className="rounded-xl border border-slate-200 p-3">
                <div className="font-medium">
                  Memory from {String(item.prior_run_public_id ?? "prior run")}
                </div>
                <div className="text-sm text-slate-600">
                  {String(item.verification_summary ?? item.root_cause_summary ?? "No summary available")}
                </div>
              </div>
            ))}
          </Subsection>
        ) : null}
        {postmortem ? (
          <Subsection title="Postmortem">
            <div className="rounded-xl border border-slate-200 p-3">
              <div className="font-medium">
                {postmortem.failure_class} · {postmortem.failure_stage}
              </div>
              <div className="mt-1 text-sm text-slate-600">{postmortem.root_cause_summary}</div>
              {(postmortem.remediation_suggestions ?? []).length > 0 ? (
                <div className="mt-2 space-y-2">
                  {(postmortem.remediation_suggestions ?? []).map((item, index) => (
                    <div key={`${item.category}-${index}`} className="rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                      <strong>{String(item.category ?? "general")}:</strong> {String(item.suggestion ?? "")}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </Subsection>
        ) : null}
        {detail.reports.length > 0 ? (
          <Subsection title="Report Links">
            {detail.reports.map((report) => (
              <button
                key={report.public_id}
                className="w-full rounded-xl border border-slate-200 p-3 text-left hover:bg-slate-50"
                onClick={() => onSelectReport(report.public_id)}
              >
                <div className="font-medium">{report.title}</div>
                <div className="text-xs text-slate-500">{report.report_type}</div>
              </button>
            ))}
          </Subsection>
        ) : null}
        <Subsection title="Telemetry">
          {(detail.telemetry_events ?? []).slice(-12).reverse().map((event) => (
            <div key={event.public_id} className="rounded-xl border border-slate-200 p-3">
              <div className="font-medium">{event.event_type}</div>
              <div className="text-xs text-slate-500">
                {new Date(event.created_at).toLocaleString()}
                {event.stream ? ` · ${event.stream}` : ""}
              </div>
              {event.message ? <div className="mt-2 text-sm text-slate-700">{event.message}</div> : null}
              <pre className="mt-2 overflow-auto rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                {JSON.stringify(event.payload, null, 2)}
              </pre>
            </div>
          ))}
        </Subsection>
      </div>
    </section>
  );
}

function SkillsPanel({ skills }: { skills: SkillSummaryResponse[] }) {
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Skill Catalog</p>
        <h2 className="text-xl font-semibold">Repo-Visible Skills</h2>
      </div>
      <div className="space-y-3">
        {skills.map((item) => (
          <div key={item.definition.public_id} className="rounded-xl border border-slate-200 p-3">
            <div className="font-medium">{item.definition.skill_key}</div>
            <div className="text-xs text-slate-500">
              {item.definition.phase} · {item.latest_version?.version ?? "no version"}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReportPanel({ report }: { report?: ReportDetail }) {
  return (
    <section className="panel p-5">
      <div className="mb-4">
        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Report Viewer</p>
        <h2 className="text-xl font-semibold">{report?.title ?? "Select a report"}</h2>
      </div>
      {report ? (
        <article className="prose prose-slate max-w-none text-sm">
          <ReactMarkdown>{report.markdown}</ReactMarkdown>
        </article>
      ) : (
        <p className="text-sm text-slate-600">Pick a report from the cycle detail panel.</p>
      )}
    </section>
  );
}

function Subsection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">{title}</h3>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-2 font-semibold">{value}</div>
    </div>
  );
}
