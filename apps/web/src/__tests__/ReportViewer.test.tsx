import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import ReportViewer from "../components/ReportViewer";
import { sampleReport, sampleReportLowQuality } from "./fixtures/phase4";

describe("ReportViewer", () => {
  it("renders the report title", () => {
    render(<ReportViewer report={sampleReport} />);
    expect(screen.getByText("Verification Report — Run 1")).toBeInTheDocument();
  });

  it("shows quality badge with high score", () => {
    render(<ReportViewer report={sampleReport} />);
    const badge = screen.getByTestId("quality-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toContain("High");
    expect(badge.textContent).toContain("85%");
  });

  it("shows quality badge with low score", () => {
    render(<ReportViewer report={sampleReportLowQuality} />);
    const badge = screen.getByTestId("quality-badge");
    expect(badge.textContent).toContain("Low");
  });

  it("renders markdown content", () => {
    render(<ReportViewer report={sampleReport} />);
    // ReactMarkdown should render the heading
    expect(screen.getByText("Verification Report")).toBeInTheDocument();
  });

  it("shows section checklist", () => {
    render(<ReportViewer report={sampleReport} />);
    // Section names appear both in checklist and rendered markdown, so use getAllByText
    expect(screen.getAllByText(/Outcome/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Checks/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Summary/).length).toBeGreaterThanOrEqual(1);
    // The checklist-specific container with "Sections:" label should exist
    expect(screen.getByText(/Sections:/)).toBeInTheDocument();
  });

  it("handles missing quality metadata gracefully", () => {
    const reportNoQuality = { ...sampleReport, quality_metadata: undefined };
    render(<ReportViewer report={reportNoQuality} />);
    expect(screen.getByText("Verification Report — Run 1")).toBeInTheDocument();
    expect(screen.queryByTestId("quality-badge")).not.toBeInTheDocument();
  });
});
