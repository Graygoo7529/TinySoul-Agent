/**
 * Memory page (plan §12/P08).
 *
 * Left navigation switches between the active Memory.md (day selector — a
 * day binding of that one document, never time travel for the whole
 * knowledge base) and the persistent knowledge list (kind tabs + server-side
 * name filter). The center reads the active Memory.md or one persistent
 * document; the right overlay hosts the shared search panel (persistent
 * Memory scopes, optional document-related queries) and the references
 * panel of the currently read document. The page never writes persistent
 * Memory: organization goes through a Memory reflection, edits go through
 * the conversation.
 */

import { useCallback, useEffect, useState, type ReactElement } from "react";
import { Brain, Search, Sparkles } from "lucide-react";

import type { DayEntry, SearchPage } from "../../api/v2/types";
import type { SearchRequestBody } from "../../api/v2/clients";
import { EmptyState } from "../../components/ui/EmptyState";
import { Button } from "../../components/ui/Button";
import { Tabs } from "../../components/ui/Tabs";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { SearchPanel, type SearchScopeChoice } from "../resources/SearchPanel";
import { ReferencesPanel } from "../resources/ReferencesPanel";
import { ReflectionDialog } from "../resources/ReflectionDialog";
import { resolveReference, routeTarget } from "../resources/router";
import { useResourceTargets } from "../resources/targetsStore";
import { useMemoryPage, type MemorySection } from "./store";
import { MemoryNav } from "./MemoryNav";
import { ActiveMemoryView } from "./ActiveMemoryView";
import { MemoryDocumentView } from "./MemoryDocumentView";

const SEARCH_SCOPES: SearchScopeChoice[] = [
  { id: "all", label: "All knowledge", value: "all" },
  { id: "daily", label: "Daily", value: "daily" },
  { id: "entity", label: "Entities", value: "entity" },
  { id: "concept", label: "Concepts", value: "concept" },
  { id: "fact", label: "Facts", value: "fact" },
  { id: "note", label: "Notes", value: "note" },
];

export function MemoryPage(): ReactElement {
  const epoch = useConnectionStore((s) => s.epoch);
  const section = useMemoryPage((s) => s.section);
  const ref = useMemoryPage((s) => s.ref);
  const fragment = useMemoryPage((s) => s.fragment);
  const currentMeta = useMemoryPage((s) => s.currentMeta);
  const currentDirectRefs = useMemoryPage((s) => s.currentDirectRefs);
  const rightPanel = useMemoryPage((s) => s.rightPanel);
  const [organizeOpen, setOrganizeOpen] = useState(false);
  const [days, setDays] = useState<DayEntry[] | null>(null);

  // Consume the pending navigation target recorded by the ResourceRouter.
  const pendingTarget = useResourceTargets((s) => s.memory);
  useEffect(() => {
    if (pendingTarget === null) return;
    useMemoryPage.getState().openTarget(pendingTarget);
    useResourceTargets.getState().consumeMemory();
  }, [pendingTarget]);

  // Day directory for the active-memory selector (first page; older days
  // stay reachable through references, which carry their own day binding).
  useEffect(() => {
    const clients = useConnectionStore.getState().clients;
    if (clients === null) {
      setDays(null);
      return;
    }
    const controller = new AbortController();
    clients.session
      .days({ limit: 30 }, { signal: controller.signal })
      .then((page) => {
        if (!controller.signal.aborted) setDays(page.items);
      })
      .catch(() => {
        if (!controller.signal.aborted) setDays(null);
      });
    return () => controller.abort();
  }, [epoch]);

  const runSearch = useCallback(
    (body: SearchRequestBody, signal: AbortSignal): Promise<SearchPage> => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.search.searchMemory(body, { signal });
    },
    [],
  );

  // Opening a result selects the document in place (frozen results stay
  // open); anything outside Memory routes through the ResourceRouter.
  const openSearchRef = useCallback(
    async (ref: string): Promise<void> => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) return;
      const outcome = await resolveReference(clients, ref, {});
      if (outcome.status !== "resolved") {
        useAppStore
          .getState()
          .pushToast(outcome.status === "unbound" ? "info" : "error", outcome.detail);
        return;
      }
      const target = outcome.value.target;
      if (target.kind === "memory") {
        useMemoryPage.getState().openTarget({
          ref: target.ref,
          day: target.day,
          fragment: target.fragment,
        });
        return;
      }
      routeTarget(epoch, target);
    },
    [epoch],
  );

  const documentAnchor =
    section === "persistent" && ref !== null
      ? { ref, label: currentMeta?.display ?? ref }
      : null;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-bg-elev/60 px-3 py-2">
        <Tabs<MemorySection>
          items={[
            { value: "active", label: "Active memory" },
            { value: "persistent", label: "Knowledge" },
          ]}
          value={section}
          onChange={(value) => useMemoryPage.getState().setSection(value)}
        />
        <span className="text-[11px] text-fg-faint">
          {section === "active"
            ? "What the agent is recording this day"
            : "Organized persistent knowledge"}
        </span>
        <div className="flex-1" />
        <Button
          variant={rightPanel === "search" ? "secondary" : "ghost"}
          size="xs"
          onClick={() =>
            useMemoryPage
              .getState()
              .setRightPanel(rightPanel === "search" ? "none" : "search")
          }
        >
          <Search size={12} />
          Search knowledge
        </Button>
        <Button variant="outline" size="xs" onClick={() => setOrganizeOpen(true)}>
          <Sparkles size={12} />
          Organize Memory
        </Button>
      </header>

      <div className="flex min-h-0 flex-1">
        <MemoryNav
          epoch={epoch}
          days={days}
          onOrganize={() => setOrganizeOpen(true)}
        />

        <div className="relative min-w-0 flex-1">
          {section === "active" ? (
            <ActiveMemoryView epoch={epoch} />
          ) : ref !== null ? (
            <MemoryDocumentView epoch={epoch} ref={ref} fragment={fragment} />
          ) : (
            <div className="flex h-full items-center justify-center p-6">
              <EmptyState
                icon={<Brain size={26} />}
                title="Knowledge"
                description="Persistent daily, entity, concept, fact and note documents. Pick one from the list, or search the knowledge base."
              />
            </div>
          )}
        </div>
      </div>

      {rightPanel === "search" && (
        <SearchPanel
          epoch={epoch}
          actionId="memory.search"
          identityKey="memory"
          title="Search Memory"
          placeholder="Search persistent knowledge…"
          scopes={SEARCH_SCOPES}
          run={runSearch}
          documentAnchor={documentAnchor}
          onOpenRef={(ref) => void openSearchRef(ref)}
          onClose={() => useMemoryPage.getState().setRightPanel("none")}
        />
      )}
      {rightPanel === "references" && section === "persistent" && ref !== null && (
        <ReferencesPanel
          actionId="memory.search"
          anchor={ref}
          directRefs={currentDirectRefs}
          origin={{ ref }}
          run={runSearch}
          onOpenRef={(ref) => void openSearchRef(ref)}
          onClose={() => useMemoryPage.getState().setRightPanel("none")}
        />
      )}
      {organizeOpen && (
        <ReflectionDialog kind="memory" onClose={() => setOrganizeOpen(false)} />
      )}
    </div>
  );
}
