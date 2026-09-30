/**
 * Runtime observation page (plan §14/P09): what the Agent is doing, waiting
 * for, and which background work and external capabilities exist. A compact
 * overview strip on top — readiness, the current Turn with its real wait
 * reason, the queue; long identities stay short — and five tabs below, each
 * reading its own detail only while open (switching tabs unmounts the
 * previous one, which stops its reads).
 */

import type { ReactElement } from "react";

import { Tabs } from "../../components/ui/Tabs";
import { useConnectionStore } from "../../store/connectionStore";
import { AcpTab } from "./acpTab";
import { EnvironmentTab } from "./environmentTab";
import { ExecutionTab } from "./executionTab";
import { JobsTab } from "./jobsTab";
import { McpTab } from "./mcpTab";
import { OverviewStrip, useActiveTurnSnapshot } from "./overview";
import { useRuntimeUi, type RuntimeTab } from "./store";

const TAB_ITEMS: { value: RuntimeTab; label: string }[] = [
  { value: "execution", label: "Execution" },
  { value: "jobs", label: "Jobs" },
  { value: "acp", label: "ACP" },
  { value: "mcp", label: "MCP" },
  { value: "environment", label: "Environment" },
];

export function RuntimePage(): ReactElement {
  const epoch = useConnectionStore((s) => s.epoch);
  const tab = useRuntimeUi((s) => s.tab);
  const setTab = useRuntimeUi((s) => s.setTab);
  const read = useActiveTurnSnapshot(epoch);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-3 border-b border-line px-5 pb-3 pt-4">
        <OverviewStrip read={read} />
        <Tabs items={TAB_ITEMS} value={tab} onChange={setTab} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-5 py-4">
          {tab === "execution" ? (
            <ExecutionTab epoch={epoch} read={read} />
          ) : tab === "jobs" ? (
            // Keyed by epoch: a reconnect rebinds the tab's turn cleanly.
            <JobsTab key={epoch} epoch={epoch} />
          ) : tab === "acp" ? (
            <AcpTab epoch={epoch} />
          ) : tab === "mcp" ? (
            <McpTab epoch={epoch} />
          ) : (
            <EnvironmentTab epoch={epoch} />
          )}
        </div>
      </div>
    </div>
  );
}
