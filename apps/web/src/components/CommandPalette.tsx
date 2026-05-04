import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useCharters, usePatterns, useSkills } from "../api/hooks";

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

interface PaletteItem {
  kind: "Charter" | "Pattern" | "Skill" | "Page";
  id: string;
  label: string;
  sublabel?: string;
  navigate: () => void;
}

const STATIC_PAGES: Array<Omit<PaletteItem, "navigate"> & { route: string }> = [
  { kind: "Page", id: "page-dashboard", label: "Dashboard", route: "/" },
  { kind: "Page", id: "page-charters", label: "Charters", route: "/charters" },
  { kind: "Page", id: "page-events", label: "Events", route: "/events" },
  { kind: "Page", id: "page-patterns", label: "Patterns", route: "/patterns" },
  { kind: "Page", id: "page-skills", label: "Skills", route: "/skills" },
  { kind: "Page", id: "page-experiment", label: "Experiments", route: "/experiment" },
  { kind: "Page", id: "page-analysis", label: "Analysis", route: "/analysis" },
];

export default function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const charters = useCharters();
  const patterns = usePatterns();
  const skills = useSkills();
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const items: PaletteItem[] = useMemo(() => {
    const out: PaletteItem[] = [];
    for (const p of STATIC_PAGES) {
      out.push({
        kind: "Page",
        id: p.id,
        label: p.label,
        navigate: () => void navigate({ to: p.route }),
      });
    }
    for (const c of charters.data?.items ?? []) {
      out.push({
        kind: "Charter",
        id: c.id,
        label: c.title,
        sublabel: c.id.slice(0, 8),
        navigate: () =>
          void navigate({
            to: "/charters/$charterId",
            params: { charterId: c.id },
          }),
      });
    }
    for (const p of patterns.data?.items ?? []) {
      out.push({
        kind: "Pattern",
        id: p.id,
        label: p.title,
        sublabel: p.pattern_type,
        navigate: () =>
          void navigate({
            to: "/patterns/$patternId",
            params: { patternId: p.id },
          }),
      });
    }
    for (const s of skills.data?.items ?? []) {
      out.push({
        kind: "Skill",
        id: s.id,
        label: s.skill_id,
        sublabel: `v${s.version}${s.phase ? ` · ${s.phase}` : ""}`,
        navigate: () => void navigate({ to: "/skills" }),
      });
    }
    return out;
  }, [charters.data, patterns.data, skills.data, navigate]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items.slice(0, 30);
    const tokens = q.split(/\s+/);
    return items
      .filter((it) => {
        const hay = `${it.kind} ${it.label} ${it.sublabel ?? ""}`.toLowerCase();
        return tokens.every((t) => hay.includes(t));
      })
      .slice(0, 30);
  }, [items, query]);

  // Reset selection when filter changes
  useEffect(() => {
    setActiveIdx(0);
  }, [query]);

  // Auto-focus on open, clear on close
  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      const id = setTimeout(() => inputRef.current?.focus(), 0);
      return () => clearTimeout(id);
    }
  }, [open]);

  if (!open) return null;

  function runActive() {
    const target = filtered[activeIdx];
    if (!target) return;
    onClose();
    target.navigate();
  }

  function handleKey(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runActive();
    }
  }

  return (
    <div
      onClick={onClose}
      onKeyDown={handleKey}
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.25)",
        display: "flex",
        justifyContent: "center",
        paddingTop: "12vh",
        zIndex: 50,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{
          width: "min(560px, 92vw)",
          maxHeight: "70vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "var(--shadow-focus)",
        }}
      >
        <div
          style={{
            padding: "12px 14px",
            borderBottom: "1px solid var(--c-line-soft)",
            display: "flex",
            gap: 10,
            alignItems: "center",
          }}
        >
          <span style={{ color: "var(--c-ink-4)", fontSize: 13 }}>›</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search charters, patterns, skills, pages…"
            style={{
              flex: 1,
              border: "none",
              outline: "none",
              background: "transparent",
              fontSize: 14,
              color: "var(--c-ink)",
              fontFamily: "var(--f-sans)",
            }}
          />
          <span className="kbd">esc</span>
        </div>
        <div style={{ overflowY: "auto", flex: 1 }}>
          {filtered.length === 0 ? (
            <div
              style={{
                padding: "16px 14px",
                fontSize: 13,
                color: "var(--c-ink-3)",
              }}
            >
              No matches.
            </div>
          ) : (
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: 4,
                display: "flex",
                flexDirection: "column",
                gap: 1,
              }}
            >
              {filtered.map((it, i) => (
                <PaletteRow
                  key={`${it.kind}:${it.id}`}
                  active={i === activeIdx}
                  onMouseEnter={() => setActiveIdx(i)}
                  onClick={runActive}
                >
                  <span
                    className="chip slate"
                    style={{ fontSize: 10.5, minWidth: 60, justifyContent: "center" }}
                  >
                    {it.kind}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {it.label}
                    </div>
                    {it.sublabel && (
                      <div
                        className="mono"
                        style={{
                          fontSize: 11,
                          color: "var(--c-ink-4)",
                        }}
                      >
                        {it.sublabel}
                      </div>
                    )}
                  </span>
                </PaletteRow>
              ))}
            </ul>
          )}
        </div>
        <div
          style={{
            padding: "8px 12px",
            borderTop: "1px solid var(--c-line-soft)",
            fontSize: 11,
            color: "var(--c-ink-4)",
            display: "flex",
            gap: 12,
          }}
        >
          <span>
            <span className="kbd">↑</span> <span className="kbd">↓</span> navigate
          </span>
          <span>
            <span className="kbd">↵</span> open
          </span>
          <span>
            <span className="kbd">esc</span> close
          </span>
        </div>
      </div>
    </div>
  );
}

function PaletteRow({
  active,
  onClick,
  onMouseEnter,
  children,
}: {
  active: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
  children: ReactNode;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        onMouseEnter={onMouseEnter}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 10px",
          borderRadius: "var(--r-md)",
          border: "1px solid transparent",
          background: active ? "var(--c-bg-elev)" : "transparent",
          color: "var(--c-ink)",
          fontSize: 13,
          textAlign: "left",
          cursor: "pointer",
        }}
      >
        {children}
      </button>
    </li>
  );
}
