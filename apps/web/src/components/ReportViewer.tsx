import ReactMarkdown from "react-markdown";
import type { ReportDetail } from "../lib/types";

interface ReportViewerProps {
  report: ReportDetail;
}

function QualityBadge({ score }: { score: number }) {
  let color = "#ef4444";
  let label = "Low";
  if (score >= 0.8) {
    color = "#22c55e";
    label = "High";
  } else if (score >= 0.5) {
    color = "#f59e0b";
    label = "Medium";
  }
  return (
    <span
      data-testid="quality-badge"
      style={{
        display: "inline-block",
        padding: "0.15rem 0.5rem",
        borderRadius: "9999px",
        fontSize: "0.75rem",
        fontWeight: 600,
        color: "#fff",
        background: color,
      }}
    >
      Quality: {label} ({Math.round(score * 100)}%)
    </span>
  );
}

export default function ReportViewer({ report }: ReportViewerProps) {
  const quality = report.quality_metadata;
  const structuralScore = quality?.structural_score;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1rem" }}>
        <h2 style={{ margin: 0 }}>{report.title}</h2>
        {structuralScore !== undefined && <QualityBadge score={structuralScore} />}
      </div>
      {quality?.section_checklist && (
        <div style={{ fontSize: "0.8rem", color: "#6b7280", marginBottom: "1rem" }}>
          Sections:{" "}
          {Object.entries(quality.section_checklist).map(([name, present]) => (
            <span key={name} style={{ marginRight: "0.5rem" }}>
              {present ? "\u2705" : "\u274C"} {name}
            </span>
          ))}
        </div>
      )}
      <div className="report-markdown">
        <ReactMarkdown>{report.markdown}</ReactMarkdown>
      </div>
    </div>
  );
}
