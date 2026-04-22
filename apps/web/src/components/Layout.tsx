import type { ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import Icon, { type IconName } from "./Icon";
import StatusDot from "./StatusDot";
import { useCharters, useJobs } from "../api/hooks";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  match: (path: string) => boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    to: "/",
    label: "Dashboard",
    icon: "home",
    match: (p) => p === "/",
  },
  {
    to: "/charters",
    label: "Charters",
    icon: "charter",
    match: (p) => p.startsWith("/charters"),
  },
  {
    to: "/patterns",
    label: "Patterns",
    icon: "pattern",
    match: (p) => p.startsWith("/patterns"),
  },
  {
    to: "/events",
    label: "Events",
    icon: "events",
    match: (p) => p.startsWith("/events"),
  },
  {
    to: "/skills",
    label: "Skills",
    icon: "skills",
    match: (p) => p.startsWith("/skills"),
  },
];

const ACTIVE_CHARTER_STATUSES = new Set([
  "active",
  "experimenting",
  "analyzing",
  "discovering",
  "planning",
]);

const ACTIVE_JOB_STATUSES = new Set([
  "pending",
  "claimed",
  "running",
  "paused",
]);

export default function Layout({ children }: { children: ReactNode }) {
  const { location } = useRouterState();
  const currentPath = location.pathname;
  const charters = useCharters();
  const jobs = useJobs();

  const charterCount = charters.data?.total ?? charters.data?.items.length;
  const activeCharters = (charters.data?.items ?? [])
    .filter((c) => ACTIVE_CHARTER_STATUSES.has(c.status))
    .slice(0, 3);
  const activeJobs = (jobs.data?.items ?? []).filter((j) =>
    ACTIVE_JOB_STATUSES.has(j.status),
  );
  const runningJobs = activeJobs.filter((j) =>
    ["running", "claimed"].includes(j.status),
  );
  const workers = new Set(
    activeJobs
      .map((j) => j.claimed_by)
      .filter((w): w is string => !!w),
  );

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "240px 1fr",
        minHeight: "100vh",
        background: "var(--c-bg)",
        color: "var(--c-ink)",
        fontFamily: "var(--f-sans)",
      }}
    >
      <aside
        style={{
          borderRight: "1px solid var(--c-line)",
          background: "var(--c-panel)",
          display: "flex",
          flexDirection: "column",
          position: "sticky",
          top: 0,
          height: "100vh",
        }}
      >
        <div
          style={{
            padding: "18px 18px 14px",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div
            style={{
              width: 22,
              height: 22,
              borderRadius: 6,
              background: "var(--c-ink)",
              display: "grid",
              placeItems: "center",
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                background: "var(--c-bg)",
              }}
            />
          </div>
          <div
            style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-0.01em" }}
          >
            Synthetos
          </div>
          <span
            className="chip slate"
            style={{ marginLeft: "auto", fontSize: 10.5 }}
          >
            v0.1
          </span>
        </div>

        <div style={{ padding: "0 10px 10px" }}>
          <button
            type="button"
            className="btn"
            style={{
              width: "100%",
              justifyContent: "flex-start",
              background: "var(--c-bg-elev)",
              color: "var(--c-ink-3)",
            }}
          >
            <Icon name="search" size={14} />
            <span>Search…</span>
            <span
              style={{
                marginLeft: "auto",
                display: "flex",
                gap: 3,
                alignItems: "center",
              }}
            >
              <span className="kbd">⌘</span>
              <span className="kbd">K</span>
            </span>
          </button>
        </div>

        <nav style={{ padding: "4px 8px", flex: 1, overflowY: "auto" }}>
          {NAV_ITEMS.map((item) => {
            const active = item.match(currentPath);
            const count =
              item.label === "Charters" ? charterCount : undefined;
            return (
              <Link
                key={item.to}
                to={item.to}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "6px 10px",
                  borderRadius: 6,
                  color: active ? "var(--c-ink)" : "var(--c-ink-2)",
                  background: active ? "var(--c-bg-elev)" : "transparent",
                  fontSize: 13,
                  fontWeight: active ? 500 : 400,
                  marginBottom: 1,
                  border: active
                    ? "1px solid var(--c-line)"
                    : "1px solid transparent",
                  textDecoration: "none",
                }}
              >
                <Icon
                  name={item.icon}
                  size={15}
                  style={{
                    color: active ? "var(--c-ink-2)" : "var(--c-ink-3)",
                  }}
                />
                <span>{item.label}</span>
                {count != null && (
                  <span
                    style={{
                      marginLeft: "auto",
                      fontSize: 11,
                      color: "var(--c-ink-4)",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {count}
                  </span>
                )}
              </Link>
            );
          })}

          {activeCharters.length > 0 && (
            <>
              <div style={{ height: 14 }} />
              <div
                className="section-label"
                style={{ padding: "0 10px 6px" }}
              >
                Active cycles
              </div>
              {activeCharters.map((c) => (
                <Link
                  key={c.id}
                  to="/charters/$charterId"
                  params={{ charterId: c.id }}
                  style={{
                    padding: "5px 10px",
                    borderRadius: 6,
                    fontSize: 12.5,
                    color: "var(--c-ink-2)",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    textDecoration: "none",
                  }}
                >
                  <StatusDot
                    status={c.status}
                    pulse={c.status === "experimenting" || c.status === "running"}
                  />
                  <span
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {c.title}
                  </span>
                </Link>
              ))}
            </>
          )}
        </nav>

        <div
          style={{
            padding: 12,
            borderTop: "1px solid var(--c-line)",
            fontSize: 11.5,
            color: "var(--c-ink-3)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              className={`dot ${runningJobs.length > 0 ? "ok pulse" : ""}`}
            />
            <span>
              {workers.size} worker{workers.size === 1 ? "" : "s"} ·{" "}
              {runningJobs.length} job{runningJobs.length === 1 ? "" : "s"}{" "}
              running
            </span>
          </div>
        </div>
      </aside>

      <main style={{ overflow: "auto" }}>{children}</main>
    </div>
  );
}
