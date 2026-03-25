import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PatternsPanel from "../components/PatternsPanel";

const categories = [
  {
    name: "failure",
    path: "failure",
    children: [
      { name: "resource", path: "failure/resource", children: [] },
    ],
  },
];

const patterns = [
  {
    public_id: "pat-1",
    pattern_type: "failure_pattern",
    polarity: "negative",
    title: "Shared OOM failure",
    category: "failure/resource/oom",
    confidence_score: 0.92,
    evidence_count: 2,
    status: "active",
    created_at: "2026-03-25T00:00:00Z",
  },
];

const detail = {
  ...patterns[0],
  description: "A repeated resource failure.",
  trigger_conditions: ["oom_or_resource_limit"],
  proven_actions: [],
  disproven_actions: [],
  evidence_refs: [],
  staleness_context: {},
  curation_notes: [{ note: "Reviewed by human", created_at: "2026-03-25T00:00:00Z" }],
  last_validated_at: "2026-03-25T00:00:00Z",
  updated_at: "2026-03-25T00:00:00Z",
};

describe("PatternsPanel", () => {
  it("renders ontology categories and pattern details", () => {
    render(
      <PatternsPanel
        patterns={patterns}
        categories={categories}
        selectedCategory={null}
        selectedPatternId="pat-1"
        patternDetail={detail}
        onSelectCategory={vi.fn()}
        onSelectPattern={vi.fn()}
        onCurate={vi.fn()}
        onConsolidate={vi.fn()}
      />,
    );

    expect(screen.getByText("failure")).toBeInTheDocument();
    expect(screen.getAllByText("Shared OOM failure")).toHaveLength(2);
    expect(screen.getByText("Reviewed by human")).toBeInTheDocument();
  });

  it("submits a refinement note", () => {
    const onCurate = vi.fn();
    render(
      <PatternsPanel
        patterns={patterns}
        categories={categories}
        selectedCategory={null}
        selectedPatternId="pat-1"
        patternDetail={detail}
        onSelectCategory={vi.fn()}
        onSelectPattern={vi.fn()}
        onCurate={onCurate}
        onConsolidate={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Keep this note" },
    });
    fireEvent.click(screen.getByText("Save Refinement"));

    expect(onCurate).toHaveBeenCalledWith({
      action: "refine",
      category: "failure/resource/oom",
      refinement_notes: "Keep this note",
    });
  });
});
