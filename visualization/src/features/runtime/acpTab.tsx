/**
 * ACP tab (plan §14 ACP, API-15).
 *
 * Two separate fact families stay side by side: configured targets (from the
 * configuration) and live connections (generation runtime facts). A
 * connection is not one delegation — an idle one survives across turns, and
 * opening this page never establishes one. "Delegate in conversation" only
 * fills an editable Composer draft; "Edit configuration" opens the settings
 * page that owns these fields.
 */

import { useState, type ReactElement } from "react";
import { RefreshCw, Send, Unplug } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { CopyButton } from "../../components/ui/CopyButton";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAppStore } from "../../store/appStore";
import { selectActiveTurnId, useConnectionStore } from "../../store/connectionStore";
import { useSettingsUiStore } from "../settings/uiStore";
import { useComposerDraft } from "../chat/composerDraft";
import { pushJobDetail } from "../trace/entries";
import { openReference } from "../resources/router";
import { useAsyncRead } from "../trace/panelShared";
import {
  narrowConnections,
  narrowTargets,
  type AcpConnection,
  type AcpTarget,
} from "./acpModel";
import { runtimeClients, shortId, shortTurnId } from "./runtimeModel";
import { useRuntimeUi } from "./store";
import { LoadingRow, ReadError } from "./shared";

const CONNECTION_TONES: Record<string, "green" | "blue" | "red" | "gray"> = {
  ready: "green",
  busy: "blue",
  unavailable: "red",
};

export function AcpTab({ epoch }: { epoch: number }): ReactElement {
  const [nonce, setNonce] = useState(0);
  const read = useAsyncRead(
    (signal) => runtimeClients(epoch).capabilities.subagent({ signal }),
    [epoch, nonce],
  );

  if (read.kind === "loading") {
    return <LoadingRow text="Reading the subagent directory…" />;
  }
  if (read.kind === "error") {
    return (
      <ReadError message={read.message} onRetry={() => setNonce((n) => n + 1)} />
    );
  }
  const directory = read.value;
  const targets = narrowTargets(directory.targets);
  const connections = narrowConnections(directory.connections);
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-[12px] text-fg-faint">
        <span>
          Reading this page never connects to a subagent — connections are
          established by delegations.
        </span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="xs"
          onClick={() => setNonce((n) => n + 1)}
        >
          <RefreshCw size={12} />
          Re-read
        </Button>
      </div>
      <TargetsSection targets={targets} />
      <ConnectionsSection
        epoch={epoch}
        day={typeof directory.day === "string" ? directory.day : null}
        connections={connections}
      />
    </div>
  );
}

function TargetsSection({
  targets,
}: {
  targets: AcpTarget[];
}): ReactElement {
  if (targets.length === 0) {
    return (
      <EmptyState
        icon={<Unplug size={26} />}
        title="No subagent targets configured"
        description="Targets are configuration facts — add one in settings before a delegation can use it."
        action={
          <Button variant="outline" size="sm" onClick={openAcpSettings}>
            Open ACP settings
          </Button>
        }
      />
    );
  }
  return (
    <section className="space-y-1.5">
      <h3 className="text-[12px] font-medium text-fg-faint">
        Configured targets
      </h3>
      {targets.map((target) => (
        <div
          key={target.agentId}
          className="flex items-center gap-2 rounded-lg border border-line bg-bg-elev px-3 py-2"
        >
          <Badge tone={target.enabled ? "green" : "gray"}>
            {target.enabled ? "enabled" : "disabled"}
          </Badge>
          <span className="shrink-0 text-[13px] font-medium">
            {target.agentId}
          </span>
          <span className="min-w-0 flex-1 truncate text-[12px] text-fg-muted">
            {target.description}
          </span>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => delegateDraft(target.agentId)}
          >
            <Send size={12} />
            Delegate in conversation
          </Button>
        </div>
      ))}
    </section>
  );
}

function ConnectionsSection({
  epoch,
  day,
  connections,
}: {
  epoch: number;
  day: string | null;
  connections: AcpConnection[];
}): ReactElement {
  const openJob = useRuntimeUi((s) => s.openJob);
  if (connections.length === 0) {
    return (
      <section className="space-y-1.5">
        <h3 className="text-[12px] font-medium text-fg-faint">Connections</h3>
        <div className="rounded-lg border border-line bg-bg-elev px-4 py-3 text-[12px] text-fg-faint">
          No live connections. A connection appears when a delegation starts
          and an idle one can be reused across turns.
        </div>
      </section>
    );
  }
  return (
    <section className="space-y-1.5">
      <h3 className="text-[12px] font-medium text-fg-faint">
        Connections — this generation's runtime facts
      </h3>
      {connections.map((connection) => (
        <div
          key={connection.connectionId}
          className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-bg-elev px-3 py-2"
        >
          <Badge tone={CONNECTION_TONES[connection.state] ?? "gray"}>
            {connection.state}
          </Badge>
          <span className="text-[13px] font-medium">{connection.agentId}</span>
          <span
            className="text-[11px] text-fg-faint"
            title={connection.connectionId}
          >
            {shortId(connection.connectionId)}
          </span>
          <CopyButton
            text={() => connection.connectionId}
            label="Copy connection id"
          />
          {connection.turnId !== null ? (
            <span
              className="text-[11px] text-fg-muted"
              title={connection.turnId}
            >
              turn {shortTurnId(connection.turnId)}
            </span>
          ) : (
            <span className="text-[11px] text-fg-faint">
              idle — reusable across turns
            </span>
          )}
          {connection.cwdLink !== "" && (
            <button
              type="button"
              onClick={() => void openReference(epoch, connection.cwdLink)}
              className="max-w-48 truncate text-[11px] text-accent hover:underline"
              title={connection.cwdLink}
            >
              {connection.cwdLink}
            </button>
          )}
          <span className="flex-1" />
          {connection.activeJobId !== null && (
            <Button
              variant="ghost"
              size="xs"
              onClick={() => {
                const activeTurn = selectActiveTurnId(
                  useConnectionStore.getState(),
                );
                const jobId = connection.activeJobId;
                if (jobId === null) return;
                if (connection.turnId !== null && connection.turnId === activeTurn) {
                  openJob(jobId);
                } else if (connection.turnId !== null) {
                  pushJobDetail(epoch, connection.turnId, day, jobId);
                }
              }}
            >
              Job {shortId(connection.activeJobId)}
            </Button>
          )}
        </div>
      ))}
    </section>
  );
}

function openAcpSettings(): void {
  useSettingsUiStore.getState().navigateTo("acp");
  useAppStore.getState().setActiveTab("settings");
}

/** Fill an editable draft — it never sends itself. */
function delegateDraft(agentId: string): void {
  useComposerDraft
    .getState()
    .setDraft(`Please delegate a task to the ${agentId} subagent: `);
  useAppStore.getState().setActiveTab("chat");
}
