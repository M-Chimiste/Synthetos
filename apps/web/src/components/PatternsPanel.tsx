import { useState } from "react";

import type {
  CanonicalPatternDetail,
  CanonicalPatternSummary,
  PatternCategoryNode,
} from "../lib/types";

interface PatternsPanelProps {
  patterns: CanonicalPatternSummary[];
  categories: PatternCategoryNode[];
  selectedCategory?: string | null;
  selectedPatternId?: string | null;
  patternDetail?: CanonicalPatternDetail | null;
  curationPending?: boolean;
  consolidationPending?: boolean;
  onSelectCategory: (path: string | null) => void;
  onSelectPattern: (patternId: string) => void;
  onCurate: (payload: {
    action: "confirm" | "dismiss" | "refine";
    category?: string | null;
    refinement_notes?: string | null;
  }) => void;
  onConsolidate: () => void;
}

function CategoryTree({
  nodes,
  selectedCategory,
  onSelectCategory,
}: {
  nodes: PatternCategoryNode[];
  selectedCategory?: string | null;
  onSelectCategory: (path: string) => void;
}) {
  return (
    <div className="space-y-1">
      {nodes.map((node) => (
        <div key={node.path}>
          <button
            className={`w-full rounded-lg px-2 py-1 text-left text-xs ${
              selectedCategory === node.path
                ? "bg-teal-100 text-teal-900"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
            onClick={() => onSelectCategory(node.path)}
            type="button"
          >
            {node.path}
          </button>
          {node.children.length > 0 ? (
            <div className="ml-3 mt-1 border-l border-slate-200 pl-2">
              <CategoryTree
                nodes={node.children}
                selectedCategory={selectedCategory}
                onSelectCategory={onSelectCategory}
              />
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export default function PatternsPanel({
  patterns,
  categories,
  selectedCategory,
  selectedPatternId,
  patternDetail,
  curationPending = false,
  consolidationPending = false,
  onSelectCategory,
  onSelectPattern,
  onCurate,
  onConsolidate,
}: PatternsPanelProps) {
  const [refinementNotes, setRefinementNotes] = useState("");

  return (
    <section className="panel p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Pattern Memory</p>
          <h2 className="text-xl font-semibold">Canonical Patterns</h2>
        </div>
        <button
          className="button-secondary text-xs"
          disabled={consolidationPending}
          onClick={onConsolidate}
          type="button"
        >
          {consolidationPending ? "Consolidating..." : "Run Consolidation"}
        </button>
      </div>

      <div className="mb-4 space-y-2">
        <button
          className={`rounded-lg px-2 py-1 text-xs ${
            !selectedCategory
              ? "bg-slate-900 text-slate-50"
              : "bg-slate-100 text-slate-700 hover:bg-slate-200"
          }`}
          onClick={() => onSelectCategory(null)}
          type="button"
        >
          All categories
        </button>
        {categories.length > 0 ? (
          <CategoryTree
            nodes={categories}
            selectedCategory={selectedCategory}
            onSelectCategory={onSelectCategory}
          />
        ) : (
          <p className="text-xs text-slate-500">No ontology categories yet.</p>
        )}
      </div>

      <div className="space-y-2">
        {patterns.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">
            No canonical patterns yet. Run consolidation to build the initial memory base.
          </p>
        ) : (
          patterns.map((pattern) => (
            <button
              key={pattern.public_id}
              className={`w-full rounded-xl border p-3 text-left ${
                selectedPatternId === pattern.public_id
                  ? "border-accent bg-teal-50"
                  : "border-slate-200 hover:bg-slate-50"
              }`}
              onClick={() => onSelectPattern(pattern.public_id)}
              type="button"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{pattern.title}</div>
                  <div className="text-xs text-slate-500">
                    {pattern.pattern_type} · {pattern.category || "uncategorized"}
                  </div>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <div>{pattern.status}</div>
                  <div>{pattern.confidence_score.toFixed(2)}</div>
                </div>
              </div>
            </button>
          ))
        )}
      </div>

      {patternDetail ? (
        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-2 text-sm font-semibold">{patternDetail.title}</div>
          <p className="text-sm text-slate-700">{patternDetail.description}</p>
          <div className="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-2">
            <div>
              <strong>Category:</strong> {patternDetail.category || "uncategorized"}
            </div>
            <div>
              <strong>Evidence:</strong> {patternDetail.evidence_count}
            </div>
            <div>
              <strong>Polarity:</strong> {patternDetail.polarity}
            </div>
            <div>
              <strong>Status:</strong> {patternDetail.status}
            </div>
          </div>
          {patternDetail.trigger_conditions.length > 0 ? (
            <div className="mt-3">
              <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500">
                Trigger Conditions
              </div>
              <div className="mt-1 space-y-1 text-sm text-slate-700">
                {patternDetail.trigger_conditions.map((condition) => (
                  <div key={condition}>- {condition}</div>
                ))}
              </div>
            </div>
          ) : null}
          {patternDetail.curation_notes.length > 0 ? (
            <div className="mt-3">
              <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500">
                Curation Notes
              </div>
              <div className="mt-1 space-y-2 text-sm text-slate-700">
                {patternDetail.curation_notes.map((note, index) => (
                  <div key={`${note.created_at ?? index}`} className="rounded-lg bg-white p-2">
                    {String(note.note ?? "")}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <label className="mt-3 block space-y-1">
            <span className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500">
              Refinement Note
            </span>
            <textarea
              className="field min-h-20"
              onChange={(event) => setRefinementNotes(event.target.value)}
              value={refinementNotes}
            />
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="button-secondary text-xs"
              disabled={curationPending}
              onClick={() => onCurate({ action: "confirm", category: patternDetail.category })}
              type="button"
            >
              Confirm
            </button>
            <button
              className="button-secondary text-xs"
              disabled={curationPending}
              onClick={() => onCurate({ action: "dismiss", category: patternDetail.category })}
              type="button"
            >
              Dismiss
            </button>
            <button
              className="button-secondary text-xs"
              disabled={curationPending || refinementNotes.trim().length === 0}
              onClick={() => {
                onCurate({
                  action: "refine",
                  category: patternDetail.category,
                  refinement_notes: refinementNotes.trim(),
                });
                setRefinementNotes("");
              }}
              type="button"
            >
              Save Refinement
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
