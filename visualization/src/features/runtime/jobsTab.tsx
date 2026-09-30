/**
 * Jobs tab (plan §14 Jobs, API-14).
 *
 * The tab binds the Turn that is active when it opens and polls only that
 * Turn's job list — no page-wide refresh. Selecting a job reads its owner
 * detail and its output through a JobOutputReader: pages append by
 * continuation (a polling position, never an end marker), a running job's
 * empty page keeps the token for the next tick, and a terminal job still
 * gets its remaining output drained before polling stops. Stopping a job
 * waits for the formal snapshot the POST returns; it never cancels the Turn.
 * When the Turn is reclaimed the last read stays on screen — frozen, with
 * its real artifact links — instead of an operable fake history.
 */

import {
  useEffect,
  useRef,
  useState,
  type ReactElement,
} from "react";
import { CircleStop, ExternalLink, ListTodo } from "lucide-react";

import type {
  JobDetail,
  JobSummary,
  JsonValue,
  ResourceLocator,
} from "../../api/v2/types";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Collapsible } from "../../components/ui/Collapsible";
import { CopyButton } from "../../components/ui/CopyButton";
import { EmptyState } from "../../components/ui/EmptyState";
import { JsonTree } from "../../components/ui/JsonTree";
import { useAppStore } from "../../store/appStore";
import {
  selectActiveDay,
  selectActiveTurnId,
  useConnectionStore,
} from "../../store/connectionStore";
import { openReference } from "../resources/router";
import { openTurnProcess } from "../trace/entries";
import {
  errorMessage,
  isTerminalJobState,
  JOB_STATE_TONES,
  runtimeClients,
  shortId,
  shortTurnId,
} from "./runtimeModel";
import {
  channelTexts,
  INITIAL_JOB_OUTPUT,
  JobOutputReader,
  type JobOutputState,
} from "./jobOutput";
import { useRuntimeUi } from "./store";
import { LoadingRow, ReadError } from "./shared";

export function JobsTab({
  epoch,
  listIntervalMs = 2500,
  outputIntervalMs = 1500,
}: {
  epoch: number;
  listIntervalMs?: number;
  outputIntervalMs?: number;
}): ReactElement {
  // The turn this tab binds, captured once: jobs belong to one Turn and are
  // reclaimed with it, so a later turn never inherits this view.
  const [bound] = useState(() => ({
    turnId: selectActiveTurnId(useConnectionStore.getState()),
    day: selectActiveDay(useConnectionStore.getState()),
  }));
  const turnMoved = useConnectionStore(
    (s) => selectActiveTurnId(s) !== bound.turnId,
  );
  const selectedJobId = useRuntimeUi((s) => s.selectedJobId);
  const selectJob = useRuntimeUi((s) => s.selectJob);

  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [listReclaimed, setListReclaimed] = useState(false);
  const hadJobs = useRef(false);
  const reclaimed = turnMoved || listReclaimed;

  // Clear the cross-jump selection when this binding unmounts — a stale job
  // id must not leak into the next turn's view.
  useEffect(() => () => selectJob(null), [selectJob]);

  useEffect(() => {
    if (bound.turnId === null || reclaimed) return;
    const turnId = bound.turnId;
    let stopped = false;
    let timer: number | null = null;
    const tick = async (): Promise<void> => {
      try {
        const list = await runtimeClients(epoch).jobs.list(turnId);
        if (stopped) return;
        setListError(null);
        setJobs(list.jobs);
        if (list.jobs.length > 0) {
          hadJobs.current = true;
        } else if (hadJobs.current) {
          // The list went from jobs to none: the turn was reclaimed.
          setListReclaimed(true);
          return;
        }
        timer = window.setTimeout(() => void tick(), listIntervalMs);
      } catch (error) {
        if (stopped) return;
        setListError(errorMessage(error));
        timer = window.setTimeout(() => void tick(), listIntervalMs);
      }
    };
    void tick();
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [epoch, bound.turnId, reclaimed, listIntervalMs]);

  if (bound.turnId === null) {
    return (
      <EmptyState
        icon={<ListTodo size={26} />}
        title="No active turn"
        description="Jobs belong to the turn that started them — none is running right now."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-[12px] text-fg-faint">
        Jobs of turn
        <span className="font-medium text-fg-muted" title={bound.turnId}>
          {shortTurnId(bound.turnId)}
        </span>
        <CopyButton text={() => bound.turnId ?? ""} label="Copy turn id" />
      </div>
      {reclaimed && (
        <ReclaimedNotice epoch={epoch} turnId={bound.turnId} day={bound.day} />
      )}
      {listError !== null && !reclaimed && (
        <ReadError message={listError} />
      )}
      {jobs === null && !reclaimed ? (
        <LoadingRow text="Reading the job list…" />
      ) : jobs !== null && jobs.length === 0 && !reclaimed ? (
        <div className="rounded-lg border border-line bg-bg-elev px-4 py-3 text-[12px] text-fg-faint">
          No background jobs in this turn yet.
        </div>
      ) : (
        jobs !== null && (
          <div className="space-y-1.5">
            {jobs.map((job) => (
              <JobRow
                key={job.job_id}
                job={job}
                selected={job.job_id === selectedJobId}
                inert={reclaimed}
                onSelect={() => selectJob(job.job_id)}
              />
            ))}
          </div>
        )
      )}
      {selectedJobId !== null && (
        <JobDetailView
          key={`${epoch}:${selectedJobId}`}
          epoch={epoch}
          turnId={bound.turnId}
          day={bound.day}
          jobId={selectedJobId}
          reclaimed={reclaimed}
          outputIntervalMs={outputIntervalMs}
        />
      )}
    </div>
  );
}

function JobRow({
  job,
  selected,
  inert,
  onSelect,
}: {
  job: JobSummary;
  selected: boolean;
  /** Reclaimed view: rows stay readable, only the actions freeze. */
  inert: boolean;
  onSelect: () => void;
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors ${
        selected
          ? "border-accent/50 bg-accent-soft"
          : "border-line bg-bg-elev hover:border-line-strong hover:bg-hover"
      }`}
    >
      <Badge tone={JOB_STATE_TONES[job.state] ?? "gray"}>{job.state}</Badge>
      <span className="shrink-0 text-[12px] text-fg-faint">{job.kind}</span>
      <span className="min-w-0 flex-1 truncate text-[13px]">
        {job.summary !== "" ? job.summary : job.job_id}
      </span>
      {job.pending_inputs.length > 0 && (
        <Badge tone="yellow">pending request</Badge>
      )}
      {!inert && <span className="sr-only">select</span>}
    </button>
  );
}

/** The frozen banner of a reclaimed turn: artifacts and process stay. */
function ReclaimedNotice({
  epoch,
  turnId,
  day,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
}): ReactElement {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-bg-sunken px-3 py-2 text-[12px] text-fg-muted">
      <span className="min-w-0 flex-1">
        This turn has finished — its jobs were reclaimed. The last read stays
        below, frozen; artifacts remain available through their links.
      </span>
      <Button
        variant="outline"
        size="xs"
        onClick={() => openTurnProcess(epoch, turnId, day)}
      >
        Turn process
      </Button>
    </div>
  );
}

function JobDetailView({
  epoch,
  turnId,
  day,
  jobId,
  reclaimed,
  outputIntervalMs,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  jobId: string;
  reclaimed: boolean;
  outputIntervalMs: number;
}): ReactElement {
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [output, setOutput] = useState<JobOutputState>({
    ...INITIAL_JOB_OUTPUT,
  });
  const [stopping, setStopping] = useState(false);
  const [nonce, setNonce] = useState(0);
  const readerRef = useRef<JobOutputReader | null>(null);
  if (readerRef.current === null) {
    const clients = runtimeClients(epoch);
    readerRef.current = new JobOutputReader(
      (continuation) =>
        clients.jobs.output(
          turnId,
          jobId,
          continuation !== undefined ? { continuation } : {},
        ),
      setOutput,
    );
  }

  useEffect(() => {
    if (reclaimed) return; // frozen: keep the last read, stop reading
    const reader = readerRef.current;
    if (reader === null) return;
    const clients = runtimeClients(epoch);
    let stopped = false;
    let timer: number | null = null;
    const tick = async (): Promise<void> => {
      try {
        const current = await clients.jobs.get(turnId, jobId);
        if (stopped) return;
        setDetail(current);
        setReadError(null);
        const outcome = await reader.poll(isTerminalJobState(current.state));
        if (stopped) return;
        if (outcome !== "stalled" && !reader.snapshot.exhausted) {
          timer = window.setTimeout(() => void tick(), outputIntervalMs);
        }
      } catch {
        // reader.poll stores its own bounded error before rethrowing; the
        // detail read has no fallback — either way one row reports it.
        if (!stopped) {
          setReadError(reader.snapshot.error ?? "the job read failed");
        }
      }
    };
    void tick();
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [epoch, turnId, jobId, reclaimed, nonce, outputIntervalMs]);

  const stopJob = async (): Promise<void> => {
    setStopping(true);
    try {
      // The POST answers with the formal snapshot — that is the new state.
      const updated = await runtimeClients(epoch).jobs.stop(turnId, jobId);
      setDetail(updated);
    } catch (error) {
      useAppStore
        .getState()
        .pushToast("error", `Failed to stop the job: ${errorMessage(error)}`);
    } finally {
      setStopping(false);
    }
  };

  const terminal = detail !== null && isTerminalJobState(detail.state);
  return (
    <div className="space-y-3 rounded-lg border border-line bg-bg-elev px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        {detail !== null && (
          <Badge tone={JOB_STATE_TONES[detail.state] ?? "gray"}>
            {detail.state}
          </Badge>
        )}
        <span className="text-[12px] text-fg-faint" title={jobId}>
          {shortId(jobId)}
        </span>
        <CopyButton text={() => jobId} label="Copy job id" />
        <span className="flex-1" />
        {!reclaimed && detail !== null && !terminal && (
          <Button
            variant="danger"
            size="xs"
            loading={stopping}
            onClick={() => void stopJob()}
          >
            <CircleStop size={12} />
            Stop job
          </Button>
        )}
      </div>
      {detail === null && readError === null && (
        <LoadingRow text="Reading the job…" />
      )}
      {readError !== null && (
        <ReadError message={readError} onRetry={() => setNonce((n) => n + 1)} />
      )}
      {detail !== null && (
        <JobDetailBody
          epoch={epoch}
          turnId={turnId}
          day={day}
          detail={detail}
        />
      )}
      <JobOutputView epoch={epoch} turnId={turnId} day={day} output={output} />
    </div>
  );
}

function JobDetailBody({
  epoch,
  turnId,
  day,
  detail,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  detail: JobDetail;
}): ReactElement {
  return (
    <div className="space-y-2 text-[12px]">
      {detail.summary !== "" && (
        <div className="text-fg-muted">{detail.summary}</div>
      )}
      {detail.reason !== "" && (
        <div className="text-warning">{detail.reason}</div>
      )}
      {detail.pending_inputs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-warning">
          <span className="min-w-0 flex-1">
            The agent has a pending request for this job — answer it in the
            conversation.
          </span>
          <Button
            variant="outline"
            size="xs"
            onClick={() => useAppStore.getState().setActiveTab("chat")}
          >
            Open in conversation
          </Button>
        </div>
      )}
      {detail.result_links.length > 0 && (
        <div className="space-y-1">
          <div className="text-fg-faint">Artifacts</div>
          {detail.result_links.map((link) => (
            <button
              key={link}
              type="button"
              onClick={() =>
                void openReference(epoch, link, {
                  turnId,
                  day: day ?? undefined,
                })
              }
              className="flex w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-left text-accent hover:bg-hover"
            >
              <ExternalLink size={11} className="shrink-0" />
              <span className="min-w-0 truncate">{link}</span>
            </button>
          ))}
        </div>
      )}
      {detail.details !== null && detail.details !== undefined && (
        <Collapsible title="Details">
          <JsonTree value={detail.details} defaultExpanded={false} />
        </Collapsible>
      )}
    </div>
  );
}

/** One job's captured output, per channel — plus the read position facts. */
function JobOutputView({
  epoch,
  turnId,
  day,
  output,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  output: JobOutputState;
}): ReactElement {
  const channels = channelTexts(output.items);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[12px] text-fg-faint">
        Output
        {output.reading && (
          <span className="text-fg-faint">(reading…)</span>
        )}
      </div>
      {channels.length === 0 && !output.reading && (
        <div className="text-[12px] text-fg-faint">
          {output.exhausted
            ? "This job produced no captured output."
            : "No output captured yet."}
        </div>
      )}
      {channels.map(([channel, text]) => (
        <div key={channel} className="overflow-hidden rounded-lg border border-line">
          <div className="border-b border-line bg-bg-sunken px-2.5 py-1 text-[11px] font-medium text-fg-faint">
            {channel}
          </div>
          <pre className="max-h-72 overflow-auto bg-code-bg px-3 py-2 text-[12px] leading-5 whitespace-pre-wrap break-words">
            {text}
          </pre>
        </div>
      ))}
      {output.truncated && !output.stalled && (
        <div className="text-[11px] text-fg-faint">
          Bounded read — more output is available and reading continues; this
          never means output was lost.
        </div>
      )}
      {output.stalled && (
        <div className="space-y-1.5 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
          <p>
            The bounded read reached its limit — the remaining output is
            available through the job's actual artifacts:
          </p>
          <LocatorLinks
            epoch={epoch}
            turnId={turnId}
            day={day}
            locators={output.locators}
          />
        </div>
      )}
    </div>
  );
}

/** A locator carries a link when it points at a real artifact. */
function locatorLink(value: ResourceLocator | JsonValue): string | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const link = (value as { link?: unknown }).link;
  return typeof link === "string" && link !== "" ? link : null;
}

function LocatorLinks({
  epoch,
  turnId,
  day,
  locators,
}: {
  epoch: number;
  turnId: string;
  day: string | null;
  locators: (ResourceLocator | JsonValue)[];
}): ReactElement {
  return (
    <div className="space-y-1">
      {locators.map((locator, index) => {
        const link = locatorLink(locator);
        if (link === null) {
          return <JsonTree key={index} value={locator} defaultExpanded={false} />;
        }
        return (
          <button
            key={link}
            type="button"
            onClick={() =>
              void openReference(epoch, link, {
                turnId,
                day: day ?? undefined,
              })
            }
            className="flex w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-left text-accent hover:bg-hover"
          >
            <ExternalLink size={11} className="shrink-0" />
            <span className="min-w-0 truncate">{link}</span>
          </button>
        );
      })}
    </div>
  );
}
