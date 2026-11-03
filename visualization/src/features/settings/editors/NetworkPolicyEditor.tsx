import { useI18n } from "../../../i18n";
import type { JsonValue } from "../../../api/v2/types";
import { SectionCard } from "../../../components/ui/Card";
import { isPlainRecord } from "../draft/model";
import { TextInput, selectClass } from "../models/controls";
import { FieldRow, useDraftField } from "./controls";

/** One policy object; changing mode removes addresses that no longer apply. */
export function NetworkPolicyEditor({
  value, parentLabel, disabled = false, root = false, onChange,
}: {
  value: JsonValue | undefined;
  parentLabel: string;
  disabled?: boolean;
  root?: boolean;
  onChange: (value: Record<string, JsonValue>) => void;
}) {
  const { t } = useI18n();
  const policy = isPlainRecord(value) ? value : {};
  const mode = typeof policy.mode === "string" ? policy.mode : "inherit";
  return (
    <div className="w-full space-y-2 text-xs">
      <select aria-label={t("settings.proxyMode")} className={selectClass} value={mode} disabled={disabled}
        onChange={(event) => onChange({ mode: event.target.value })}>
        <option value="inherit">{root ? t("settings.inheritEnvironment") : t("settings.inheritParent")}</option>
        <option value="direct">{root ? t("settings.disableProxy") : t("settings.directConnection")}</option>
        <option value="override">{root ? t("settings.enableProxy") : t("settings.overrideProxy")}</option>
      </select>
      {mode === "inherit" && <p className="text-fg-muted">{t("settings.inheritedProxy")}{parentLabel}</p>}
      {mode === "direct" && <p className="text-fg-muted">{t("settings.noProxyHint")}</p>}
      {mode === "override" && <>
        <p className="text-fg-muted">{t("settings.replaceProxyHint")}</p>
        {([
          ["http_proxy", t("settings.httpProxy"), "http://127.0.0.1:7897"],
          ["https_proxy", t("settings.httpsProxy"), "http://127.0.0.1:7897"],
          ["no_proxy", t("settings.proxyBypass"), "localhost,127.0.0.1,::1"],
        ] as const).map(([key, label, placeholder]) => (
          <label key={key} className="block space-y-1 text-fg-muted">
            <span>{label}</span>
            <TextInput ariaLabel={label} value={typeof policy[key] === "string" ? policy[key] : ""}
              placeholder={placeholder} mono disabled={disabled}
              onCommit={(next) => onChange({ ...policy, [key]: next.trim() })} />
          </label>
        ))}
        <p className="text-fg-faint">{t("settings.bypassHint")}</p>
      </>}
    </div>
  );
}

/** Bind an atomic policy to the existing saved-configuration draft lifecycle. */
export function NetworkPolicyField({ path, title, parentLabel, root = false }: {
  path: string; title?: string; parentLabel?: string; root?: boolean;
}) {
  const { t } = useI18n();
  const api = useDraftField(path);
  return (
    <SectionCard title={title ?? t("settings.networkSettings")}>
      <FieldRow path={path} api={api} titleOverride={t("settings.proxySettings")}>
        <NetworkPolicyEditor value={api.value} disabled={api.readOnly !== null} root={root}
          parentLabel={parentLabel ?? t("settings.rootNetwork")} onChange={api.set} />
      </FieldRow>
    </SectionCard>
  );
}
