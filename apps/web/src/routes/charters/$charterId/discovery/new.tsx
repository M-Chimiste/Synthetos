import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useStartDiscovery } from "../../../../api/hooks";

export const Route = createFileRoute("/charters/$charterId/discovery/new")({
  component: NewDiscoveryPage,
});

function NewDiscoveryPage() {
  const { charterId } = Route.useParams();
  const navigate = useNavigate();
  const start = useStartDiscovery();

  const [queryText, setQueryText] = useState("");
  const [notes, setNotes] = useState("");
  const [view, setView] = useState<"stable" | "discovery" | "both">("both");
  const [internal, setInternal] = useState(true);
  const [external, setExternal] = useState(true);
  const [rerank, setRerank] = useState(true);
  const [rerankBudget, setRerankBudget] = useState(30);
  const [analyzeTopN, setAnalyzeTopN] = useState(25);

  return (
    <div>
      <Link
        to="/charters/$charterId"
        params={{ charterId }}
        className="text-sm text-gray-500 hover:text-gray-700"
      >
        &larr; Back to charter
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">New discovery session</h1>
      <p className="mt-1 text-gray-500 text-sm">
        Define a problem, pick sources, and kick off the discovery operator chain.
      </p>

      <form
        className="mt-6 space-y-5 rounded-lg border border-gray-200 bg-white p-5"
        onSubmit={(e) => {
          e.preventDefault();
          start.mutate(
            {
              charterId,
              body: {
                query_text: queryText,
                notes,
                view_preference: view,
                source_scope: { internal_corpus: internal, arxiv_live: external },
                rerank_policy: {
                  enabled: rerank,
                  budget_seconds: rerankBudget,
                },
                budget: { analyze_top_n: analyzeTopN },
              },
            },
            {
              onSuccess: (data) => {
                void navigate({
                  to: "/discovery/$sessionId",
                  params: { sessionId: data.session.id },
                });
              },
            },
          );
        }}
      >
        <Field label="Query text">
          <textarea
            required
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            rows={4}
            className="w-full rounded-md border border-gray-300 p-2 text-sm"
            placeholder="Describe what you're looking for…"
          />
        </Field>

        <Field label="Notes (optional)">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="w-full rounded-md border border-gray-300 p-2 text-sm"
          />
        </Field>

        <Field label="Source scope">
          <div className="space-y-2 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={internal}
                onChange={(e) => setInternal(e.target.checked)}
              />
              Internal corpus (local arXiv mirror)
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={external}
                onChange={(e) => setExternal(e.target.checked)}
              />
              arXiv live API
            </label>
          </div>
        </Field>

        <Field label="View preference">
          <select
            value={view}
            onChange={(e) => setView(e.target.value as typeof view)}
            className="rounded-md border border-gray-300 p-2 text-sm"
          >
            <option value="both">Stable + Discovery</option>
            <option value="stable">Stable only</option>
            <option value="discovery">Discovery only</option>
          </select>
        </Field>

        <Field label="Reranker">
          <div className="space-y-2 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(e) => setRerank(e.target.checked)}
              />
              Enable local cross-encoder reranker
            </label>
            <label className="flex items-center gap-2">
              Budget (seconds):
              <input
                type="number"
                min={1}
                max={600}
                value={rerankBudget}
                onChange={(e) => setRerankBudget(Number(e.target.value))}
                className="w-20 rounded-md border border-gray-300 p-1 text-sm"
              />
            </label>
          </div>
        </Field>

        <Field label="Metadata analysis top-N">
          <input
            type="number"
            min={0}
            max={500}
            value={analyzeTopN}
            onChange={(e) => setAnalyzeTopN(Number(e.target.value))}
            className="w-24 rounded-md border border-gray-300 p-1 text-sm"
          />
        </Field>

        {start.error && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {start.error.message}
          </div>
        )}

        <button
          type="submit"
          disabled={start.isPending || !queryText.trim()}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {start.isPending ? "Starting…" : "Start discovery"}
        </button>
      </form>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium uppercase text-gray-500">
        {label}
      </label>
      {children}
    </div>
  );
}
