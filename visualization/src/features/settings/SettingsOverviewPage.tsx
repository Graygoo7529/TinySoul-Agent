import { settingsText } from "./i18n";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  Layers,
} from "lucide-react";
import { useState } from "react";

import type { JsonValue, PresetSummary } from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { SectionCard } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { JsonTree } from "../../components/ui/JsonTree";
import { useConnectionStore } from "../../store/connectionStore";
import { reloadSaved } from "./applyController";
import {
  activityReasonText,
  activationBlocker,
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
  const clients = useConnectionStore((s) => s.clients);
  const saved = useConfigDraftStore((s) => s.saved);
  const active = useConfigDraftStore((s) => s.active);
  const presets = useConfigDraftStore((s) => s.presets);
  const drafts = useConfigDraftStore((s) => s.drafts);
  const stale = useConfigDraftStore((s) => s.stale);
  const draftCount = useConfigDraftStore(selectDraftCount);
  const blocker = useConfigDraftStore(activationBlocker);
  const applyPhase = useConfigDraftStore((s) => s.applyPhase);
  const resolveStale = useConfigDraftStore((s) => s.resolveStale);
  const navigateTo = useSettingsUiStore((s) => s.navigateTo);

  if (saved === null || active === null) return null;

  const pending = pendingActivationChanges(saved, active);
  const activity = saved.activity;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-5">
      <SectionCard
        title="运行配置"
        description="当前 Agent generation 正在使用的配置。"
        actions={
          activity.can_reload ? (
            <Badge tone="green">空闲</Badge>
          ) : (
            <Badge tone="yellow" title={settingsText(activityReasonText(activity.reason))}>
              忙碌
            </Badge>
          )
        }
      >
        <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12px]">
          <dt className="text-fg-faint">运行代次</dt>
          <dd className="font-mono break-all text-fg">
            {active.generation_id || "—"}
          </dd>
          <dt className="text-fg-faint">运行状态</dt>
          <dd className="text-fg">
            {activity.state}
            {activity.reason !== "" && (
              <span className="ml-1.5 text-fg-muted">
                — {settingsText(activityReasonText(activity.reason))}
              </span>
            )}
          </dd>
          <dt className="text-fg-faint">待激活修改</dt>
          <dd className="text-fg">
            {saved.pending_reload ? `${pending.length} 项` : "无"}
          </dd>
        </dl>

        <div className="mt-3 border-t border-line pt-3">
          <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-fg-muted uppercase">
            配置来源
          </div>
          <div className="space-y-1">
            {saved.sources.map((source) => (
              <div
                key={source.id}
                className="flex items-center gap-2 text-[12px]"
              >
                <span className="font-mono text-fg">{source.id}</span>
                <span className="truncate font-mono text-[11px] text-fg-faint">
                  {source.path || "—"}
                </span>
                <span className="ml-auto flex shrink-0 items-center gap-1">
                  {!source.exists && <Badge tone="gray">缺失</Badge>}
                  {!source.writable && <Badge tone="gray">只读</Badge>}
                </span>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="待激活"
        description="已保存但不同于运行配置的值，会在下次应用或重载时激活。"
        actions={
          saved.pending_reload && draftCount === 0 ? (
            <Button
              variant="primary"
              size="xs"
              disabled={blocker !== null || clients === null}
              loading={applyPhase === "reloading"}
              title={blocker ?? "Activate the saved configuration"}
              onClick={() => clients !== null && void reloadSaved(clients)}
            >
              激活已保存配置
            </Button>
          ) : undefined
        }
      >
        {pending.length === 0 ? (
          <div className="text-[12px] text-fg-muted">
            已保存配置与当前运行配置一致。
          </div>
        ) : (
          <>
            {draftCount > 0 && (
              <div className="mb-2 flex items-center gap-1.5 rounded-md bg-info-soft px-2.5 py-1.5 text-[12px] text-info">
                <ArrowRight size={12} /> 应用本地修改时也会激活这些已保存修改。
              </div>
            )}
            <div className="space-y-1">
              {pending.map((change) => {
                const owner = pageForPath(change.path);
                return (
                  <button
                    key={change.path}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hover"
                    onClick={() =>
                      owner !== null && navigateTo(owner.id, change.path)
                    }
                  >
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg">
                      {change.path}
                    </span>
                    <span className="hidden max-w-[220px] truncate font-mono text-[11px] text-fg-faint sm:block">
                      {previewValue(change.active, 30)} → {previewValue(change.saved, 30)}
                    </span>
                    {owner !== null && (
                      <Badge tone="gray">{SETTINGS_PAGES[owner.id].title}</Badge>
                    )}
                  </button>
                );
              })}
            </div>
          </>
        )}
      </SectionCard>

      <SectionCard
        title="本地修改"
        description="当前窗口中的未提交草稿；应用时会一次保存并激活。"
      >
        {draftCount === 0 ? (
          <div className="text-[12px] text-fg-muted">
            没有本地修改。各设置页的编辑会集中在这里，直到应用或放弃。
          </div>
        ) : (
          <DraftList
            drafts={drafts}
            stale={stale}
            onLocate={(entry) => {
              const owner = pageForDraft(entry);
              if (owner !== null) navigateTo(owner.id, entry.path);
            }}
            onResolveStale={resolveStale}
          />
        )}
      </SectionCard>

      <SectionCard
        title="运行方案"
        description="命名的模型路由与预算预设，可在运行方案页保存、管理和应用。"
        actions={
          <Button variant="ghost" size="xs" onClick={() => navigateTo("plans")}>
            管理方案
          </Button>
        }
      >
        {presets === null || presets.length === 0 ? (
          <EmptyState
            icon={<CircleDashed size={20} />}
            title="还没有运行方案"
            description="方案保存模型链、Action 绑定和可选预算，方便快速切换。"
            action={
              <Button variant="outline" size="sm" onClick={() => navigateTo("plans")}>
                打开运行方案
              </Button>
            }
          />
        ) : (
          <div className="space-y-1.5">
            {presets.map((preset) => (
              <PresetRow
                key={preset.id}
                preset={preset}
                onOpen={() => navigateTo("plans")}
              />
            ))}
          </div>
        )}
      </SectionCard>
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
