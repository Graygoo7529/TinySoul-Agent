import { t, useI18n, message, tStatus } from "../../../i18n";
import { requestIdForTurn } from "../../../store/turnStore";
/**
 * Turn-owned Job detail (plan §9.1 job-control family).
 *
 * The owner projection (state/kind/pending inputs/result links/details)
 * plus bounded output reads. Job output pages always carry a
 * `next_continuation` — it is a polling position, never an end marker — so
 * further output is read only when the user asks ("显示更多输出"), and a
 * running Job can be refreshed explicitly. Stopping a Job is the Agent's
 * business, not this read-only panel's.
 */

import { useState, type ReactElement } from "react";
import { Loader2, RotateCw } from "lucide-react";

import type { JobDetail, JobOutputItem } from "../../../api/v2/types";
import { Badge, type BadgeTone } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { JsonTree } from "../../../components/ui/JsonTree";
import { asNumber, asString, asStringArray } from "../model/facts";
import { ReferenceButton } from "../views/resultShared";
import { makeTraceNavigation } from "../entries";
import {
  AsyncStatus,
  traceClients,
  useAsyncRead,
} from "./panelShared";

const STATE_TONES: Record<string, BadgeTone> = {
  running: "blue",
  completed: "green",
  failed: "red",
  stopped: "gray",
  pending: "yellow",
};

interface JobRead {
  detail: JobDetail;
  items: JobOutputItem[];
  nextContinuation: string;
  truncated: boolean;
}

export function JobPanel({
  epoch,
  turnId,
  day,
  jobId,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  jobId: string;
}): ReactElement {
  useI18n();
  const nav = makeTraceNavigation(epoch, turnId, day);
  const [extra, setExtra] = useState<JobOutputItem[]>([]);
  const [continuation, setContinuation] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const read = useAsyncRead(
    async (signal) => {
      const clients = traceClients(epoch);
      const [detail, output] = await Promise.all([
        clients.jobs.get(requestIdForTurn(turnId), jobId, { signal }),
        clients.jobs.output(requestIdForTurn(turnId), jobId, {}, { signal }),
      ]);
      return {
        detail,
        items: output.items,
        nextContinuation: output.next_continuation,
        truncated: output.truncated,
      } satisfies JobRead;
    },
    [epoch, turnId, jobId, refreshTick],
  );

  const status = AsyncStatus({ state: read, loading: message("trace.readingJob") });
  if (status !== null) return status;
  if (read.kind !== "ready") return <></>;
  const { detail } = read.value;
  const baseContinuation = read.value.nextContinuation;
  const effectiveContinuation = continuation ?? baseContinuation;
  const allItems = [...read.value.items, ...extra];
  const running = detail.state === "running" || detail.state === "pending";

  const showMore = async () => {
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await traceClients(epoch).jobs.output(requestIdForTurn(turnId), jobId, {
        continuation: effectiveContinuation,
      });
      setExtra((current) => [...current, ...page.items]);
      setContinuation(page.next_continuation);
      setTruncated(page.truncated);
    } catch (error) {
      setMoreError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingMore(false);
    }
  };

  const refresh = () => {
    setExtra([]);
    setContinuation(null);
    setTruncated(false);
    setMoreError(null);
    setRefreshTick((tick) => tick + 1);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[13px] font-medium">{detail.job_id}</span>
        <Badge tone={STATE_TONES[detail.state] ?? "gray"}>{tStatus(detail.state)}</Badge>
        {detail.kind !== "" && <Badge tone="gray">{detail.kind}</Badge>}
        {running && (
          <button
            type="button"
            onClick={refresh}
            className="ml-auto inline-flex items-center gap-1 text-[12px] text-accent hover:underline"
          >
            <RotateCw size={11} />
            {t("common.refresh")}</button>
        )}
      </div>

      {detail.summary !== "" && (
        <div className="text-[12px] text-fg-muted">{detail.summary}</div>
      )}
      {detail.reason !== "" && (
        <div className="text-[12px] text-fg-faint">{detail.reason}</div>
      )}

      {detail.pending_inputs.length > 0 && (
        <Collapsible title={t("trace.pendingInputCount", { count: detail.pending_inputs.length })}>
          <JsonTree value={detail.pending_inputs} defaultExpanded={false} />
        </Collapsible>
      )}

      <JobDetails details={detail.details ?? null} />

      {detail.result_refs.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.resultResources")}</div>
          {detail.result_refs.map((link) => (
            <ReferenceButton
              key={link}
              reference={link}
              onOpen={nav.openReference}
            />
          ))}
        </div>
      )}

      <JobChannels items={allItems} truncated={truncated || read.value.truncated} />

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void showMore()}
          disabled={loadingMore}
          className="inline-flex items-center gap-1 text-[12px] text-accent hover:underline disabled:opacity-50"
        >
          {loadingMore && <Loader2 size={11} className="animate-spin-slow" />}
          {t("trace.showMoreOutput")}</button>
        {moreError !== null && (
          <span className="text-[12px] text-danger">
            {t("common.readFailedDetail", { detail: moreError })}
          </span>
        )}
      </div>
    </div>
  );
}

function JobDetails({ details }: { details: Record<string, unknown> | null }) {
  const { t } = useI18n();
  if (details === null) return null;
  const exitCode = asNumber(details.exit_code);
  const stdoutBytes = asNumber(details.stdout_bytes);
  const stderrBytes = asNumber(details.stderr_bytes);
  const workspaceLinks = asStringArray(details.workspace_refs);
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
      {exitCode !== null && (
        <>
          <dt className="text-fg-faint">{t("common.exitCode")}</dt>
          <dd className="text-fg-muted">{exitCode}</dd>
        </>
      )}
      {stdoutBytes !== null && (
        <>
          <dt className="text-fg-faint">{t("trace.stdout")}</dt>
          <dd className="text-fg-muted">{stdoutBytes} {t("common.bytes")}</dd>
        </>
      )}
      {stderrBytes !== null && (
        <>
          <dt className="text-fg-faint">{t("trace.stderr")}</dt>
          <dd className="text-fg-muted">{stderrBytes} {t("common.bytes")}</dd>
        </>
      )}
      {workspaceLinks.length > 0 && (
        <>
          <dt className="text-fg-faint">{t("trace.artifacts")}</dt>
          <dd className="text-fg-muted">{workspaceLinks.length} {t("trace.workspaceResources")}</dd>
        </>
      )}
    </dl>
  );
}

/** Channel-separated output; pages append in read order per channel. */
function JobChannels({
  items,
  truncated,
}: {
  items: JobOutputItem[];
  truncated: boolean;
}): ReactElement {
  useI18n();
  const channels = new Map<string, string>();
  for (const item of items) {
    const name = asString(item.channel) ?? "output";
    channels.set(name, (channels.get(name) ?? "") + item.text);
  }
  if (channels.size === 0) {
    return (
      <div className="rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
        {t("trace.noOutput")}</div>
    );
  }
  return (
    <div className="space-y-2">
      {[...channels.entries()].map(([name, text]) => (
        <Collapsible
          key={name}
          title={name}
          meta={<span className="text-[11px] text-fg-faint">{text.length} {t("home.chars")}</span>}
          defaultOpen={name === "stdout"}
          tone="sunken"
        >
          <pre className="max-h-72 overflow-auto text-[11px] leading-5 break-words whitespace-pre-wrap text-fg-muted">
            {text}
          </pre>
        </Collapsible>
      ))}
      {truncated && (
        <div className="text-[11px] text-fg-faint">
          {t("trace.outputReadsBoundedShowMoreContinuesLast")}</div>
      )}
    </div>
  );
}
