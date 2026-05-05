import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, Dispatch, ReactNode, SetStateAction } from "react";
import type {
  ModelCatalogEntry,
  ModelCatalogEntryPayload,
  ProviderType,
} from "../api/client";
import {
  useAssignModelRole,
  useCreateModelCatalogEntry,
  useDeleteModelCatalogEntry,
  useModelSettings,
  useTestModelCatalogEntry,
  useUpdateModelCatalogEntry,
} from "../api/hooks";
import Icon from "../components/Icon";
import { useTheme, type ThemeMode } from "../lib/theme";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

const PROVIDER_TYPES: ProviderType[] = [
  "anthropic",
  "openai",
  "google",
  "openai_compatible",
];

interface CatalogFormState {
  key: string;
  display_name: string;
  provider_type: ProviderType;
  provider_name: string;
  model: string;
  base_url: string;
  default_temperature: string;
  default_max_tokens: string;
  enabled: boolean;
  notes: string;
}

interface RoleDraft {
  catalog_entry_id: string;
  temperature: string;
  max_tokens: string;
}

const EMPTY_FORM: CatalogFormState = {
  key: "",
  display_name: "",
  provider_type: "openai_compatible",
  provider_name: "local",
  model: "",
  base_url: "http://localhost:11434/v1",
  default_temperature: "0.7",
  default_max_tokens: "4096",
  enabled: true,
  notes: "",
};

function SettingsPage() {
  const { data, isLoading, error } = useModelSettings();
  const createEntry = useCreateModelCatalogEntry();
  const updateEntry = useUpdateModelCatalogEntry();
  const deleteEntry = useDeleteModelCatalogEntry();
  const assignRole = useAssignModelRole();
  const testEntry = useTestModelCatalogEntry();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [catalogModalOpen, setCatalogModalOpen] = useState(false);
  const [form, setForm] = useState<CatalogFormState>(EMPTY_FORM);
  const [roleDrafts, setRoleDrafts] = useState<Record<string, RoleDraft>>({});
  const [testMessages, setTestMessages] = useState<Record<string, string>>({});

  const catalog = useMemo(() => data?.catalog_entries ?? [], [data]);
  const bindings = useMemo(() => data?.role_bindings ?? [], [data]);

  const entryById = useMemo(() => {
    const map = new Map<string, ModelCatalogEntry>();
    for (const entry of catalog) map.set(entry.id, entry);
    return map;
  }, [catalog]);

  const bindingByRole = useMemo(() => {
    const map = new Map(bindings.map((binding) => [binding.role, binding]));
    return map;
  }, [bindings]);

  const boundEntryIds = useMemo(
    () => new Set(bindings.map((binding) => binding.catalog_entry_id)),
    [bindings],
  );

  useEffect(() => {
    if (!data) return;
    const next: Record<string, RoleDraft> = {};
    for (const role of data.roles) {
      const binding = bindingByRole.get(role);
      next[role] = {
        catalog_entry_id: binding?.catalog_entry_id ?? "",
        temperature: binding?.temperature?.toString() ?? "",
        max_tokens: binding?.max_tokens?.toString() ?? "",
      };
    }
    setRoleDrafts(next);
  }, [data, bindingByRole]);

  const editingEntry = editingId ? entryById.get(editingId) : null;

  function resetForm() {
    setEditingId(null);
    setForm(EMPTY_FORM);
  }

  function startCreate() {
    resetForm();
    setCatalogModalOpen(true);
  }

  function startEdit(entry: ModelCatalogEntry) {
    setEditingId(entry.id);
    setForm({
      key: entry.key,
      display_name: entry.display_name,
      provider_type: entry.provider_type,
      provider_name: entry.provider_name,
      model: entry.model,
      base_url: entry.base_url ?? "",
      default_temperature: entry.default_temperature?.toString() ?? "",
      default_max_tokens: entry.default_max_tokens?.toString() ?? "",
      enabled: entry.enabled,
      notes: entry.notes ?? "",
    });
    setCatalogModalOpen(true);
  }

  function closeCatalogModal() {
    setCatalogModalOpen(false);
    resetForm();
  }

  function catalogPayload(): ModelCatalogEntryPayload {
    const key = form.key.trim() || generatedCatalogKey(form);
    return {
      key,
      display_name: form.display_name.trim(),
      provider_type: form.provider_type,
      provider_name: form.provider_name.trim(),
      model: form.model.trim(),
      base_url: form.base_url.trim() || null,
      default_temperature: parseOptionalFloat(form.default_temperature),
      default_max_tokens: parseOptionalInt(form.default_max_tokens),
      enabled: form.enabled,
      notes: form.notes.trim() || null,
    };
  }

  async function saveCatalogEntry() {
    if (editingId) {
      await updateEntry.mutateAsync({ id: editingId, data: catalogPayload() });
    } else {
      await createEntry.mutateAsync(catalogPayload());
    }
    closeCatalogModal();
  }

  async function deleteCatalogEntry(entry: ModelCatalogEntry) {
    if (
      !window.confirm(
        `Delete ${entry.display_name}? This cannot be undone.`,
      )
    ) {
      return;
    }
    await deleteEntry.mutateAsync(entry.id);
  }

  async function testCatalogEntry(entry: ModelCatalogEntry) {
    setTestMessages((prev) => ({ ...prev, [entry.id]: "Testing…" }));
    const result = await testEntry.mutateAsync(entry.id);
    setTestMessages((prev) => ({
      ...prev,
      [entry.id]: result.success
        ? `OK · ${result.latency_ms} ms`
        : result.error ?? "Test failed",
    }));
  }

  async function saveRole(role: string) {
    const draft = roleDrafts[role];
    if (!draft?.catalog_entry_id) return;
    await assignRole.mutateAsync({
      role,
      data: {
        catalog_entry_id: draft.catalog_entry_id,
        temperature: parseOptionalFloat(draft.temperature),
        max_tokens: parseOptionalInt(draft.max_tokens),
      },
    });
  }

  const mutationError =
    createEntry.error ??
    updateEntry.error ??
    deleteEntry.error ??
    assignRole.error ??
    testEntry.error;

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1360 }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginBottom: 22,
          gap: 16,
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              margin: 0,
            }}
          >
            Settings
          </h1>
          <div
            style={{ color: "var(--c-ink-3)", fontSize: 13.5, marginTop: 4 }}
          >
            LLM model routing for future operator calls.
          </div>
        </div>
        {data && (
          <span className="chip slate">
            {catalog.filter((entry) => entry.enabled).length} enabled models
          </span>
        )}
      </div>

      {error && <Notice tone="err">Failed to load settings: {error.message}</Notice>}
      {mutationError && <Notice tone="err">{mutationError.message}</Notice>}
      {isLoading && (
        <div style={{ fontSize: 13, color: "var(--c-ink-3)" }}>
          Loading model settings…
        </div>
      )}

      <div style={{ display: "grid", gap: 18 }}>
        <AppearanceSection />
        {data && (<>
          <section className="card" style={{ overflow: "hidden" }}>
            <SurfaceHeader
              title="Role assignments"
              subtitle="Map each runtime role to an enabled catalog model."
            />
            <div style={{ overflowX: "auto" }}>
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <Th>Role</Th>
                    <Th>Active model</Th>
                    <Th>Provider</Th>
                    <Th>Temperature</Th>
                    <Th>Max tokens</Th>
                    <Th>Status</Th>
                    <Th align="right">Action</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.roles.map((role) => {
                    const binding = bindingByRole.get(role);
                    const entry = binding
                      ? entryById.get(binding.catalog_entry_id)
                      : null;
                    const fallback = data.yaml_defaults[role];
                    const draft = roleDrafts[role] ?? {
                      catalog_entry_id: "",
                      temperature: "",
                      max_tokens: "",
                    };
                    const hasDbBinding = !!binding;
                    const status = entry
                      ? entry.enabled
                        ? "active"
                        : "disabled"
                      : fallback
                        ? "default"
                        : "unset";

                    return (
                      <tr key={role}>
                        <Td mono>{role}</Td>
                        <Td>
                          <select
                            value={draft.catalog_entry_id}
                            onChange={(event) =>
                              setRoleDrafts((prev) => ({
                                ...prev,
                                [role]: {
                                  ...draft,
                                  catalog_entry_id: event.target.value,
                                },
                              }))
                            }
                            style={inputStyle}
                          >
                            <option value="">
                              {fallback ? "Use YAML fallback" : "Select model"}
                            </option>
                            {catalog.map((option) => (
                              <option
                                key={option.id}
                                value={option.id}
                                disabled={!option.enabled}
                              >
                                {option.display_name}
                                {option.enabled ? "" : " (disabled)"}
                              </option>
                            ))}
                          </select>
                          {!hasDbBinding && fallback && (
                            <div
                              className="mono"
                              style={{
                                color: "var(--c-ink-4)",
                                fontSize: 11,
                                marginTop: 4,
                              }}
                            >
                              {fallback.model}
                            </div>
                          )}
                        </Td>
                        <Td>
                          {entry ? (
                            <ProviderBlock entry={entry} />
                          ) : fallback ? (
                            <FallbackProviderBlock fallback={fallback} />
                          ) : (
                            <span style={{ color: "var(--c-ink-4)" }}>—</span>
                          )}
                        </Td>
                        <Td>
                          <input
                            value={draft.temperature}
                            onChange={(event) =>
                              setRoleDrafts((prev) => ({
                                ...prev,
                                [role]: {
                                  ...draft,
                                  temperature: event.target.value,
                                },
                              }))
                            }
                            placeholder={
                              entry?.default_temperature?.toString() ??
                              fallback?.temperature?.toString() ??
                              "default"
                            }
                            style={{ ...inputStyle, width: 96 }}
                          />
                        </Td>
                        <Td>
                          <input
                            value={draft.max_tokens}
                            onChange={(event) =>
                              setRoleDrafts((prev) => ({
                                ...prev,
                                [role]: {
                                  ...draft,
                                  max_tokens: event.target.value,
                                },
                              }))
                            }
                            placeholder={
                              entry?.default_max_tokens?.toString() ??
                              fallback?.max_tokens?.toString() ??
                              "default"
                            }
                            style={{ ...inputStyle, width: 108 }}
                          />
                        </Td>
                        <Td>
                          <span className={`chip ${statusChip(status)}`}>
                            {status}
                          </span>
                        </Td>
                        <Td align="right">
                          <button
                            type="button"
                            className="btn sm"
                            onClick={() => void saveRole(role)}
                            disabled={!draft.catalog_entry_id || assignRole.isPending}
                          >
                            Save
                          </button>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card" style={{ overflow: "hidden" }}>
            <SurfaceHeader
              title="Model catalog"
              subtitle="Curated models available for role assignment. API keys stay in the environment."
              action={
                <button type="button" className="btn sm" onClick={startCreate}>
                  <Icon name="plus" size={13} />
                  Add model
                </button>
              }
            />
            <div style={{ overflowX: "auto", borderTop: "1px solid var(--c-line-soft)" }}>
              <table style={catalogTableStyle}>
                <thead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Provider type</Th>
                    <Th>Model</Th>
                    <Th>Base URL</Th>
                    <Th>Status</Th>
                    <Th>Test</Th>
                    <Th align="right">Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {catalog.map((entry) => {
                    const isBound = boundEntryIds.has(entry.id);
                    return (
                      <tr key={entry.id}>
                        <Td>
                          <div style={{ fontWeight: 500 }}>
                            {entry.display_name}
                          </div>
                          <div
                            className="mono"
                            style={{ fontSize: 11, color: "var(--c-ink-4)" }}
                          >
                            {entry.key}
                          </div>
                        </Td>
                        <Td>
                          <span className="chip slate">
                            {entry.provider_type}
                          </span>
                        </Td>
                        <Td mono>{entry.model}</Td>
                        <Td mono>{entry.base_url ?? "—"}</Td>
                        <Td>
                          <span
                            className={`chip ${entry.enabled ? "ok" : "slate"}`}
                          >
                            {entry.enabled ? "enabled" : "disabled"}
                          </span>
                        </Td>
                        <Td>
                          <button
                            type="button"
                            className="btn sm"
                            onClick={() => void testCatalogEntry(entry)}
                            disabled={testEntry.isPending || !entry.enabled}
                            title="Run completion test"
                          >
                            <Icon name="play" size={13} />
                            Test
                          </button>
                          <div
                            style={{
                              color:
                                entry.last_test_ok === false
                                  ? "var(--c-err)"
                                  : "var(--c-ink-4)",
                              fontSize: 11,
                              marginTop: 4,
                              maxWidth: 280,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                            title={
                              testMessages[entry.id] ??
                              entry.last_test_error ??
                              undefined
                            }
                          >
                            {testMessages[entry.id] ??
                              lastTestLabel(entry) ??
                              "Not tested"}
                          </div>
                        </Td>
                        <Td align="right">
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "flex-end",
                              gap: 6,
                            }}
                          >
                            <button
                              type="button"
                              className="btn sm"
                              onClick={() => startEdit(entry)}
                            >
                              <Icon name="edit" size={13} />
                              Edit
                            </button>
                            <button
                              type="button"
                              className="btn ghost sm"
                              onClick={() => void deleteCatalogEntry(entry)}
                              disabled={deleteEntry.isPending || isBound}
                              title={
                                isBound
                                  ? "Reassign roles before deleting this model"
                                  : "Delete model"
                              }
                              style={{ color: "var(--c-err)" }}
                            >
                              <Icon name="x" size={13} />
                              Delete
                            </button>
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          {catalogModalOpen && (
            <CatalogModelModal
              editing={!!editingEntry}
              form={form}
              setForm={setForm}
              onClose={closeCatalogModal}
              onSubmit={() => void saveCatalogEntry()}
              busy={createEntry.isPending || updateEntry.isPending}
            />
          )}
        </>)}
      </div>
    </div>
  );
}

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

function AppearanceSection() {
  const { mode, resolved, setMode } = useTheme();
  return (
    <section className="card" style={{ overflow: "hidden" }}>
      <SurfaceHeader
        title="Appearance"
        subtitle="Theme applies immediately and persists across sessions."
      />
      <div
        style={{
          padding: "14px 16px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div role="radiogroup" aria-label="Theme" style={{ display: "flex", gap: 8 }}>
          {THEME_OPTIONS.map((option) => {
            const active = mode === option.value;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setMode(option.value)}
                className={`chip ${active ? "accent" : "slate"}`}
                style={{
                  cursor: "pointer",
                  border: "none",
                  fontFamily: "inherit",
                }}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        {mode === "system" && (
          <span
            className="mono"
            style={{ color: "var(--c-ink-4)", fontSize: 11 }}
          >
            currently: {resolved}
          </span>
        )}
      </div>
    </section>
  );
}

function CatalogModelModal({
  editing,
  form,
  setForm,
  onClose,
  onSubmit,
  busy,
}: {
  editing: boolean;
  form: CatalogFormState;
  setForm: Dispatch<SetStateAction<CatalogFormState>>;
  onClose: () => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  const valid =
    !!form.display_name.trim() &&
    !!form.provider_name.trim() &&
    !!form.model.trim() &&
    (form.provider_type !== "openai_compatible" || !!form.base_url.trim());

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 70,
        display: "grid",
        placeItems: "center",
        padding: 24,
        background: "rgba(0, 0, 0, 0.42)",
      }}
    >
      <div
        className="card"
        onClick={(event) => event.stopPropagation()}
        style={{
          width: "min(620px, 96vw)",
          maxHeight: "88vh",
          overflow: "auto",
          boxShadow: "var(--shadow-focus)",
        }}
      >
        <div
          style={{
            padding: "16px 18px",
            borderBottom: "1px solid var(--c-line-soft)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
              {editing ? "Edit model" : "Add model"}
            </h2>
            <div style={{ color: "var(--c-ink-3)", fontSize: 12.5, marginTop: 3 }}>
              Environment variables provide provider secrets.
            </div>
          </div>
          <button type="button" className="btn ghost sm" onClick={onClose}>
            <Icon name="x" size={14} />
          </button>
        </div>

        <div style={{ display: "grid", gap: 12, padding: 18 }}>
          <Label text="Key">
            <input
              value={form.key}
              placeholder={generatedCatalogKey(form)}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, key: event.target.value }))
              }
              style={inputStyle}
            />
            <span style={{ color: "var(--c-ink-4)", fontSize: 11 }}>
              Leave blank to generate from provider, model, and base URL.
            </span>
          </Label>
          <Label text="Display name">
            <input
              value={form.display_name}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  display_name: event.target.value,
                }))
              }
              style={inputStyle}
            />
          </Label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Label text="Provider type">
              <select
                value={form.provider_type}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    provider_type: event.target.value as ProviderType,
                  }))
                }
                style={inputStyle}
              >
                {PROVIDER_TYPES.map((providerType) => (
                  <option key={providerType} value={providerType}>
                    {providerType}
                  </option>
                ))}
              </select>
            </Label>
            <Label text="Provider name">
              <input
                value={form.provider_name}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    provider_name: event.target.value,
                  }))
                }
                style={inputStyle}
              />
            </Label>
          </div>
          <Label text="Model id">
            <input
              value={form.model}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, model: event.target.value }))
              }
              style={inputStyle}
            />
          </Label>
          <Label text="Base URL">
            <input
              value={form.base_url}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, base_url: event.target.value }))
              }
              style={inputStyle}
            />
          </Label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <Label text="Temperature">
              <input
                value={form.default_temperature}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    default_temperature: event.target.value,
                  }))
                }
                style={inputStyle}
              />
            </Label>
            <Label text="Max tokens">
              <input
                value={form.default_max_tokens}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    default_max_tokens: event.target.value,
                  }))
                }
                style={inputStyle}
              />
            </Label>
          </div>
          <Label text="Notes">
            <textarea
              value={form.notes}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, notes: event.target.value }))
              }
              rows={3}
              style={{ ...inputStyle, resize: "vertical" }}
            />
          </Label>
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
              color: "var(--c-ink-2)",
            }}
          >
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  enabled: event.target.checked,
                }))
              }
            />
            Enabled for assignments
          </label>
        </div>

        <div
          style={{
            padding: "12px 18px 18px",
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
          }}
        >
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={onSubmit}
            disabled={busy || !valid}
          >
            {editing ? "Save model" : "Create model"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SurfaceHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  return (
    <div
      style={{
        padding: "14px 16px",
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: 16,
      }}
    >
      <div>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{title}</h2>
        <span style={{ color: "var(--c-ink-3)", fontSize: 12.5 }}>{subtitle}</span>
      </div>
      {action}
    </div>
  );
}

function Notice({
  tone,
  children,
}: {
  tone: "err" | "ok";
  children: ReactNode;
}) {
  return (
    <div
      className="card"
      style={{
        padding: 12,
        marginBottom: 16,
        borderColor: tone === "err" ? "var(--c-err)" : "var(--c-ok)",
        color: tone === "err" ? "var(--c-err)" : "var(--c-ok)",
        fontSize: 13,
      }}
    >
      {children}
    </div>
  );
}

function Label({
  text,
  children,
}: {
  text: string;
  children: ReactNode;
}) {
  return (
    <label style={{ display: "grid", gap: 4, fontSize: 12 }}>
      <span style={{ color: "var(--c-ink-3)" }}>{text}</span>
      {children}
    </label>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      style={{
        padding: "9px 12px",
        textAlign: align,
        color: "var(--c-ink-3)",
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
        borderTop: "1px solid var(--c-line-soft)",
        borderBottom: "1px solid var(--c-line-soft)",
        background: "var(--c-panel)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
  mono = false,
}: {
  children: ReactNode;
  align?: "left" | "right";
  mono?: boolean;
}) {
  return (
    <td
      className={mono ? "mono" : undefined}
      style={{
        padding: "9px 12px",
        textAlign: align,
        borderBottom: "1px solid var(--c-line-soft)",
        color: "var(--c-ink-2)",
        fontSize: mono ? 12 : 13,
        verticalAlign: "middle",
      }}
    >
      {children}
    </td>
  );
}

function ProviderBlock({ entry }: { entry: ModelCatalogEntry }) {
  return (
    <div style={{ display: "grid", gap: 3 }}>
      <span className="chip slate" style={{ width: "fit-content" }}>
        {entry.provider_name}
      </span>
      <span className="mono" style={{ color: "var(--c-ink-4)", fontSize: 11 }}>
        {entry.provider_type}
      </span>
    </div>
  );
}

function FallbackProviderBlock({
  fallback,
}: {
  fallback: { provider: string; provider_type: ProviderType };
}) {
  return (
    <div style={{ display: "grid", gap: 3 }}>
      <span className="chip slate" style={{ width: "fit-content" }}>
        {fallback.provider}
      </span>
      <span className="mono" style={{ color: "var(--c-ink-4)", fontSize: 11 }}>
        {fallback.provider_type}
      </span>
    </div>
  );
}

function parseOptionalFloat(value: string): number | null {
  const trimmed = value.trim();
  return trimmed ? Number.parseFloat(trimmed) : null;
}

function parseOptionalInt(value: string): number | null {
  const trimmed = value.trim();
  return trimmed ? Number.parseInt(trimmed, 10) : null;
}

function generatedCatalogKey(form: CatalogFormState): string {
  const provider = form.provider_name.trim() || "provider";
  const model = form.model.trim() || "model";
  const baseUrl = form.base_url.trim();
  return form.provider_type === "openai_compatible" && baseUrl
    ? `${provider}:${model}:${baseUrl}`
    : `${provider}:${model}`;
}

function statusChip(status: string) {
  if (status === "active") return "ok";
  if (status === "disabled") return "err";
  if (status === "default") return "accent";
  return "slate";
}

function lastTestLabel(entry: ModelCatalogEntry): string | null {
  if (!entry.last_tested_at) return null;
  if (entry.last_test_ok) {
    return `OK · ${new Date(entry.last_tested_at).toLocaleString()}`;
  }
  return entry.last_test_error ?? "Test failed";
}

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  minWidth: 880,
};

const catalogTableStyle: CSSProperties = {
  ...tableStyle,
  minWidth: 1120,
};

const inputStyle: CSSProperties = {
  width: "100%",
  minHeight: 30,
  borderRadius: 6,
  border: "1px solid var(--c-line)",
  background: "var(--c-bg-elev)",
  color: "var(--c-ink)",
  padding: "5px 8px",
  font: "inherit",
  fontSize: 12.5,
};
