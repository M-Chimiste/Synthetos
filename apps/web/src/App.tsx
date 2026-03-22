import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";

import {
  API_BASE,
  API_TOKEN,
  createCycle,
  cycleCommand,
  eventSource,
  getCycle,
  getLiteratureTriage,
  getReport,
  listCycles,
  listSkills,
  startIntake,
} from "./lib/api";
import type { CycleDetailResponse, CycleSummaryResponse, LiteratureTriageResponse, PaperCardSummary, ReportDetail, SkillSummaryResponse } from "./lib/types";

const defaultForm = {
  title: "Phase 0 bootstrap cycle",
  problem_statement: "Create the durable control-plane foundation for the ML laboratory.",
  success_criteria: '{"summary":"Cycle reaches ready and produces an initialization report."}',
  budget_envelope: '{"timebox_hours":4}',
  source_scope: '{"mode":"internal+arxiv"}',
  stop_conditions: '{"summary":"Initialization report is available."}',
  constraints: '{"phase":"phase0"}',
  notes: "Created from the web shell.",
};

function parseJsonField(value: string): Record<string, unknown> {
  return JSON.parse(value);
}

export default function App() {
  const client = useQueryClient();
  const [selectedCycleId, setSelectedCycleId] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
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

  useEffect(() => {
    if (!selectedCycleId && cyclesQuery.data?.items?.[0]) {
      setSelectedCycleId(cyclesQuery.data.items[0].cycle.public_id);
    }
  }, [cyclesQuery.data, selectedCycleId]);

  useEffect(() => {
    if (!selectedCycleId) {
      return;
    }
    const source = eventSource(selectedCycleId);
    source.onmessage = () => {
      client.invalidateQueries({ queryKey: ["cycle", selectedCycleId] });
      client.invalidateQueries({ queryKey: ["cycles"] });
    };
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [client, selectedCycleId]);

  const createMutation = useMutation({
    mutationFn: async () =>
      createCycle({
        title: form.title,
        problem_statement: form.problem_statement,
        success_criteria: parseJsonField(form.success_criteria),
        budget_envelope: parseJsonField(form.budget_envelope),
        source_scope: parseJsonField(form.source_scope),
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

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(15,118,110,0.14),_transparent_35%),linear-gradient(180deg,_#f8fafc_0%,_#eef2ff_100%)] px-4 py-6 text-ink md:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="panel overflow-hidden p-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Synthetos</p>
              <h1 className="text-3xl font-semibold">Phase 1 Control Tower</h1>
              <p className="mt-2 max-w-2xl text-sm text-slate-600">
                Create a cycle, start literature intake, watch the pipeline triage papers,
                and browse shortlists, reports, and the skill catalog.
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
              {(["success_criteria", "budget_envelope", "source_scope", "stop_conditions", "constraints"] as const).map((key) => (
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
            onCommand={(command) => commandMutation.mutate(command)}
            onStartIntake={() => intakeMutation.mutate()}
            intakePending={intakeMutation.isPending}
            onSelectReport={setSelectedReportId}
          />
          <aside className="space-y-6">
            <LiteraturePanel triage={literatureQuery.data} />
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
  onCommand,
  onStartIntake,
  intakePending,
  onSelectReport,
}: {
  detail?: CycleDetailResponse;
  onCommand: (command: string) => void;
  onStartIntake: () => void;
  intakePending: boolean;
  onSelectReport: (reportId: string) => void;
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
            <button
              className="button-primary"
              onClick={onStartIntake}
              disabled={intakePending}
            >
              {intakePending ? "Starting..." : "Start Literature Intake"}
            </button>
          )}
          <button className="button-secondary" onClick={() => onCommand("pause")}>Pause</button>
          <button className="button-secondary" onClick={() => onCommand("resume")}>Resume</button>
          <button className="button-secondary" onClick={() => onCommand("cancel")}>Cancel</button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <InfoCard label="Cycle ID" value={detail.cycle.public_id} />
        <InfoCard label="Current Status" value={detail.cycle.current_status} />
        <InfoCard label="Snapshot" value={detail.current_state_snapshot?.state ?? "none"} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
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
            {detail.recent_events.map((event) => (
              <div key={event.public_id} className="rounded-xl border border-slate-200 p-3">
                <div className="font-medium">{event.event_type}</div>
                <div className="text-xs text-slate-500">
                  #{event.sequence_id} · {new Date(event.created_at).toLocaleString()}
                </div>
                <pre className="mt-2 overflow-auto rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                  {JSON.stringify(event.payload, null, 2)}
                </pre>
              </div>
            ))}
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
          </div>
        ))}
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

