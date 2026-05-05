import { createFileRoute, Link } from "@tanstack/react-router";
import { useDiscoveryReport, useDiscoverySession } from "../../../api/hooks";
import Icon from "../../../components/Icon";
import Markdown from "../../../components/Markdown";

export const Route = createFileRoute("/discovery/$sessionId/report")({
  component: ReportPage,
});

function ReportPage() {
  const { sessionId } = Route.useParams();
  const session = useDiscoverySession(sessionId);
  const report = useDiscoveryReport(sessionId);

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
          to="/discovery/$sessionId"
          params={{ sessionId }}
          style={{ cursor: "pointer", color: "inherit", textDecoration: "none" }}
        >
          Discovery session
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span style={{ color: "var(--c-ink)" }}>Report</span>
      </div>

      <div style={{ padding: "28px 40px", maxWidth: 1000 }}>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.015em",
            margin: 0,
            marginBottom: 4,
          }}
        >
          Discovery report
        </h1>
        <div
          className="mono"
          style={{ fontSize: 11.5, color: "var(--c-ink-3)" }}
        >
          {sessionId}
        </div>

        {session.data?.report_artifact_path && (
          <div
            style={{ marginTop: 8, fontSize: 12, color: "var(--c-ink-3)" }}
          >
            Source:{" "}
            <span className="mono" style={{ color: "var(--c-ink-2)" }}>
              {session.data.report_artifact_path}
            </span>
          </div>
        )}

        {report.isLoading && (
          <div
            style={{
              marginTop: 20,
              fontSize: 13,
              color: "var(--c-ink-3)",
            }}
          >
            Loading report…
          </div>
        )}

        {report.error && (
          <div
            className="card"
            style={{
              marginTop: 20,
              padding: 14,
              borderColor: "var(--c-err)",
              color: "var(--c-err)",
              fontSize: 13,
            }}
          >
            {report.error.message}
          </div>
        )}

        {report.data?.markdown && (
          <div className="card" style={{ marginTop: 20, padding: 24 }}>
            <Markdown>{report.data.markdown}</Markdown>
          </div>
        )}

        {!report.data?.markdown && report.data?.json && (
          <div className="card" style={{ marginTop: 20, padding: 18 }}>
            <pre
              style={{
                margin: 0,
                fontSize: 11.5,
                color: "var(--c-ink-2)",
                fontFamily: "var(--f-mono)",
                whiteSpace: "pre-wrap",
              }}
            >
              {JSON.stringify(report.data.json, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
