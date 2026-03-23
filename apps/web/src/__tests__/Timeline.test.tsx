import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import Timeline from "../components/Timeline";
import { sampleTimelineEntries } from "./fixtures/phase4";

describe("Timeline", () => {
  it("renders all timeline entries", () => {
    render(<Timeline items={sampleTimelineEntries} />);
    const entries = screen.getAllByTestId("timeline-entry");
    expect(entries).toHaveLength(4);
  });

  it("shows summaries for each entry", () => {
    render(<Timeline items={sampleTimelineEntries} />);
    expect(screen.getByText("Cycle created")).toBeInTheDocument();
    expect(screen.getByText("Started operator: initialize_cycle")).toBeInTheDocument();
    expect(screen.getByText("Run command: retry")).toBeInTheDocument();
  });

  it("filters by category", () => {
    render(<Timeline items={sampleTimelineEntries} filterCategory="operator" />);
    const entries = screen.getAllByTestId("timeline-entry");
    expect(entries).toHaveLength(1);
    expect(entries[0]).toHaveAttribute("data-category", "operator");
  });

  it("shows empty state when no items", () => {
    render(<Timeline items={[]} />);
    expect(screen.getByText("No timeline events.")).toBeInTheDocument();
  });

  it("shows empty state when filter matches nothing", () => {
    render(<Timeline items={sampleTimelineEntries} filterCategory="user_action" />);
    expect(screen.getByText("No timeline events.")).toBeInTheDocument();
  });

  it("renders timestamps", () => {
    render(<Timeline items={[sampleTimelineEntries[0]]} />);
    // The timestamp should be rendered in some locale format
    const entry = screen.getByTestId("timeline-entry");
    expect(entry.textContent).toContain("2026");
  });
});
