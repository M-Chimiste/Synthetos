import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useCreateCharter } from "../../api/hooks";

export const Route = createFileRoute("/charters/new")({
  component: NewCharterPage,
});

function NewCharterPage() {
  const navigate = useNavigate();
  const createCharter = useCreateCharter();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [problemStatement, setProblemStatement] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    createCharter.mutate(
      {
        title: title.trim(),
        description: description.trim(),
        problem_statement: problemStatement.trim(),
      },
      {
        onSuccess: (charter) => {
          void navigate({
            to: "/charters/$charterId",
            params: { charterId: charter.id },
          });
        },
      },
    );
  }

  const canSubmit =
    title.trim().length > 0 &&
    problemStatement.trim().length > 0 &&
    !createCharter.isPending;

  return (
    <div className="mx-auto max-w-2xl">
      <Link to="/charters" className="text-sm text-gray-500 hover:text-gray-700">
        &larr; Charters
      </Link>
      <h1 className="mt-2 mb-6 text-2xl font-semibold">New Charter</h1>

      {createCharter.error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {createCharter.error.message}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label htmlFor="title" className="mb-1 block text-sm font-medium">
            Title <span className="text-red-500">*</span>
          </label>
          <input
            id="title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g., Efficient Fine-tuning of LLMs"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
          />
        </div>

        <div>
          <label htmlFor="description" className="mb-1 block text-sm font-medium">
            Description
          </label>
          <textarea
            id="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Brief description of the research charter"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
          />
        </div>

        <div>
          <label
            htmlFor="problem_statement"
            className="mb-1 block text-sm font-medium"
          >
            Problem Statement <span className="text-red-500">*</span>
          </label>
          <textarea
            id="problem_statement"
            value={problemStatement}
            onChange={(e) => setProblemStatement(e.target.value)}
            rows={6}
            placeholder="Describe the research problem in detail..."
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-500"
          />
        </div>

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {createCharter.isPending ? "Creating..." : "Create Charter"}
          </button>
          <Link
            to="/charters"
            className="rounded-md px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
          >
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
