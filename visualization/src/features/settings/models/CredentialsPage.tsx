import { t, useI18n } from "../../../i18n";
/**
 * Credentials settings page (plan §16.6): the unified editor for every
 * credential reference the catalog declares (provider env names, dedicated
 * provider keys, MCP header env refs) merged with the dotenv contents. Values
 * are always redacted in read projections; the masked placeholder is never
 * written back. All edits stage the same dotenv draft the provider pages use.
 */

import { useMemo, useState } from "react";
import { KeyRound, Plus, RotateCcw } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { useConfigDraftStore } from "../draft/store";
import { deriveCredentials, type CredentialEntry } from "./collectionDrafts";
import { CredentialValueEditor } from "../editors/controls";
import { inputClass } from "./controls";

export function CredentialsPage() {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const credentials = useMemo(
    () => deriveCredentials(state),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts, state.catalog],
  );
  const dotenv = state.saved?.sources.find((source) => source.kind === "dotenv");
  const dotenvId = dotenv?.id ?? "dotenv";
  const pendingCount = Object.values(state.drafts).filter(
    (entry) => entry.sourceId === dotenvId,
  ).length;

  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [newValue, setNewValue] = useState("");

  const discardCredentialDrafts = () => {
    const keys = Object.values(state.drafts)
      .filter((entry) => entry.sourceId === dotenvId)
      .map((entry) => entry.key);
    if (keys.length > 0) state.resetEntries(keys);
  };

  const needle = query.trim().toLowerCase();
  const visible = credentials.filter(
    (entry) =>
      needle === "" ||
      entry.name.toLowerCase().includes(needle) ||
      entry.references.some((reference) =>
        reference.path.toLowerCase().includes(needle),
      ),
  );
  const groups = groupCredentials(visible);

  const nameError =
    newName.trim() === ""
      ? null
      : !/^[A-Za-z_][A-Za-z0-9_]*$/.test(newName.trim())
        ? t("settings.credentialNameHint")
        : credentials.some((entry) => entry.name === newName.trim())
          ? t("settings.credentialNameDuplicate")
          : null;

  return (
    <div className="mx-auto w-full max-w-3xl px-5 py-4">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <KeyRound size={15} className="text-fg-faint" />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-fg">{t("settings.credentialsTitle")}</div>
          <div className="text-[11px] text-fg-faint">
            {t("settings.credentialLocation")}{dotenv !== undefined ? ` (${dotenv.path})` : ""}{t("settings.credentialHint")}</div>
        </div>
        {pendingCount > 0 && (
          <Button size="xs" variant="outline" onClick={discardCredentialDrafts}>
            <RotateCcw size={13} /> {t("common.discard")}{pendingCount} {t("settings.credentialChanges")}</Button>
        )}
      </div>

      <div className="mb-3 flex items-center gap-2">
        <input
          aria-label={t("settings.filterCredentials")}
          value={query}
          placeholder={t("settings.credentialFilterHint")}
          onChange={(event) => setQuery(event.target.value)}
          className={`${inputClass} h-7 text-[11px]`}
        />
        <Button
          size="xs"
          variant="outline"
          disabled={dotenv !== undefined && !dotenv.writable}
          onClick={() => setAdding((open) => !open)}
        >
          <Plus size={13} />{t("settings.addCredential")}</Button>
      </div>

      {adding && (
        <div className="mb-4 space-y-2 rounded-md border border-line bg-bg-elev px-3 py-3">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
            <input
              aria-label={t("settings.newCredentialName")}
              value={newName}
              placeholder="PROVIDER_API_KEY"
              onChange={(event) => setNewName(event.target.value)}
              className={`${inputClass} font-mono text-[11px]`}
              aria-invalid={nameError !== null}
            />
            <input
              aria-label={t("settings.newCredentialValue")}
              type="password"
              value={newValue}
              placeholder={t("settings.credentialValueHint")}
              onChange={(event) => setNewValue(event.target.value)}
              className={`${inputClass} font-mono text-[11px]`}
            />
            <Button
              size="xs"
              variant="primary"
              disabled={nameError !== null || newName.trim() === "" || newValue === ""}
              onClick={() => {
                state.setValue(dotenvId, newName.trim(), newValue);
                setNewName("");
                setNewValue("");
                setAdding(false);
              }}
            >{t("settings.stageValue")}</Button>
          </div>
          {nameError !== null && (
            <div className="text-[10px] text-danger">{nameError}</div>
          )}
          <div className="text-[10px] text-fg-faint">{t("settings.preferNamesReferencedByAProviderOrMcpServer")}</div>
        </div>
      )}

      {credentials.length === 0 && !adding ? (
        <EmptyState
          title={t("settings.noCredentialRefs")}
          description={t("settings.credentialRefsHint")}
        />
      ) : (
        groups.map((group) => (
          <section key={group.key} className="mb-5">
            <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-fg-faint uppercase">
              {group.title}
            </div>
            <div className="space-y-1.5">
              {group.entries.map((entry) => (
                <CredentialRow key={entry.name} entry={entry} />
              ))}
            </div>
          </section>
        ))
      )}
      {visible.length === 0 && credentials.length > 0 && (
        <div className="px-1 py-3 text-[11px] text-fg-faint">{t("settings.noCredentialMatchesTheFilter")}</div>
      )}
    </div>
  );
}

function groupCredentials(entries: CredentialEntry[]): { key: string; title: string; entries: CredentialEntry[] }[] {
  const groups = new Map<string, CredentialEntry[]>();
  for (const entry of entries) {
    const titles = new Set(entry.references.map((reference) => reference.groupTitle));
    const title =
      titles.size === 0
        ? "Unreferenced (dotenv only)"
        : titles.size > 1
          ? "Shared across groups"
          : ([...titles][0] as string);
    const list = groups.get(title) ?? [];
    list.push(entry);
    groups.set(title, list);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => {
      // Referenced groups first (alphabetical), unreferenced last.
      if (a === "Unreferenced (dotenv only)") return 1;
      if (b === "Unreferenced (dotenv only)") return -1;
      return a.localeCompare(b);
    })
    .map(([title, groupEntries]) => ({ key: title, title: title === "Unreferenced (dotenv only)" ? t("settings.unreferencedCredentials") : title === "Shared across groups" ? t("settings.sharedCredentials") : title, entries: groupEntries }));
}

function CredentialRow({ entry }: { entry: CredentialEntry }) {
  return (
    <div className="rounded-md border border-line bg-bg-elev px-3 py-2">
      <CredentialValueEditor name={entry.name} />
      {entry.references.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {entry.references.map((reference) => (
            <Badge
              key={reference.path}
              tone="gray"
              title={`${reference.path} (${reference.kind === "header" ? t("settings.httpHeaderValue") : t("settings.environmentVariable")})`}
            >
              {reference.path}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
