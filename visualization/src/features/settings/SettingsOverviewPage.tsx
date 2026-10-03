import { settingsText } from "./i18n";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Layers,
} from "lucide-react";
import { useState } from "react";

import type { JsonValue, PresetSummary } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { SectionCard } from "../../components/ui/Card";
import { JsonTree } from "../../components/ui/JsonTree";
import { CopyButton } from "../../components/ui/CopyButton";
import { SettingsDisclosure } from "./SettingsDisclosure";
import {
  activityReasonText,
  draftIssues,
  selectDraftCount,
  useConfigDraftStore,
  type ApplyFailure,
} from "./draft/store";
import {
  isRedactedValue,
  pendingActivationChanges,
  type DraftEntry,
} from "./draft/model";
import { pageForDraft, pageForPath, SETTINGS_PAGES } from "./pages";
import { useSettingsUiStore } from "./uiStore";

/** Compact one-line rendering of a config value for summaries. */
function previewValue(value: JsonValue | undefined, limit = 60): string {
  if (value === undefined) return "—";
  if (isRedactedValue(value)) return "••••••";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

/**
 * The settings overview (P10): running configuration facts, saved-but-not-
 * activated changes, local draft changes grouped by owning page, and the
 * run-plan summary that routes to the plans page for capture/management.
 */
export function SettingsOverviewPage() {
  const saved = useConfigDraftStore((s) => s.saved);
  const active = useConfigDraftStore((s) => s.active);
  const presets = useConfigDraftStore((s) => s.presets);
  const drafts = useConfigDraftStore((s) => s.drafts);
  const stale = useConfigDraftStore((s) => s.stale);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const issueCount = useConfigDraftStore((s) => draftIssues(s).length);
  const resolveStale = useConfigDraftStore((s) => s.resolveStale);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const [sourceQuery, setSourceQuery] = useState("");
  if (saved === null || active === null) return null;

  const pending = pendingActivationChanges(saved, active);
  const activity = saved.activity;
  const sources = saved.sources.filter((source) =>
    `${source.id} ${source.path ?? ""}`.toLocaleLowerCase().includes(sourceQuery.trim().toLocaleLowerCase()));
  return (
    <div className="settings-form mx-auto flex max-w-3xl flex-col gap-4 p-5">
      <SectionCard title="运行配置" actions={<Badge tone={activity.can_reload ? "green" : "yellow"}>
        {activity.can_reload ? "可应用修改" : "忙碌"}</Badge>}>
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-fg-muted">
          <CheckCircle2 size={16} className="shrink-0 text-accent" />
          <span>{saved.pending_reload ? "有已保存配置等待激活。" : "已保存配置与当前运行配置一致。"}</span>
        </div>
        {!activity.can_reload && <p className="mt-2 text-[12px] text-fg-muted">{settingsText(activityReasonText(activity.reason))}</p>}
        {draftCount === 0 && <p className="mt-2 text-[12px] text-fg-faint">没有本地修改</p>}
      </SectionCard>

      {draftCount > 0 && <SectionCard title="本地修改" description="这些修改尚未保存；在底部一次应用全部修改。"
        actions={issueCount > 0 ? <Badge tone="yellow">{issueCount} 项字段问题</Badge> : <Badge tone="accent">{draftCount} 项</Badge>}>
        <DraftList drafts={drafts} stale={stale} onResolveStale={resolveStale}
          onLocate={(entry) => { const owner = pageForDraft(entry); if (owner !== null) navigateTo(owner.id, entry.path); }} />
      </SectionCard>}

      {saved.pending_reload && <SectionCard title="已保存待激活" description="保存值与运行值的差异，应用或重载后生效。">
        {draftCount > 0 && <div className="mb-2 flex items-center gap-1.5 rounded-md bg-info-soft px-2.5 py-1.5 text-[12px] text-info">
          <ArrowRight size={12} /> 应用本地修改时也会激活这些已保存修改。
        </div>}
        <div className="space-y-1">{pending.map((change) => {
          const owner = pageForPath(change.path);
          return <button key={change.path} className="flex w-full flex-wrap items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-hover"
            onClick={() => owner !== null && navigateTo(owner.id, change.path)}>
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg">{change.path}</span>
            {owner !== null && <Badge tone="gray">{SETTINGS_PAGES[owner.id].title}</Badge>}
            <span className="w-full break-all text-[11px] text-fg-faint">{previewValue(change.active, 50)} → {previewValue(change.saved, 50)}</span>
          </button>;
        })}</div>
      </SectionCard>}

      <SectionCard title="运行方案" description="保存模型路由与可选预算，方便切换。"
        actions={<Button variant="ghost" size="xs" onClick={() => navigateTo("plans")}>管理方案</Button>}>
        {presets === null || presets.length === 0
          ? <p className="text-[12px] text-fg-muted">尚未保存运行方案。</p>
          : <div className="space-y-1.5">{presets.map((preset) =>
              <PresetRow key={preset.id} preset={preset} onOpen={() => navigateTo("plans")} />)}</div>}
      </SectionCard>

      <SettingsDisclosure title="配置来源与运行详情" meta={<span className="text-[11px] text-fg-faint">{saved.sources.length} 个来源</span>}>
        <div className="space-y-3 p-3">
          <div className="text-[12px] text-fg-muted">运行代次 <span className="break-all font-mono text-fg">{active.generation_id || "—"}</span></div>
          <input aria-label="筛选配置来源" placeholder="按名称或路径筛选…" value={sourceQuery} onChange={(event) => setSourceQuery(event.target.value)}
            className="w-full rounded-md border border-line bg-bg px-2.5 py-1.5 text-[12px] outline-none focus:border-accent" />
          <div className="space-y-1">{sources.map((source) =>
            <details key={source.id} className="rounded-md border border-line">
              <summary className="flex cursor-pointer items-center gap-2 px-2.5 py-2 text-[12px]">
                <span className="min-w-0 flex-1 truncate font-mono" title={source.id}>{source.id}</span>
                {!source.exists && <Badge tone="gray">缺失</Badge>}
                {!source.writable && <Badge tone="gray">只读</Badge>}
              </summary>
              <div className="flex items-start gap-2 border-t border-line p-2.5">
                <span className="min-w-0 flex-1 break-all font-mono text-[11px] text-fg-muted">{source.path === source.id ? "名称即来源路径" : source.path || "未提供路径"}</span>
                <CopyButton label="复制路径" text={() => source.path || source.id} />
              </div>
            </details>)}</div>
          {sources.length === 0 && <p className="text-[12px] text-fg-faint">没有匹配的来源。</p>}
        </div>
      </SettingsDisclosure>
    </div>
  );
}

function DraftList({
  drafts,
  stale,
  onLocate,
  onResolveStale,
}: {
  drafts: Record<string, DraftEntry>;
  stale: Record<string, true>;
  onLocate: (entry: DraftEntry) => void;
  onResolveStale: (key: string, action: "adopt" | "keep") => void;
}) {
  const entries = Object.values(drafts).sort(
    (a, b) => a.sourceId.localeCompare(b.sourceId) || a.path.localeCompare(b.path),
  );
  return (
    <div className="space-y-1">
      {entries.map((entry) => {
        const isStale = stale[entry.key] === true;
        return (
          <div
            key={entry.key}
            className="flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors hover:bg-hover"
          >
            <Badge tone={entry.op.op === "delete" ? "red" : "accent"}>
              {entry.op.op}
            </Badge>
            <button
              className="min-w-0 flex-1 truncate text-left font-mono text-[12px] text-fg"
              onClick={() => onLocate(entry)}
              title={entry.sourceId}
            >
              {entry.path}
            </button>
            {entry.op.op === "set" && (
              <span className="hidden max-w-[200px] truncate font-mono text-[11px] text-fg-faint md:block">
                {previewValue(entry.op.value, 28)}
              </span>
            )}
            {isStale && (
              <span className="flex shrink-0 items-center gap-1">
                <Badge tone="yellow" title="The saved baseline changed while you were editing">
                  <AlertTriangle size={10} />{settingsText("stale")}</Badge>
                <Button
                  variant="ghost"
                  size="xs"
                  title="Drop the local change and use the new baseline"
                  onClick={() => onResolveStale(entry.key, "adopt")}
                >{settingsText("Adopt")}</Button>
                <Button
                  variant="ghost"
                  size="xs"
                  title="Keep the local change"
                  onClick={() => onResolveStale(entry.key, "keep")}
                >{settingsText("Keep")}</Button>
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function PresetRow({
  preset,
  onOpen,
}: {
  preset: PresetSummary;
  onOpen: () => void;
}) {
  const issueCount = preset.validation_issues.length;
  return (
    <button
      className="flex w-full items-center gap-2 rounded-md border border-line px-3 py-2 text-left transition-colors hover:bg-hover"
      onClick={onOpen}
    >
      <Layers size={14} className="shrink-0 text-fg-faint" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium text-fg">
            {preset.name}
          </span>
          {preset.active_match && <Badge tone="green">运行中</Badge>}
          {!preset.active_match && preset.saved_match && (
            <Badge tone="blue">匹配已保存</Badge>
          )}
          {issueCount > 0 && (
            <Badge
              tone="yellow"
              title="Dependencies of this plan are currently missing"
            >
              {issueCount} {issueCount === 1 ? "issue" : "issues"}
            </Badge>
          )}
        </div>
        {preset.description !== "" && (
          <div className="mt-0.5 truncate text-[11px] text-fg-muted">
            {preset.description}
          </div>
        )}
      </div>
      <span className="shrink-0 text-[10px] text-fg-faint">
        {preset.included_scopes.join(" · ")}
      </span>
    </button>
  );
}

/** Batch-level apply failure rendering shared by the overview banner. */
export function ApplyFailureBanner({ failure }: { failure: ApplyFailure }) {
  const clearApplyFailure = useConfigDraftStore((s) => s.clearApplyFailure);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const locatedPage =
    failure.kind === "config-invalid" && failure.key !== null
      ? pageForPath(failure.key)
      : null;

  // The structured details stay available verbatim for inspection (plan
  // §15.1); locating never parses them for field names.
  const details = "details" in failure ? failure.details : null;
  const hasDetails = details !== null && Object.keys(details).length > 0;

  const tone =
    failure.kind === "activation-unavailable"
      ? "border-warning/30 bg-warning-soft text-warning"
      : "border-danger/30 bg-danger-soft text-danger";

  return (
    <div
      className={`flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5 text-[12px] leading-5 ${tone}`}
    >
      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">
          {failure.kind === "config-invalid"
              ? "配置被拒绝，草稿未改变。"
            : failure.kind === "request-invalid"
              ? "请求被拒绝，草稿未改变。"
              : failure.kind === "activation-unavailable"
                ? "当前无法激活配置，草稿已保留。"
                : failure.kind === "activation-failed"
                  ? "激活失败，之前的运行配置仍在使用。"
                  : failure.kind === "api-error"
                    ? `端点拒绝了配置应用（${failure.code}）。`
                    : "配置应用结果未知，草稿已保留。"}
        </div>
        <div className="mt-0.5 break-words opacity-90">{failure.message}</div>
        {failure.kind === "config-invalid" && failure.key !== null && (
          <div className="mt-0.5 font-mono text-[11px] break-all opacity-90">
            key: {failure.key}
          </div>
        )}
        {hasDetails && (
          <div className="mt-1.5">
            <button
              type="button"
              className="font-medium underline opacity-80 hover:opacity-100"
              onClick={() => setDetailsOpen((open) => !open)}
            >
              {detailsOpen ? "隐藏详情" : "查看详情"}
            </button>
            {detailsOpen && (
              <div className="mt-1.5 max-h-64 overflow-y-auto text-fg">
                <JsonTree value={details} defaultExpanded={false} />
              </div>
            )}
          </div>
        )}
      </div>
      {locatedPage !== null && failure.kind === "config-invalid" && (
        <Button
          variant="outline"
          size="xs"
          onClick={() => {
            navigateTo(locatedPage.id, failure.key);
            clearApplyFailure();
          }}
        >
          定位
        </Button>
      )}
      <Button variant="ghost" size="xs" onClick={() => clearApplyFailure()}>
        关闭
      </Button>
    </div>
  );
}

/** Success-with-diagnostics note; never implies the apply failed. */
export function CleanupDiagnosticsBanner() {
  const cleanupDiagnostics = useConfigDraftStore((s) => s.cleanupDiagnostics);
  const dismiss = useConfigDraftStore((s) => s.dismissCleanupDiagnostics);
  if (cleanupDiagnostics === null) return null;
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-warning/30 bg-warning-soft px-3.5 py-2.5 text-[12px] leading-5 text-warning">
      <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        配置已应用，但部分旧资源未能清理：
        <ul className="mt-1 list-inside list-disc font-mono text-[11px]">
          {cleanupDiagnostics.map((item, index) => (
            <li key={index} className="break-all">
              {previewValue(item, 120)}
            </li>
          ))}
        </ul>
      </div>
      <Button variant="ghost" size="xs" onClick={dismiss}>
        关闭
      </Button>
    </div>
  );
}
