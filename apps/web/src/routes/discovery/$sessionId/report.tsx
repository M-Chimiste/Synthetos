import { createFileRoute, Link } from "@tanstack/react-router";
import { useDiscoveryReport, useDiscoverySession } from "../../../api/hooks";
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
      <Link
        to="/discovery/$sessionId"
        params={{ sessionId }}
        className="text-sm text-gray-500 hover:text-gray-700"
      >
        &larr; Back to session
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">Discovery report</h1>
      <p className="mt-1 font-mono text-xs text-gray-500">{sessionId}</p>

      {session.data?.report_artifact_path && (
        <p className="mt-2 text-xs text-gray-500">
          Source: {session.data.report_artifact_path}
        </p>
      )}

      {report.isLoading && (
        <p className="mt-4 text-sm text-gray-500">Loading report…</p>
      )}

      {report.error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {report.error.message}
        </div>
      )}

      {report.data?.markdown && (
        <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
          <Markdown>{report.data.markdown}</Markdown>
        </div>
      )}

      {!report.data?.markdown && report.data?.json && (
        <pre className="mt-4 overflow-x-auto rounded-lg border border-gray-200 bg-white p-5 text-xs">
          {JSON.stringify(report.data.json, null, 2)}
        </pre>
      )}
    </div>
  );
}
