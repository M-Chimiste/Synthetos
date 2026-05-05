import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useCreateCharter } from "../../api/hooks";
import Icon from "../../components/Icon";

export const Route = createFileRoute("/charters/new")({
  component: NewCharterPage,
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

function NewCharterPage() {
  const navigate = useNavigate();
  const createCharter = useCreateCharter();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [problemStatement, setProblemStatement] = useState("");

  function handleSubmit(e: FormEvent) {
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
          to="/charters"
          style={{
            cursor: "pointer",
            color: "inherit",
            textDecoration: "none",
          }}
        >
          Charters
        </Link>
        <Icon name="chevron" size={12} style={{ color: "var(--c-ink-4)" }} />
        <span style={{ color: "var(--c-ink)" }}>New charter</span>
      </div>

      <div style={{ padding: "40px 40px", maxWidth: 720 }}>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 600,
            letterSpacing: "-0.015em",
            margin: 0,
            marginBottom: 6,
          }}
        >
          New charter
        </h1>
        <div
          style={{ fontSize: 13.5, color: "var(--c-ink-3)", marginBottom: 28 }}
        >
          Define a research mandate that the system can plan and execute
          against.
        </div>

        {createCharter.error && (
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
            {createCharter.error.message}
          </div>
        )}

        <form
          onSubmit={handleSubmit}
          style={{ display: "flex", flexDirection: "column", gap: 18 }}
        >
          <Field
            id="title"
            label="Title"
            required
          >
            <input
              id="title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., Efficient fine-tuning of LLMs"
              style={FIELD_STYLE}
            />
          </Field>

          <Field id="description" label="Description">
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Brief description of the research charter"
              style={FIELD_STYLE}
            />
          </Field>

          <Field id="problem_statement" label="Problem statement" required>
            <textarea
              id="problem_statement"
              value={problemStatement}
              onChange={(e) => setProblemStatement(e.target.value)}
              rows={6}
              placeholder="Describe the research problem in detail…"
              style={FIELD_STYLE}
            />
          </Field>

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              type="submit"
              disabled={!canSubmit}
              className="btn primary"
            >
              {createCharter.isPending ? "Creating…" : "Create charter"}
            </button>
            <Link to="/charters" className="btn ghost">
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  required,
  children,
}: {
  id: string;
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
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
