/**
 * Credential value editing shared by the provider pages and the dedicated
 * Credentials page (plan §16.1/§16.6). Secret values live in the dotenv
 * source and are redacted in every read projection (`"<redacted>"`); the
 * masked value is display-only — typing a new value stages a dotenv `set`
 * draft, and only the explicit delete button stages a `delete`. Nothing is
 * written back from the placeholder.
 */

import { useState } from "react";
import { Check, KeyRound, Trash2 } from "lucide-react";

import { Badge } from "../../../components/ui/Badge";
import { Button, IconButton } from "../../../components/ui/Button";
import { isRedactedValue } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import { inputClass } from "./controls";

export type CredentialReadiness =
  | "configured" // a value exists in dotenv (or was staged)
  | "missing" // referenced but no value anywhere visible
  | "deleted-pending"; // staged for deletion

/** Derive the readiness of one env name from the saved dotenv source + drafts. */
export function credentialReadiness(
  name: string,
  state = useConfigDraftStore.getState(),
): { readiness: CredentialReadiness; draftState: "none" | "set" | "deleted" } {
  const dotenv = state.saved?.sources.find((source) => source.kind === "dotenv");
  const sourceId = dotenv?.id ?? "dotenv";
  const draft = Object.values(state.drafts).find(
    (entry) => entry.sourceId === sourceId && entry.path === name,
  );
  if (draft !== undefined) {
    return {
      readiness: draft.op.op === "set" ? "configured" : "deleted-pending",
      draftState: draft.op.op === "set" ? "set" : "deleted",
    };
  }
  const stored = dotenv?.values[name];
  const configured =
    typeof stored === "string" && (isRedactedValue(stored) || stored.trim() !== "");
  return { readiness: configured ? "configured" : "missing", draftState: "none" };
}

/**
 * One credential row: name, readiness and the value editor. Editing the value
 * stages the shared dotenv draft (the same draft the Credentials page edits).
 */
export function CredentialValueEditor({
  name,
  compact = false,
}: {
  name: string;
  compact?: boolean;
}) {
  const state = useConfigDraftStore();
  const { readiness, draftState } = credentialReadiness(name, state);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");

  const dotenv = state.saved?.sources.find((source) => source.kind === "dotenv");
  const dotenvWritable = dotenv?.writable !== false;
  const commit = () => {
    if (value === "") return;
    state.setValue(dotenv?.id ?? "dotenv", name, value);
    setValue("");
    setEditing(false);
  };

  return (
    <div
      className={`flex items-center gap-2 rounded-md border border-line bg-bg px-2 py-1.5 ${
        compact ? "" : "min-h-9"
      }`}
    >
      <KeyRound size={12} className="shrink-0 text-fg-faint" />
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg">
        {name}
      </span>
      {readiness === "configured" && draftState === "none" && (
        <Badge tone="green" title="A value exists in the project dotenv file">
          •••••• configured
        </Badge>
      )}
      {readiness === "configured" && draftState === "set" && (
        <Badge tone="accent" title="A new value is staged in the local draft">
          •••••• pending apply
        </Badge>
      )}
      {readiness === "missing" && (
        <Badge tone="yellow" title="No value found in the dotenv source">
          missing
        </Badge>
      )}
      {readiness === "deleted-pending" && (
        <Badge tone="red" title="Deletion is staged in the local draft">
          delete pending
        </Badge>
      )}
      {editing ? (
        <>
          <input
            autoFocus
            aria-label={`New value for ${name}`}
            type="password"
            value={value}
            placeholder="Enter new value…"
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") {
                setValue("");
                setEditing(false);
              }
            }}
            className={`${inputClass} h-7 max-w-44 font-mono text-[11px]`}
          />
          <IconButton label="Stage new value" disabled={value === ""} onClick={commit}>
            <Check size={13} />
          </IconButton>
          <Button
            size="xs"
            variant="ghost"
            onClick={() => {
              setValue("");
              setEditing(false);
            }}
          >
            Cancel
          </Button>
        </>
      ) : (
        <Button
          size="xs"
          variant="ghost"
          disabled={!dotenvWritable}
          title={
            dotenvWritable
              ? "Stage a new value in the shared credentials draft"
              : "The dotenv source is read-only"
          }
          onClick={() => setEditing(true)}
        >
          Set value
        </Button>
      )}
      {readiness !== "missing" && draftState !== "deleted" && (
        <IconButton
          label="Stage credential deletion"
          disabled={!dotenvWritable}
          onClick={() => state.deleteValue(dotenv?.id ?? "dotenv", name)}
        >
          <Trash2 size={13} />
        </IconButton>
      )}
    </div>
  );
}
