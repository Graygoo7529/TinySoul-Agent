import { useEffect, useState } from "react";
import { AlertCircle, Check, Eye, EyeOff, Plus, Trash2 } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import type { ConfigCatalog, ConfigStatus } from "../../types";
import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { deriveCredentials, type CredentialSetting } from "./model";
import { SettingsGroupSection } from "./SettingsGroupSection";

const inputClass =
  "focus-ring h-8 rounded-lg border border-line bg-bg-elev px-2.5 text-[13px] outline-none transition-colors focus:border-accent disabled:cursor-not-allowed disabled:opacity-50";

export function CredentialsSettingsPage({
  client,
  status,
  catalog,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
}) {
  const { source, groups } = deriveCredentials(status, catalog);
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const writable = Boolean(source?.writable && status.activity.can_write && !savingPath);

  const mutate = async (key: string, nextValue?: string) => {
    if (!source) return false;
    try {
      const mutation = nextValue === undefined
        ? { source_id: source.id, path: key, op: "delete" as const }
        : { source_id: source.id, path: key, op: "set" as const, value: nextValue };
      const result = await patch(client, mutation);
      pushToast("success", `Credentials active · ${shortId(result.generation_id)}`);
      return true;
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
      return false;
    }
  };

  return (
    <div>
      {!status.activity.can_write && (
        <div className="flex items-center gap-2 border-b border-warning/30 bg-warning-soft px-5 py-2.5 text-[12px] text-warning">
          <AlertCircle size={14} />
          {status.activity.reason || "Credentials are read-only while a turn is active."}
        </div>
      )}
      <div className="flex min-h-12 items-center justify-between gap-3 border-b border-line bg-bg-sunken/40 px-5 py-2">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-fg-muted">Environment credentials</div>
          <div className="truncate font-mono text-[10px] text-fg-faint">{source?.path ?? ".env"}</div>
        </div>
        <Button
          size="xs"
          variant="outline"
          disabled={!writable}
          onClick={() => setAdding((current) => !current)}
        >
          <Plus size={13} /> Add
        </Button>
      </div>

      {adding && (
        <div className="grid gap-2 border-b border-line px-5 py-3 md:grid-cols-[minmax(180px,1fr)_minmax(240px,2fr)_auto]">
          <input
            aria-label="Environment variable name"
            value={name}
            placeholder="VARIABLE_NAME"
            onChange={(event) => setName(event.target.value.toUpperCase())}
            className={`${inputClass} font-mono text-[12px]`}
          />
          <input
            aria-label="Credential value"
            type="password"
            value={value}
            placeholder="Value"
            onChange={(event) => setValue(event.target.value)}
            className={inputClass}
          />
          <Button
            size="xs"
            variant="primary"
            disabled={!isEnvName(name) || !writable}
            onClick={() => {
              void mutate(name, value).then((applied) => {
                if (!applied) return;
                setName("");
                setValue("");
                setAdding(false);
              });
            }}
          >
            <Check size={13} /> Apply
          </Button>
        </div>
      )}

      {groups.length === 0 ? (
        <EmptyState title="No credentials declared" />
      ) : (
        <div>
          {groups.map((group) => (
            <SettingsGroupSection
              key={group.id}
              title={group.title}
              description={group.description}
              meta={<Badge>{group.credentials.length}</Badge>}
            >
              <div className="divide-y divide-line">
                {group.credentials.map((credential) => (
                  <CredentialRow
                    key={credential.name}
                    credential={credential}
                    disabled={!writable}
                    saving={savingPath === credential.name}
                    onSave={(nextValue) => mutate(credential.name, nextValue)}
                    onDelete={() => mutate(credential.name)}
                  />
                ))}
              </div>
            </SettingsGroupSection>
          ))}
        </div>
      )}
    </div>
  );
}

function CredentialRow({
  credential,
  disabled,
  saving,
  onSave,
  onDelete,
}: {
  credential: CredentialSetting;
  disabled: boolean;
  saving: boolean;
  onSave: (value: string) => Promise<boolean>;
  onDelete: () => Promise<boolean>;
}) {
  const [draft, setDraft] = useState(credential.value);
  const [visible, setVisible] = useState(false);

  useEffect(() => setDraft(credential.value), [credential.value]);

  return (
    <div className="grid min-h-16 gap-3 px-5 py-3 md:grid-cols-[minmax(220px,1fr)_minmax(280px,420px)] md:items-center">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[12px] font-medium text-fg">{credential.name}</span>
          <Badge tone={credential.configured ? "green" : "gray"}>
            {credential.configured ? "Configured" : credential.present ? "Empty" : "Unset"}
          </Badge>
        </div>
        {credential.declaredBy.length > 0 && (
          <div
            className="mt-1 truncate font-mono text-[10px] text-fg-faint"
            title={credential.declaredBy.join(", ")}
          >
            {credential.declaredBy.join(", ")}
          </div>
        )}
      </div>
      <div className="flex min-w-0 items-center gap-1.5">
        <input
          aria-label={`${credential.name} value`}
          type={visible ? "text" : "password"}
          autoComplete="off"
          value={draft}
          disabled={disabled || saving}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && draft !== credential.value) void onSave(draft);
          }}
          className={`${inputClass} min-w-0 flex-1 font-mono text-[12px]`}
        />
        <IconButton label={visible ? "Hide value" : "Show value"} onClick={() => setVisible(!visible)}>
          {visible ? <EyeOff size={15} /> : <Eye size={15} />}
        </IconButton>
        <IconButton
          label="Apply credential"
            disabled={
              disabled ||
              saving ||
              (credential.present && draft === credential.value)
            }
          onClick={() => void onSave(draft)}
        >
          <Check size={15} />
        </IconButton>
        <IconButton
          label="Delete credential"
          disabled={disabled || saving || !credential.present}
          onClick={() => void onDelete()}
          className="hover:text-danger"
        >
          <Trash2 size={15} />
        </IconButton>
      </div>
    </div>
  );
}

function isEnvName(value: string): boolean {
  return /^[A-Z_][A-Z0-9_]*$/.test(value);
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
