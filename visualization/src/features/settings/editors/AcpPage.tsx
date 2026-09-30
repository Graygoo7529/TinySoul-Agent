/**
 * ACP Subagents settings (config-coverage §4.6): delegation targets are
 * collection objects edited atomically; live connections are read-only and
 * observed under Runtime Observation.
 */

import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";

import type { AcpDirectory, JsonValue } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { SectionCard } from "../../../components/ui/Card";
import { useAppStore } from "../../../store/appStore";
import { useConnectionStore } from "../../../store/connectionStore";
import { FieldSection } from "./controls";
import {
  CollectionObjectEditor,
  ObjBoolean,
  ObjMap,
  ObjRow,
  ObjStringList,
  ObjText,
  type ObjectEditContext,
} from "./collection";

const ROOT = "capabilities.subagent.agents";

export function AcpPage() {
  return (
    <CollectionObjectEditor
      collectionId="capabilities.subagent.agents"
      runtimeSummary={<AcpRuntimeSummary />}
      renderFields={(ctx) => <AcpTargetFields ctx={ctx} />}
      limits={
        <FieldSection
          title="Delegation Limits"
          description="Connection and delegation bounds shared by all targets."
          paths={[
            "capabilities.subagent.max_connections",
            "capabilities.subagent.connect_timeout_seconds",
            "capabilities.subagent.max_runtime_seconds",
            "capabilities.subagent.stop_timeout_seconds",
            "capabilities.subagent.max_output_chars",
            "capabilities.subagent.max_collect_chars",
            "capabilities.subagent.max_brief_chars",
          ]}
          overrides={{
            "capabilities.subagent.max_connections": { min: 1 },
            "capabilities.subagent.connect_timeout_seconds": { min: 1 },
            "capabilities.subagent.max_runtime_seconds": { min: 1 },
            "capabilities.subagent.stop_timeout_seconds": { min: 1 },
          }}
        />
      }
    />
  );
}

function AcpTargetFields({ ctx }: { ctx: ObjectEditContext }) {
  const disabled = ctx.readOnly !== null;
  const at = (name: string) => `${ROOT}.${ctx.id}.${name}`;
  const text = (name: string): string =>
    typeof ctx.object[name] === "string" ? (ctx.object[name] as string) : "";
  const bool = (name: string): boolean => ctx.object[name] === true;
  const list = (name: string): string[] =>
    Array.isArray(ctx.object[name])
      ? ctx.object[name].filter(
          (item): item is string => typeof item === "string",
        )
      : [];
  const map = (name: string): Record<string, JsonValue> =>
    ctx.object[name] !== null &&
    typeof ctx.object[name] === "object" &&
    !Array.isArray(ctx.object[name])
      ? (ctx.object[name] as Record<string, JsonValue>)
      : {};

  return (
    <>
      <ObjRow path={at("enabled")}>
        <ObjBoolean
          value={bool("enabled")}
          disabled={disabled}
          onChange={(next) => ctx.update({ enabled: next })}
        />
      </ObjRow>
      <ObjRow path={at("description")}>
        <ObjText
          value={text("description")}
          disabled={disabled}
          placeholder="What this subagent is for"
          onChange={(next) => ctx.update({ description: next })}
        />
      </ObjRow>
      <ObjRow path={at("command")}>
        <ObjText
          value={text("command")}
          mono
          disabled={disabled}
          placeholder="Executable of the ACP agent"
          onChange={(next) => ctx.update({ command: next })}
        />
      </ObjRow>
      <ObjRow path={at("args")}>
        <ObjStringList
          value={list("args")}
          disabled={disabled}
          onChange={(next) => ctx.update({ args: next })}
        />
      </ObjRow>
      <ObjRow path={at("auto_approve")} label="auto_approve">
        <div className="flex items-center gap-2">
          <ObjBoolean
            value={bool("auto_approve")}
            disabled={disabled}
            onChange={(next) => ctx.update({ auto_approve: next })}
          />
          <span className="text-[11px] text-fg-faint">
            On: the adapter approves its own requests; off: requests come back
            to this Agent.
          </span>
        </div>
      </ObjRow>
      <ObjRow path={at("env")} label="env">
        <ObjMap
          value={map("env")}
          disabled={disabled}
          keyPlaceholder="VARIABLE"
          valuePlaceholder="value"
          onChange={(next) => ctx.update({ env: next })}
        />
      </ObjRow>
      <ObjRow path={at("env_refs")} label="env_refs">
        <ObjMap
          value={map("env_refs")}
          disabled={disabled}
          credentialValues
          keyPlaceholder="VARIABLE"
          valuePlaceholder="DOTENV_NAME"
          onChange={(next) => ctx.update({ env_refs: next })}
        />
      </ObjRow>
    </>
  );
}

/** Read-only live connection summary of the running generation. */
function AcpRuntimeSummary() {
  const clients = useConnectionStore((s) => s.clients);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const [directory, setDirectory] = useState<AcpDirectory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (clients === null) return;
    clients.capabilities
      .subagent()
      .then((result) => {
        if (!cancelled) setDirectory(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Unavailable");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [clients]);

  const connectionStates = (directory?.connections ?? []).map((connection) => {
    const target =
      typeof connection.target_id === "string"
        ? connection.target_id
        : typeof connection.target === "string"
          ? connection.target
          : "?";
    const state =
      typeof connection.state === "string"
        ? connection.state
        : typeof connection.status === "string"
          ? connection.status
          : "unknown";
    return { target, state };
  });

  return (
    <SectionCard
      title="Runtime connections"
      description="Live connections of the running generation. Configuration changes activate on apply; they never start a connection by themselves."
      actions={
        <button
          type="button"
          className="flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
          onClick={() => setActiveTab("runtime")}
        >
          Runtime Observation <ArrowRight size={12} />
        </button>
      }
    >
      {clients === null ? (
        <div className="text-[12px] text-fg-faint">
          No backend connection — runtime facts are unavailable.
        </div>
      ) : error !== null ? (
        <div className="text-[12px] text-fg-faint">
          The runtime directory is unavailable: {error}
        </div>
      ) : directory === null ? (
        <div className="text-[12px] text-fg-faint">Loading…</div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <div className="text-[12px] text-fg-muted">
            {directory.targets.length} configured target(s) ·{" "}
            {connectionStates.length} live connection(s)
          </div>
          {connectionStates.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {connectionStates.map((connection, index) => (
                <span
                  key={`${connection.target}:${index}`}
                  className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11.5px]"
                >
                  <span className="font-mono text-fg">{connection.target}</span>
                  <Badge
                    tone={
                      connection.state === "ready" || connection.state === "connected"
                        ? "green"
                        : "gray"
                    }
                  >
                    {connection.state}
                  </Badge>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </SectionCard>
  );
}
