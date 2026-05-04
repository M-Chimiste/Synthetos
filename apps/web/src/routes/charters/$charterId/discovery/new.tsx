import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { useStartDiscovery } from "../../../../api/hooks";
import Icon from "../../../../components/Icon";

export const Route = createFileRoute("/charters/$charterId/discovery/new")({
  component: NewDiscoveryPage,
});

const FIELD_STYLE = {
  width: "100%",
  border: "1px solid var(--c-line)",
  background: "var(--c-bg-elev)",
  color: "var(--c-ink)",
  borderRadius: "var(--r-md)",
  padding: "10px 12px",
  fontSize: 13.5,
  fontFamily: "var(--f-sans)",
  outline: "none",
  resize: "vertical" as const,
};

const SMALL_INPUT_STYLE = {
  border: "1px solid var(--c-line)",
  background: "var(--c-bg-elev)",
  color: "var(--c-ink)",
  borderRadius: "var(--r-sm)",
  padding: "4px 8px",
  fontSize: 13,
  fontFamily: "var(--f-sans)",
  outline: "none",
  width: 90,
};

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
      <div
        style={{
          padding: "12px 40px",
          borderBottom: "1px solid var(--c-line)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 12.5,
          color: "var(--c-ink-3)",
          background: "var(--c-bg)",
          position: "sticky",
          top: 0,
          zIndex: 5,
        }}
      >
        <Link
          to="/charters/$charterId"
          params={{ charterId }}
          style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}
        >
          Charter
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span style={{ color: "var(--c-ink)" }}>New discovery session</span>
      </div>

      <div style={{ padding: "40px 40px", maxWidth: 760 }}>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.015em",
            margin: 0,
            marginBottom: 6,
          }}
        >
          New discovery session
        </h1>
        <div
          style={{ fontSize: 13.5, color: "var(--c-ink-3)", marginBottom: 28 }}
        >
          Define a problem, pick sources, and kick off the discovery operator
          chain.
        </div>

        {start.error && (
          <div
            className="card"
            style={{
              padding: 12,
              marginBottom: 20,
              borderColor: "var(--c-err)",
              color: "var(--c-err)",
              fontSize: 13,
            }}
          >
            {start.error.message}
          </div>
        )}

        <form
          style={{ display: "flex", flexDirection: "column", gap: 20 }}
          onSubmit={(e) => {
            e.preventDefault();
            start.mutate(
              {
                charterId,
                body: {
                  query_text: queryText,
                  notes,
                  view_preference: view,
                  source_scope: {
                    internal_corpus: internal,
                    arxiv_live: external,
                  },
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
          <Field label="Query text" required>
            <textarea
              required
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              rows={4}
              style={FIELD_STYLE}
              placeholder="Describe what you're looking for…"
            />
          </Field>

          <Field label="Notes (optional)">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              style={FIELD_STYLE}
            />
          </Field>

          <Field label="Source scope">
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
                fontSize: 13,
                color: "var(--c-ink-2)",
              }}
            >
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <input
                  type="checkbox"
                  checked={internal}
                  onChange={(e) => setInternal(e.target.checked)}
                />
                Internal corpus (local arXiv mirror)
              </label>
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
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
              style={{
                ...FIELD_STYLE,
                width: "auto",
                resize: undefined,
              }}
            >
              <option value="both">Stable + Discovery</option>
              <option value="stable">Stable only</option>
              <option value="discovery">Discovery only</option>
            </select>
          </Field>

          <Field label="Reranker">
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
                fontSize: 13,
                color: "var(--c-ink-2)",
              }}
            >
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                <input
                  type="checkbox"
                  checked={rerank}
                  onChange={(e) => setRerank(e.target.checked)}
                />
                Enable local cross-encoder reranker
              </label>
              <label
                style={{ display: "flex", alignItems: "center", gap: 8 }}
              >
                Budget (seconds):
                <input
                  type="number"
                  min={1}
                  max={600}
                  value={rerankBudget}
                  onChange={(e) => setRerankBudget(Number(e.target.value))}
                  style={SMALL_INPUT_STYLE}
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
              style={SMALL_INPUT_STYLE}
            />
          </Field>

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              type="submit"
              disabled={start.isPending || !queryText.trim()}
              className="btn primary"
            >
              {start.isPending ? "Starting…" : "Start discovery"}
            </button>
            <Link
              to="/charters/$charterId"
              params={{ charterId }}
              className="btn ghost"
            >
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div>
      <label
        style={{
          display: "block",
          fontSize: 12,
          fontWeight: 500,
          color: "var(--c-ink-2)",
          marginBottom: 6,
        }}
      >
        {label}
        {required && (
          <span style={{ color: "var(--c-err)", marginLeft: 4 }}>*</span>
        )}
      </label>
      {children}
    </div>
  );
}
