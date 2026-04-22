import { createFileRoute } from "@tanstack/react-router";
import { useSkills, useDiscoverSkills } from "../api/hooks";
import StatusBadge from "../components/StatusBadge";

export const Route = createFileRoute("/skills")({
  component: SkillsPage,
});

function SkillsPage() {
  const { data, isLoading, error } = useSkills();
  const discover = useDiscoverSkills();
  const skills = data?.items ?? [];

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1240 }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginBottom: 24,
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.015em",
              margin: 0,
            }}
          >
            Skills
          </h1>
          <div
            style={{ color: "var(--c-ink-3)", fontSize: 13.5, marginTop: 4 }}
          >
            Agent tools registered with the runtime.
          </div>
        </div>
        <button
          type="button"
          className="btn"
          onClick={() => discover.mutate()}
          disabled={discover.isPending}
        >
          {discover.isPending ? "Discovering…" : "Discover skills"}
        </button>
      </div>

      {discover.isSuccess && (
        <div
          className="card"
          style={{
            padding: 12,
            marginBottom: 16,
            borderColor: "var(--c-ok-soft)",
            background: "var(--c-ok-soft)",
            color: "var(--c-ok)",
            fontSize: 13,
          }}
        >
          Discovered or refreshed {discover.data.discovered} skill package
          {discover.data.discovered === 1 ? "" : "s"}.
        </div>
      )}

      {discover.error && (
        <div
          className="card"
          style={{
            padding: 12,
            marginBottom: 16,
            borderColor: "var(--c-err)",
            color: "var(--c-err)",
            fontSize: 13,
          }}
        >
          Discovery failed: {discover.error.message}
        </div>
      )}

      {error && (
        <div
          className="card"
          style={{
            padding: 14,
            marginBottom: 16,
            borderColor: "var(--c-err)",
            color: "var(--c-err)",
            fontSize: 13,
          }}
        >
          Failed to load skills: {error.message}
        </div>
      )}

      {isLoading && (
        <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
          Loading skills…
        </div>
      )}

      {!isLoading && skills.length === 0 && (
        <div
          className="card"
          style={{
            padding: 32,
            textAlign: "center",
            color: "var(--c-ink-3)",
            fontSize: 13.5,
          }}
        >
          <p style={{ margin: 0 }}>No skills registered yet.</p>
          <p
            style={{
              marginTop: 8,
              marginBottom: 0,
              fontSize: 12.5,
              color: "var(--c-ink-4)",
            }}
          >
            Click "Discover skills" to scan for available skill packages.
          </p>
        </div>
      )}

      {skills.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 12,
          }}
        >
          {skills.map((s) => (
            <div key={s.id} className="card" style={{ padding: 16 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  marginBottom: 8,
                }}
              >
                <div
                  className="mono"
                  style={{ fontSize: 13, fontWeight: 500 }}
                >
                  {s.skill_id}
                </div>
                <span
                  className="dot"
                  style={{
                    background: s.enabled
                      ? "var(--c-ok)"
                      : "var(--c-ink-4)",
                  }}
                />
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 6,
                  marginBottom: 10,
                  flexWrap: "wrap",
                }}
              >
                <StatusBadge status={s.trust_tier} />
                {s.phase && (
                  <span className="chip slate" style={{ fontSize: 10.5 }}>
                    {s.phase}
                  </span>
                )}
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 11.5,
                  color: "var(--c-ink-3)",
                }}
              >
                <span>v{s.version}</span>
                <span className="mono tabular">
                  {new Date(s.discovered_at).toLocaleDateString()}
                </span>
              </div>
              {s.source_path && (
                <div
                  className="mono"
                  style={{
                    marginTop: 8,
                    fontSize: 10.5,
                    color: "var(--c-ink-4)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={s.source_path}
                >
                  {s.source_path}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
