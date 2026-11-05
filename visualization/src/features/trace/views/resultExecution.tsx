/**
 * Execution, job-control, ACP and MCP result views.
 */

import { t, useI18n } from "../../../i18n";
import type { JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { JsonTree } from "../../../components/ui/JsonTree";
import { asNumber, asObject, asString, asStringArray } from "../model/facts";
import type { ResultViewProps } from "../model/registry";
import { isSearchPage, SearchResultView } from "./SearchResultView";
import {
  FactRow,
  FactGrid,
  Excerpt,
  LinksBlock,
  EmptyResult,
  GenericView,
} from "./resultShared";

// ---------------------------------------------------------------------------
// execution / job-control / acp / mcp
// ---------------------------------------------------------------------------

/** The Job identity chip — one visual token in both the plan and result zones. */
function JobChip({ id }: { id: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-accent/40 bg-accent-soft px-1.5 py-px font-mono text-[10px] text-accent">
      Job · {id}
    </span>
  );
}

export function ExecutionView({ result, params, nav }: ResultViewProps) {
  useI18n();
  if (result === null) return <EmptyResult />;
  const jobId = asString(result.job_id);
  const paramJobId = params !== null ? asString(params.job_id) : null;
  const command = params !== null ? asString(params.command) : null;
  const sourceRef = params !== null ? asString(params.source_ref) : null;
  const args = params !== null ? asStringArray(params.args) : [];
  const cwdRef = params !== null ? asString(params.cwd_ref) : null;
  const stdinText = params !== null ? asString(params.text) : null;
  const stdinClose = params !== null && params.close === true;
  const interactive = params !== null && params.interactive === true;
  const interpreter = params !== null ? asString(params.interpreter) : null;
  const stdout = asString(result.stdout);
  const stderr = asString(result.stderr);

  // The planned invocation in terminal language: cwd comment + `$ command`,
  // or a Job chip line for stdin/collect job interactions.
  const commandLine =
    command !== null
      ? `${command}${args.length > 0 ? ` ${args.join(" ")}` : ""}`
      : sourceRef !== null
        ? `${sourceRef}${args.length > 0 ? ` ${args.join(" ")}` : ""}`
        : null;
  const isStdin = stdinText !== null;
  const isCollect =
    !isStdin && commandLine === null && paramJobId !== null && stdinText === null;
  const hasPlanZone = commandLine !== null || isStdin || isCollect;

  return (
    <div className="space-y-2">
      {hasPlanZone && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-accent">
            {t("trace.planningInput")}</div>
          <div className="term-block relative">
            {interpreter !== null && (
              <span className="absolute right-1.5 top-1 rounded border border-accent/40 bg-accent-soft px-1 font-mono text-[10px] text-accent">
                {interpreter}
              </span>
            )}
            {cwdRef !== null && <div className="opacity-50"># {cwdRef}</div>}
            {commandLine !== null && (
              <div>
                <span className="term-cmd">$ {commandLine}</span>
                {interactive && <span className="opacity-50">{t("trace.interactive")}</span>}
              </div>
            )}
            {isStdin && paramJobId !== null && (
              <div>
                <JobChip id={paramJobId} /> {t("trace.inputs")}{" "}
                <span className="text-success">"{stdinText}"</span>
                {stdinClose && <span className="opacity-50">{t("trace.closeAfterInput")}</span>}
              </div>
            )}
            {isCollect && paramJobId !== null && (
              <div>
                <JobChip id={paramJobId} />
                <br />
                {t("trace.readOutput")}</div>
            )}
          </div>
        </div>
      )}
      <div className={hasPlanZone ? "border-t border-line/60 pt-2" : ""}>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-success">
          {t("trace.executionResult")}</div>
        <FactGrid>
          {jobId !== null && (
            <FactRow
              label="job"
              value={
                <button
                  type="button"
                  className="text-accent hover:underline"
                  onClick={() => nav.openJob(jobId)}
                >
                  {jobId}
                </button>
              }
            />
          )}
          {asString(result.kind) !== null && (
            <FactRow label={t("trace.kind")} value={asString(result.kind)} />
          )}
          {asString(result.state) !== null && (
            <FactRow
              label={t("trace.state")}
              value={<JobStateBadge state={asString(result.state)!} />}
            />
          )}
          {asNumber(result.exit_code) !== null && (
            <FactRow label={t("common.exitCode")} value={asNumber(result.exit_code)} />
          )}
        </FactGrid>
        {stdout !== null && stdout !== "" && (
          <Collapsible title={t("trace.stdoutChars", { count: stdout.length })} defaultOpen={stdout.length <= 1500}>
            <div className="term-block">{stdout}</div>
          </Collapsible>
        )}
        {stderr !== null && stderr !== "" && (
          <Collapsible title={t("trace.stderrChars", { count: stderr.length })} defaultOpen>
            <div className="term-block"><span className="term-stderr">{stderr}</span></div>
          </Collapsible>
        )}
      </div>
      {(result.stdout_truncated === true || result.stderr_truncated === true) && (
        <div className="text-[11px] text-fg-faint">
          {t("trace.fullOutputHint")}</div>
      )}
      <LinksBlock payload={result} onOpen={nav.openReference} title={t("trace.resultResources")} />
    </div>
  );
}

function JobStateBadge({ state }: { state: string }) {
  const tone =
    state === "completed"
      ? "green"
      : state === "failed" || state === "stopped"
        ? "red"
        : state === "running"
          ? "blue"
          : "gray";
  return <Badge tone={tone}>{state}</Badge>;
}

export function JobControlView({ result, params, nav }: ResultViewProps) {
  const { t } = useI18n();
  if (result === null) return <EmptyResult />;
  const jobId = asString(result.job_id) ?? (params !== null ? asString(params.job_id) : null);
  const waitKind = asString(result.event_kind);
  const timeout = asNumber(result.timeout_seconds);
  return (
    <div className="space-y-2">
      <FactGrid>
        {waitKind !== null && <FactRow label={t("trace.waitingFor")} value={waitKind} />}
        {asString(result.topic) !== null && (
          <FactRow label={t("trace.topic")} value={asString(result.topic)} />
        )}
        {asString(result.source) !== null && (
          <FactRow label={t("trace.source")} value={asString(result.source)} />
        )}
        {asString(result.event_id) !== null && (
          <FactRow label={t("trace.event")} value={asString(result.event_id)} />
        )}
        {timeout !== null && <FactRow label={t("common.timeout")} value={`${timeout}s`} />}
        {asString(result.summary) !== null && asString(result.summary) !== "" && (
          <FactRow label={t("trace.summary")} value={asString(result.summary)} />
        )}
        {result.ready !== undefined && (
          <FactRow label={t("common.ready")} value={result.ready === true ? "yes" : "no"} />
        )}
        {asString(result.state) !== null && (
          <FactRow
            label={t("trace.jobState")}
            value={<JobStateBadge state={asString(result.state)!} />}
          />
        )}
      </FactGrid>
      {jobId !== null && (
        <button
          type="button"
          className="text-[12px] text-accent hover:underline"
          onClick={() => nav.openJob(jobId)}
        >
          {t("trace.openJob")}{jobId}
        </button>
      )}
      {asString(result.action) === null && jobId === null && waitKind === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

export function AcpView({ action, result, nav }: ResultViewProps) {
  useI18n();
  if (result === null) return <EmptyResult />;
  const jobId = asString(result.job_id);
  const connectionId = asString(result.connection_id);
  const agents = Array.isArray(result.agents) ? result.agents : null;
  const outputText = action === "subagent.collect" ? asString(result.text) : null;
  return (
    <div className="space-y-2">
      <FactGrid>
        {connectionId !== null && (
          <FactRow label={t("trace.connection")} value={connectionId} />
        )}
        {result.disconnected === true && (
          <FactRow label={t("trace.connection")} value="disconnected" />
        )}
        {asString(result.state) !== null && (
          <FactRow
            label={t("trace.jobState")}
            value={<JobStateBadge state={asString(result.state)!} />}
          />
        )}
      </FactGrid>
      {jobId !== null && (
        <button
          type="button"
          className="text-[12px] text-accent hover:underline"
          onClick={() => nav.openJob(jobId)}
        >
          {t("trace.openDelegatedJob")}{jobId}
        </button>
      )}
      {agents !== null && (
        <Collapsible title={t("trace.configuredAgentCount", { count: agents.length })}>
          <JsonTree value={agents} defaultExpanded={false} />
        </Collapsible>
      )}
      {outputText !== null && outputText.trim() !== "" && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium text-fg-faint">{t("trace.output")}</div>
          <Excerpt text={outputText} max={4000} />
        </div>
      )}
      <LinksBlock payload={result} onOpen={nav.openReference} title={t("trace.resultResources")} />
      {jobId === null && connectionId === null && agents === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

export function McpView({ result, params, nav }: ResultViewProps) {
  useI18n();
  if (result === null) return <EmptyResult />;
  if (isSearchPage(result)) {
    // MCP natural-language discovery is a real directory+pipeline Search.
    return (
      <SearchResultView
        result={result}
        params={params}
        onOpenReference={nav.openReference}
      />
    );
  }
  const content = result.content;
  const isError = result.is_error === true;
  const items = Array.isArray(result.items) ? result.items : null;
  const servers = Array.isArray(result.servers) ? result.servers : null;
  return (
    <div className="space-y-2">
      {isError && <Badge tone="red">{t("trace.remoteToolError")}</Badge>}
      {servers !== null && (
        <div className="flex flex-wrap gap-1">
          {servers.map((entry, index) => {
            const server = asObject(entry);
            const id = server !== null ? asString(server.server_id) : null;
            return id !== null ? <Badge key={index} tone="gray">{id}</Badge> : null;
          })}
        </div>
      )}
      {items !== null && (
        <Collapsible title={t("trace.directoryItemCount", { count: items.length })} defaultOpen={items.length <= 6}>
          <JsonTree value={items} defaultExpanded={false} />
        </Collapsible>
      )}
      {content !== undefined && content !== null && (
        <Collapsible title={t("trace.toolResultContent")} defaultOpen>
          <JsonTree value={content as JsonValue} defaultExpanded={false} />
        </Collapsible>
      )}
      {items === null && content === undefined && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------