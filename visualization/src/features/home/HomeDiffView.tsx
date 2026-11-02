/**
 * Home overlay-change diff (center cover, plan §11).
 *
 * Reads the actual → effective unified diff of one overlay change and shows
 * it in two modes: unified (as emitted, line classes) and side-by-side
 * (actual left, effective right, real line numbers). baseline_diverged is a
 * fact banner that suggests re-reading or organizing Home — the page never
 * becomes a merge editor: no accept/reject, no line staging.
 */

import { useMemo, useState, type ReactElement } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Columns2,
  GitCompareArrows,
  Loader2,
  RotateCcw,
  Rows3,
  Sparkles,
} from "lucide-react";

import type {
  HomeContentItem,
  HomeDiffMetadata,
  HomeDiffPage,
} from "../../api/v2/types";
import { nextContinuation } from "../../api/v2/pagination";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Tabs } from "../../components/ui/Tabs";
import { useConnectionStore } from "../../store/connectionStore";
import { useOwnerPage } from "../resources/useOwnerPage";
import { ReflectionDialog } from "../resources/ReflectionDialog";
import { parseDiffLines, toSideRows, type DiffLine, type SideRow } from "./diffModel";
import { useHomePage } from "./store";

type DiffMode = "unified" | "side";

const KIND_TONES: Record<string, BadgeTone> = {
  created: "green",
  modified: "yellow",
  deleted: "red",
};

export function HomeDiffView({
  epoch,
  ref,
}: {
  epoch: number;
  ref: string;
}): ReactElement {
  const diffKind = useHomePage((s) => s.diffKind);
  const [mode, setMode] = useState<DiffMode>("unified");
  const [organizeOpen, setOrganizeOpen] = useState(false);
  const page = useOwnerPage<HomeContentItem, HomeDiffPage, HomeDiffMetadata>(
    (token, signal) => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.home.diff(
        { ref, continuation: token ?? undefined },
        { signal },
      );
    },
    nextContinuation,
    (page) =>
      page.metadata ?? { baseline_diverged: false, actual_chars: 0, effective_chars: 0 },
    [epoch, ref],
  );

  const diffText = useMemo(() => page.items.map((item) => item.text).join(""), [page.items]);
  const lines = useMemo(() => parseDiffLines(diffText), [diffText]);
  const sideRows = useMemo(() => (mode === "side" ? toSideRows(lines) : []), [mode, lines]);
  const metadata = page.metadata;
  const errorMessage =
    page.error instanceof Error ? page.error.message : String(page.error ?? "");
  // The prefill only names the change under review (ref + kind from the
  // changes fact); it never prejudges accept/reject — that stays with the
  // Reflection, and the user can edit or clear it before submitting.
  const reviewPrefill = `重点审核这条 Home 变更：${ref}${diffKind !== null ? `（${diffKind}）` : ""}。`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <Button
          variant="ghost"
          size="xs"
          aria-label="返回变更列表"
          onClick={() => useHomePage.getState().closeDiff()}
        >
          <ArrowLeft size={12} />
          Changes
        </Button>
        <GitCompareArrows size={13} className="shrink-0 text-fg-faint" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium" title={ref}>
          {ref.replace(/^home:/, "")}
        </span>
        {diffKind !== null && (
          <Badge tone={KIND_TONES[diffKind] ?? "gray"}>{diffKind}</Badge>
        )}
        <Badge tone="gray" title="actual → effective">
          actual → effective
        </Badge>
        <Tabs<DiffMode>
          items={[
            { value: "unified", label: "统一" },
            { value: "side", label: "并排" },
          ]}
          value={mode}
          onChange={setMode}
        />
        <IconButton
          label="就这条发起整理"
          className="h-7 w-7"
          onClick={() => setOrganizeOpen(true)}
        >
          <Sparkles size={13} />
        </IconButton>
      </div>

      {metadata !== null && metadata.baseline_diverged && (
        <div className="flex items-start gap-2 border-b border-line bg-warning-soft px-4 py-2 text-[12px] text-warning">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span className="min-w-0 flex-1">
            记录此 overlay 变更后，已接受基线又发生了变化——当前差异是相对
            旧基线计算的。可重新读取生效内容，或发起一次 Home 整理来收敛。
          </span>
        </div>
      )}

      {metadata !== null && (
        <div className="border-b border-line px-4 py-1.5 text-[11px] text-fg-faint">
          actual {metadata.actual_chars} 字符 · effective {metadata.effective_chars} 字符
        </div>
      )}

      {page.loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-[12px] text-fg-faint">
          <Loader2 size={15} className="animate-spin-slow" />
          正在读取差异…
        </div>
      ) : page.error !== null && page.items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<AlertTriangle size={24} />}
            title="差异读取失败"
            description={errorMessage}
            action={
              <Button variant="outline" size="sm" onClick={page.reload}>
                <RotateCcw size={13} />
                重试
              </Button>
            }
          />
        </div>
      ) : lines.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<GitCompareArrows size={24} />}
            title="无差异"
            description="该条目的生效内容与已接受基线一致。"
          />
        </div>
      ) : mode === "unified" ? (
        <div className="min-h-0 flex-1 overflow-auto px-2 py-2">
          <UnifiedRows lines={lines} />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto px-2 py-2">
          <SideBySideRows rows={sideRows} />
        </div>
      )}

      {page.error !== null && page.items.length > 0 && (
        <div className="flex items-center gap-2 border-t border-line bg-danger-soft px-4 py-2 text-[12px] text-danger">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="min-w-0 flex-1">{errorMessage}</span>
          <Button variant="ghost" size="xs" onClick={page.reload}>
            <RotateCcw size={12} />
            重试
          </Button>
        </div>
      )}

      {!page.loading && page.next !== null && (
        <div className="border-t border-line px-4 py-2">
          <Button
            variant="outline"
            size="xs"
            loading={page.loadingMore}
            onClick={page.loadMore}
          >
            显示更多
          </Button>
        </div>
      )}

      {organizeOpen && (
        <ReflectionDialog
          kind="home"
          initialInstructions={reviewPrefill}
          onClose={() => setOrganizeOpen(false)}
        />
      )}
    </div>
  );
}

const UNIFIED_LINE_CLASSES: Record<DiffLine["kind"], string> = {
  meta: "text-fg-faint",
  hunk: "bg-info-soft/60 text-info",
  context: "text-fg-muted",
  add: "bg-success-soft/70 text-success",
  del: "bg-danger-soft/70 text-danger",
};

function UnifiedRows({ lines }: { lines: DiffLine[] }): ReactElement {
  return (
    <div className="font-mono text-[12px] leading-5">
      {lines.map((line, index) => (
        <div
          key={index}
          className={`whitespace-pre-wrap break-all rounded-sm px-2 ${UNIFIED_LINE_CLASSES[line.kind]}`}
        >
          {line.kind === "add" ? `+${line.text}` : line.kind === "del" ? `-${line.text}` : line.kind === "context" ? ` ${line.text}` : line.text === "" ? " " : line.text}
        </div>
      ))}
    </div>
  );
}

const SIDE_CELL_CLASSES: Record<"context" | "add" | "del", string> = {
  context: "text-fg-muted",
  add: "bg-success-soft/70 text-success",
  del: "bg-danger-soft/70 text-danger",
};

function SideBySideRows({ rows }: { rows: SideRow[] }): ReactElement {
  return (
    <div className="font-mono text-[12px] leading-5">
      <div className="grid grid-cols-2 gap-2 px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-wide text-fg-faint">
        <span className="flex items-center gap-1">
          <Rows3 size={11} />
          Actual
        </span>
        <span className="flex items-center gap-1">
          <Columns2 size={11} />
          Effective
        </span>
      </div>
      {rows.map((row, index) =>
        row.hunk !== null ? (
          <div
            key={index}
            className="rounded-sm bg-info-soft/60 px-2 text-info whitespace-pre-wrap break-all"
          >
            {row.hunk}
          </div>
        ) : (
          <div key={index} className="grid grid-cols-2 gap-2">
            <SideCellView cell={row.left} />
            <SideCellView cell={row.right} />
          </div>
        ),
      )}
    </div>
  );
}

function SideCellView({
  cell,
}: {
  cell: SideRow["left"];
}): ReactElement {
  if (cell === null) {
    return <div className="rounded-sm bg-bg-sunken/50 px-2"> </div>;
  }
  return (
    <div className={`flex rounded-sm px-2 ${SIDE_CELL_CLASSES[cell.kind]}`}>
      <span className="w-8 shrink-0 select-none pr-2 text-right text-fg-faint">
        {cell.lineNo}
      </span>
      <span className="min-w-0 whitespace-pre-wrap break-all">
        {cell.text === "" ? " " : cell.text}
      </span>
    </div>
  );
}
