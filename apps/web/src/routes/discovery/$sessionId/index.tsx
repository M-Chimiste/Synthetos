import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  useDiscoveryPapers,
  useDiscoveryProfile,
  useDiscoverySession,
  useTriagePaper,
} from "../../../api/hooks";
import EventStream from "../../../components/EventStream";
import StatusBadge from "../../../components/StatusBadge";

export const Route = createFileRoute("/discovery/$sessionId/")({
  component: DiscoverySessionPage,
});

function DiscoverySessionPage() {
  const { sessionId } = Route.useParams();
  const session = useDiscoverySession(sessionId);
  const profile = useDiscoveryProfile(sessionId);
  const [view, setView] = useState<"stable" | "discovery">("stable");
  const allPapers = useDiscoveryPapers(sessionId, { limit: 500 });
  const papers = useDiscoveryPapers(sessionId, { view, limit: 100 });
  const triage = useTriagePaper();

  if (session.isLoading) {
    return <p className="text-sm text-gray-500">Loading session…</p>;
  }
  if (session.error || !session.data) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load session: {session.error?.message ?? "not found"}
      </div>
    );
  }

  const s = session.data;
  const allItems = allPapers.data?.items ?? [];
  const critique = readObjectField(s.stats, "shortlist_critique");
  const finalizeStats = readObjectField(s.stats, "finalize");
  const stableCount =
    readNumberField(finalizeStats, "stable_view_size") ??
    countViewMembership(allItems, "stable");
  const discoveryCount =
    readNumberField(finalizeStats, "discovery_view_size") ??
    countViewMembership(allItems, "discovery");
  const totalCandidates =
    readNumberField(finalizeStats, "total_cards") ?? allPapers.data?.total ?? 0;

  return (
    <div>
      <Link
        to="/charters/$charterId"
        params={{ charterId: s.charter_id }}
        className="text-sm text-gray-500 hover:text-gray-700"
      >
        &larr; Back to charter
      </Link>

      <div className="mt-2 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Discovery session</h1>
          <p className="mt-1 font-mono text-xs text-gray-500">{s.id}</p>
        </div>
        <StatusBadge status={s.status} />
      </div>

      {(s.status === "failed" || s.error) && (
        <section className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p className="font-medium">Discovery session failed</p>
          {s.error && <p className="mt-1 whitespace-pre-wrap">{s.error}</p>}
        </section>
      )}

      {profile.data && (
        <section className="mt-4 rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="text-xs font-medium uppercase text-gray-500">Query</h2>
          <p className="mt-1 whitespace-pre-wrap text-sm text-gray-800">
            {profile.data.query_text}
          </p>
          {profile.data.notes && (
            <p className="mt-2 whitespace-pre-wrap text-xs text-gray-500">
              {profile.data.notes}
            </p>
          )}
        </section>
      )}

      <section className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Stable view" value={stableCount} />
        <Stat label="Discovery view" value={discoveryCount} />
        <Stat label="Total candidates" value={totalCandidates} />
      </section>

      {s.stats && (
        <section className="mt-4 rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="text-xs font-medium uppercase text-gray-500">Stats</h2>
          <pre className="mt-2 overflow-x-auto text-xs text-gray-700">
            {JSON.stringify(s.stats, null, 2)}
          </pre>
        </section>
      )}

      {critique && (
        <section className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <h2 className="text-xs font-medium uppercase text-amber-700">
            Shortlist critique
          </h2>
          {readStringField(critique, "summary") && (
            <p className="mt-2 text-sm text-amber-900">
              {readStringField(critique, "summary")}
            </p>
          )}
          <CritiqueList label="Coverage gaps" items={readStringList(critique, "coverage_gaps")} />
          <CritiqueList label="Clustering risks" items={readStringList(critique, "clustering_risks")} />
          <CritiqueList label="Score concerns" items={readStringList(critique, "score_concerns")} />
        </section>
      )}

      {s.report_artifact_path && (
        <section className="mt-4">
          <Link
            to="/discovery/$sessionId/report"
            params={{ sessionId }}
            className="text-sm font-medium text-blue-700 hover:text-blue-800"
          >
            View discovery report &rarr;
          </Link>
        </section>
      )}

      <section className="mt-6">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-lg font-medium">Papers</h2>
          <div className="ml-auto flex gap-2">
            <ViewTab active={view === "stable"} onClick={() => setView("stable")}>
              Stable
            </ViewTab>
            <ViewTab
              active={view === "discovery"}
              onClick={() => setView("discovery")}
            >
              Discovery
            </ViewTab>
          </div>
        </div>

        {papers.isLoading && (
          <p className="text-sm text-gray-500">Loading papers…</p>
        )}

        {papers.data && papers.data.items.length === 0 && (
          <p className="text-sm text-gray-500">
            No papers in the {view} view yet.
          </p>
        )}

        <div className="space-y-3">
          {papers.data?.items.map((card) => (
            <div
              key={card.id}
              className="rounded-lg border border-gray-200 bg-white p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">
                    {card.title}
                  </h3>
                  <p className="mt-1 text-xs text-gray-500">
                    {(card.authors ?? []).slice(0, 5).join(", ")}
                    {card.year && <> &middot; {card.year}</>}
                    {card.venue && <> &middot; {card.venue}</>}
                  </p>
                </div>
                <div className="shrink-0 text-right text-xs text-gray-500">
                  <div>score {(card.final_score ?? 0).toFixed(4)}</div>
                  <div className="font-mono">{card.source}</div>
                </div>
              </div>
              {card.metadata_analysis &&
                typeof card.metadata_analysis.one_line_summary === "string" && (
                  <p className="mt-2 text-xs italic text-gray-700">
                    {String(card.metadata_analysis.one_line_summary)}
                  </p>
                )}
              {readStringField(card.metadata_analysis, "escalation_rationale") && (
                <p className="mt-2 text-xs text-gray-700">
                  <span className="font-medium text-gray-900">Escalation:</span>{" "}
                  {readStringField(card.metadata_analysis, "escalation_rationale")}
                </p>
              )}
              {(readNumberField(card.metadata_analysis, "shortlist_fit") !== null ||
                readNumberField(card.metadata_analysis, "relevance_to_problem") !== null) && (
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-gray-600">
                  {readNumberField(card.metadata_analysis, "shortlist_fit") !== null && (
                    <span className="rounded bg-gray-100 px-2 py-1">
                      shortlist fit{" "}
                      {readNumberField(card.metadata_analysis, "shortlist_fit")!.toFixed(2)}
                    </span>
                  )}
                  {readNumberField(card.metadata_analysis, "relevance_to_problem") !== null && (
                    <span className="rounded bg-gray-100 px-2 py-1">
                      relevance{" "}
                      {readNumberField(card.metadata_analysis, "relevance_to_problem")!.toFixed(2)}
                    </span>
                  )}
                </div>
              )}
              {readStringList(card.metadata_analysis, "risks_or_caveats").length > 0 && (
                <p className="mt-2 text-xs text-amber-700">
                  Risks: {readStringList(card.metadata_analysis, "risks_or_caveats").join("; ")}
                </p>
              )}
              {card.abstract && (
                <p className="mt-2 line-clamp-3 text-xs text-gray-700">
                  {card.abstract}
                </p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                {card.pdf_url && (
                  <a
                    className="text-blue-700 hover:underline"
                    href={card.pdf_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    PDF
                  </a>
                )}
                {card.source_url && (
                  <a
                    className="text-blue-700 hover:underline"
                    href={card.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    source
                  </a>
                )}
                <span className="ml-auto inline-flex gap-1">
                  <TriageButton
                    label="Shortlist"
                    onClick={() =>
                      triage.mutate({
                        sessionId,
                        paperId: card.id,
                        triageStatus: "shortlisted",
                      })
                    }
                  />
                  <TriageButton
                    label="Drop"
                    onClick={() =>
                      triage.mutate({
                        sessionId,
                        paperId: card.id,
                        triageStatus: "dropped",
                      })
                    }
                  />
                  <TriageButton
                    label="Escalate"
                    onClick={() =>
                      triage.mutate({
                        sessionId,
                        paperId: card.id,
                        triageStatus: "escalated",
                      })
                    }
                  />
                </span>
                <StatusBadge status={card.triage_status} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-6">
        <h2 className="mb-3 text-lg font-medium">Live events</h2>
        <EventStream charterId={s.charter_id} />
      </section>
    </div>
  );
}

function countViewMembership(items: { view_membership: string[] | null }[], v: string) {
  return items.filter((i) => (i.view_membership ?? []).includes(v)).length;
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function CritiqueList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="mt-3">
      <p className="text-xs font-medium uppercase text-amber-700">{label}</p>
      <p className="mt-1 text-xs text-amber-900">{items.join(" • ")}</p>
    </div>
  );
}

function readObjectField(
  value: Record<string, unknown> | null,
  key: string,
): Record<string, unknown> | null {
  if (!value) {
    return null;
  }
  const field = value[key];
  return field && typeof field === "object" && !Array.isArray(field)
    ? (field as Record<string, unknown>)
    : null;
}

function readStringField(
  value: Record<string, unknown> | null,
  key: string,
): string | null {
  if (!value) {
    return null;
  }
  return typeof value[key] === "string" ? String(value[key]) : null;
}

function readNumberField(
  value: Record<string, unknown> | null,
  key: string,
): number | null {
  if (!value) {
    return null;
  }
  const field = value[key];
  return typeof field === "number" ? field : null;
}

function readStringList(
  value: Record<string, unknown> | null,
  key: string,
): string[] {
  if (!value) {
    return [];
  }
  const field = value[key];
  return Array.isArray(field)
    ? field.filter((item): item is string => typeof item === "string")
    : [];
}

function ViewTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-md px-3 py-1.5 text-sm font-medium " +
        (active
          ? "bg-gray-900 text-white"
          : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50")
      }
    >
      {children}
    </button>
  );
}

function TriageButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-100"
    >
      {label}
    </button>
  );
}
