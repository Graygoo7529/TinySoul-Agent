/**
 * Home page (plan §11/P07).
 *
 * Left directory organized by the real spaces/types (top content, general
 * skills, plain resources, domain/action guidance) or the overlay changes
 * list; center reads one resource in the selected view, or the actual →
 * effective diff of one overlay change. The top bar carries the
 * effective/actual switch, the catalog filter, content search, the changes
 * entry and "Organize Home". Content search reads effective Home only —
 * opening it from the actual view switches the page explicitly. The page
 * never writes Home: no accept/reject, no merge editor, no per-day restore.
 */

import { useCallback, useEffect, useState, type ReactElement } from "react";
import { House, ListChecks, Search, Sparkles } from "lucide-react";

import type { SearchPage } from "../../api/v2/types";
import type { SearchRequestBody } from "../../api/v2/clients";
import { EmptyState } from "../../components/ui/EmptyState";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Tabs } from "../../components/ui/Tabs";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { SearchPanel, type SearchScopeChoice } from "../resources/SearchPanel";
import { ReferencesPanel } from "../resources/ReferencesPanel";
import { ReflectionDialog } from "../resources/ReflectionDialog";
import { resolveReference, routeTarget } from "../resources/router";
import { useResourceTargets } from "../resources/targetsStore";
import { useHomePage } from "./store";
import { HomeDirectory } from "./HomeDirectory";
import { HomeChanges } from "./HomeChanges";
import { HomeContentView } from "./HomeContentView";
import { HomeDiffView } from "./HomeDiffView";

const SEARCH_SCOPES: SearchScopeChoice[] = [
  { id: "all", label: "All of Home", value: "all" },
  { id: "agent", label: "Agent space", value: "agent" },
  { id: "skills", label: "Skills", value: "skills" },
];

export function HomePage(): ReactElement {
  const epoch = useConnectionStore((s) => s.epoch);
  const view = useHomePage((s) => s.view);
  const ref = useHomePage((s) => s.ref);
  const fragment = useHomePage((s) => s.fragment);
  const panel = useHomePage((s) => s.panel);
  const diffLink = useHomePage((s) => s.diffLink);
  const currentDirectRefs = useHomePage((s) => s.currentDirectRefs);
  const rightPanel = useHomePage((s) => s.rightPanel);
  const [organizeOpen, setOrganizeOpen] = useState(false);

  // Consume the pending navigation target recorded by the ResourceRouter.
  const pendingTarget = useResourceTargets((s) => s.home);
  useEffect(() => {
    if (pendingTarget === null) return;
    useHomePage.getState().openTarget(pendingTarget);
    useResourceTargets.getState().consumeHome();
  }, [pendingTarget]);

  const runSearch = useCallback(
    (body: SearchRequestBody, signal: AbortSignal): Promise<SearchPage> => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.search.searchHome(body, { signal });
    },
    [],
  );

  // Opening a result selects the resource in place (frozen results stay
  // open); anything outside Home routes through the ResourceRouter.
  const openSearchRef = useCallback(
    async (ref: string): Promise<void> => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) return;
      const outcome = await resolveReference(clients, ref, { homeView: "effective" });
      if (outcome.status !== "resolved") {
        useAppStore
          .getState()
          .pushToast(outcome.status === "unbound" ? "info" : "error", outcome.detail);
        return;
      }
      const target = outcome.value.target;
      if (target.kind === "home") {
        useHomePage.getState().select(target.ref, target.fragment);
        return;
      }
      routeTarget(epoch, target);
    },
    [epoch],
  );

  const openSearch = () => {
    if (view === "actual") {
      // Content search exists only over effective Home; say so and switch.
      useHomePage.getState().setView("effective");
      useHomePage.getState().setRightPanel("search");
      useAppStore
        .getState()
        .pushToast(
          "info",
          "Content search reads effective Home — switched to the effective view.",
        );
      return;
    }
    useHomePage.getState().setRightPanel(rightPanel === "search" ? "none" : "search");
  };

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-line bg-bg-elev/60 px-3 py-2">
        <Tabs
          items={[
            { value: "effective", label: "Effective" },
            { value: "actual", label: "Actual" },
          ]}
          value={view}
          onChange={(value) => useHomePage.getState().setView(value)}
        />
        <span className="text-[11px] text-fg-faint">
          {view === "effective" ? "What the next run uses" : "The accepted baseline"}
        </span>
        <div className="flex-1" />
        <Button
          variant={panel === "changes" ? "secondary" : "ghost"}
          size="xs"
          onClick={() =>
            useHomePage.getState().setPanel(panel === "changes" ? "directory" : "changes")
          }
        >
          <ListChecks size={12} />
          Changes
        </Button>
        <Button
          variant={rightPanel === "search" ? "secondary" : "ghost"}
          size="xs"
          onClick={openSearch}
        >
          <Search size={12} />
          Search content
        </Button>
        <Button variant="outline" size="xs" onClick={() => setOrganizeOpen(true)}>
          <Sparkles size={12} />
          Organize Home
        </Button>
      </header>

      <div className="flex min-h-0 flex-1">
        {panel === "changes" ? <HomeChanges epoch={epoch} /> : <HomeDirectory epoch={epoch} />}

        <div className="relative min-w-0 flex-1">
          {ref === null && diffLink === null && (
            <div className="flex h-full items-center justify-center p-6">
              <EmptyState
                icon={<House size={26} />}
                title="Home"
                description={
                  view === "effective"
                    ? "The identity, preferences, skills and guidance the next run uses. Pick an entry from the directory."
                    : "The accepted baseline. Switch back to effective to see the content runs actually use."
                }
                action={
                  <Badge tone="purple">{view} view</Badge>
                }
              />
            </div>
          )}
          {ref !== null && (
            <div className={diffLink === null ? "h-full" : "hidden"}>
              <HomeContentView epoch={epoch} ref={ref} view={view} fragment={fragment} />
            </div>
          )}
          {diffLink !== null && (
            <div className="h-full">
              <HomeDiffView epoch={epoch} ref={diffLink} />
            </div>
          )}
        </div>
      </div>

      {rightPanel === "search" && (
        <SearchPanel
          epoch={epoch}
          actionId="home.search"
          identityKey={`home|effective`}
          title="Search Home"
          placeholder="Search effective Home…"
          scopes={SEARCH_SCOPES}
          run={runSearch}
          onOpenRef={(ref) => void openSearchRef(ref)}
          onClose={() => useHomePage.getState().setRightPanel("none")}
        />
      )}
      {rightPanel === "references" && ref !== null && (
        <ReferencesPanel
          actionId="home.search"
          anchor={ref}
          directRefs={currentDirectRefs}
          origin={{ homeView: view }}
          run={runSearch}
          onOpenRef={(ref) => void openSearchRef(ref)}
          onClose={() => useHomePage.getState().setRightPanel("none")}
        />
      )}
      {organizeOpen && (
        <ReflectionDialog kind="home" onClose={() => setOrganizeOpen(false)} />
      )}
    </div>
  );
}
