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
  const policy = isPlainRecord(value) ? value : {};
  const mode = typeof policy.mode === "string" ? policy.mode : "inherit";
  return (
    <div className="w-full space-y-2 text-xs">
      <select aria-label="代理模式" className={selectClass} value={mode} disabled={disabled}
        onChange={(event) => onChange({ mode: event.target.value })}>
        <option value="inherit">{root ? "继承环境代理" : "继承上级"}</option>
        <option value="direct">{root ? "关闭代理" : "直接连接"}</option>
        <option value="override">{root ? "开启并指定代理" : "使用覆盖配置"}</option>
      </select>
      {mode === "inherit" && <p className="text-fg-muted">继承：{parentLabel}</p>}
      {mode === "direct" && <p className="text-fg-muted">不使用代理；子进程清除继承的代理变量。</p>}
      {mode === "override" && <>
        <p className="text-fg-muted">完整覆盖上级设置。未填写的协议直接连接。</p>
        {([
          ["http_proxy", "HTTP 代理", "http://127.0.0.1:7897"],
          ["https_proxy", "HTTPS 代理", "http://127.0.0.1:7897"],
          ["no_proxy", "不使用代理的地址", "localhost,127.0.0.1,::1"],
        ] as const).map(([key, label, placeholder]) => (
          <label key={key} className="block space-y-1 text-fg-muted">
            <span>{label}</span>
            <TextInput ariaLabel={label} value={typeof policy[key] === "string" ? policy[key] : ""}
              placeholder={placeholder} mono disabled={disabled}
              onCommit={(next) => onChange({ ...policy, [key]: next.trim() })} />
          </label>
        ))}
        <p className="text-fg-faint">绕过地址以逗号分隔；未配置时绕过本机地址，清空已配置值表示不绕过。</p>
      </>}
    </div>
  );
}

/** Bind an atomic policy to the existing saved-configuration draft lifecycle. */
export function NetworkPolicyField({ path, title = "网络配置", parentLabel = "系统网络默认配置", root = false }: {
  path: string; title?: string; parentLabel?: string; root?: boolean;
}) {
  const api = useDraftField(path);
  return (
    <SectionCard title={title}>
      <FieldRow path={path} api={api} titleOverride="代理设置">
        <NetworkPolicyEditor value={api.value} disabled={api.readOnly !== null} root={root}
          parentLabel={parentLabel} onChange={api.set} />
      </FieldRow>
    </SectionCard>
  );
}
