/**
 * Workspace page (plan §10/P06).
 *
 * One page binds a day and a selected resource: the active day is writable,
 * archived days are read-only (archive reads never fall back to today). The
 * manifest is the committed index — it is read on day/epoch changes and on
 * window refocus, and every mutation response installs its returned manifest
 * directly, so the tree and the backend never diverge silently. The shared
 * SearchPanel rides on top reading the active Workspace; opening a result
 * selects the file (fragment included) without closing the frozen results.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
} from "react";
import { FolderOpen, Loader2, RotateCcw } from "lucide-react";

import type { DayEntry } from "../../api/v2/session";
import type { WorkspaceManifest } from "../../api/v2/types";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { useAppStore } from "../../store/appStore";
import {
  selectActiveDay,
  useConnectionStore,
} from "../../store/connectionStore";
import {
  resolveReference,
  routeTarget,
} from "../resources/router";
import {
  SearchPanel,
  type SearchScopeChoice,
} from "../resources/SearchPanel";
import type { SearchRequestBody } from "../../api/v2/clients";
import type { SearchPage } from "../../api/v2/types";
import { FilePanel } from "./FilePanel";
import { Sidebar } from "./Sidebar";
import { useWorkspaceMutations } from "./mutations";
import { useWorkspacePage } from "./store";
import { topLevelDirectories } from "./tree";

interface ManifestView {
  day: string;
  records: WorkspaceManifest["resources"];
}

export function WorkspacePage(): ReactElement {
  const epoch = useConnectionStore((s) => s.epoch);
  const activeDay = useConnectionStore(selectActiveDay);
  const viewDay = useWorkspacePage((s) => s.day);
  const ref = useWorkspacePage((s) => s.ref);
  const fragment = useWorkspacePage((s) => s.fragment);
  const searchOpen = useWorkspacePage((s) => s.searchOpen);
  const setSearchOpen = useWorkspacePage((s) => s.setSearchOpen);
  const select = useWorkspacePage((s) => s.select);

  const isActive = viewDay === null || viewDay === activeDay;
  const apiDay = isActive ? null : viewDay;

  const [manifest, setManifest] = useState<ManifestView | null>(null);
  const [manifestStatus, setManifestStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [days, setDays] = useState<DayEntry[] | null>(null);
  const manifestRef = useRef(manifest);
  manifestRef.current = manifest;

  const loadManifest = useCallback(
    async (fresh: boolean, signal?: AbortSignal): Promise<void> => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        if (fresh) setManifestStatus("error");
        return;
      }
      if (fresh) setManifestStatus("loading");
      try {
        const result = await clients.workspace.manifest(
          apiDay !== null ? { day: apiDay } : undefined,
          { signal },
        );
        if (signal?.aborted) return;
        setManifest({ day: result.day, records: result.resources });
        setManifestStatus("ready");
      } catch (error) {
        if (signal?.aborted) return;
        if (manifestRef.current !== null && !fresh) {
          useAppStore
            .getState()
            .pushToast(
              "error",
              `Manifest refresh failed: ${
                error instanceof Error ? error.message : String(error)
              }`,
            );
        } else {
          setManifestStatus("error");
        }
      }
    },
    [apiDay],
  );

  // Fresh read on connection, day binding or day rollover.
  useEffect(() => {
    const controller = new AbortController();
    setManifest(null);
    void loadManifest(true, controller.signal);
    return () => controller.abort();
  }, [epoch, apiDay, activeDay, loadManifest]);

  // External changes surface on refocus; mutation responses keep the index
  // current in between.
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void loadManifest(false);
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [loadManifest]);

  // Day directory for the selector (first page; older days stay reachable
  // through references, which carry their own day binding).
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

  const isActiveRef = useRef(isActive);
  isActiveRef.current = isActive;
  const applyMutationManifest = useCallback((result: WorkspaceManifest) => {
    if (!isActiveRef.current) return;
    setManifest({ day: result.day, records: result.resources });
    setManifestStatus("ready");
  }, []);
  const mutations = useWorkspaceMutations(applyMutationManifest);

  const record = useMemo(
    () => manifest?.records.find((item) => item.ref === ref) ?? null,
    [manifest, ref],
  );

  const scopes = useMemo<SearchScopeChoice[]>(
    () => [
      {
        id: "all",
        label: "Everything",
        value: { kind: "workspace" },
      },
      ...topLevelDirectories(manifest?.records ?? []).map((dir) => ({
        id: `dir:${dir}`,
        label: `Folder: ${dir}`,
        value: { kind: "directory", ref: `workspace:${dir}` },
      })),
    ],
    [manifest],
  );

  const runSearch = useCallback(
    (body: SearchRequestBody, signal: AbortSignal): Promise<SearchPage> => {
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        return Promise.reject(new Error("Not connected to a backend."));
      }
      return clients.search.searchWorkspace(body, { signal });
    },
    [],
  );

  // Opening a result selects the file in place (the frozen results stay
  // open); anything outside this Workspace routes through the ResourceRouter.
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
      if (
        target.kind === "workspace" &&
        (target.day === null || target.day === activeDay)
      ) {
        select(target.ref, target.fragment);
        return;
      }
      routeTarget(epoch, target);
    },
    [epoch, activeDay, select],
  );

  return (
    <div className="relative flex h-full min-h-0">
      <Sidebar
        epoch={epoch}
        days={days}
        viewDay={viewDay}
        activeDay={activeDay}
        manifest={manifest}
        manifestLoading={manifestStatus === "loading" && manifest === null}
        mutations={mutations}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {manifestStatus === "error" && manifest === null ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyState
              title="The manifest could not be read"
              description="The Workspace index is unavailable right now."
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void loadManifest(true)}
                >
                  <RotateCcw size={13} />
                  Retry
                </Button>
              }
            />
          </div>
        ) : record !== null ? (
          <FilePanel
            viewDay={viewDay}
            activeDay={activeDay}
            record={record}
            fragment={fragment}
            mutations={mutations}
          />
        ) : ref !== null && manifestStatus === "ready" ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyState
              title="Not in the manifest"
              description={
                <>
                  <span className="font-mono text-[11px]">{ref}</span> is not
                  part of the {manifest?.day ?? ""} Workspace index.
                </>
              }
              action={
                <Button variant="outline" size="sm" onClick={() => select(null)}>
                  Back to the tree
                </Button>
              }
            />
          </div>
        ) : manifestStatus === "loading" && manifest === null ? (
          <div className="flex flex-1 items-center justify-center text-fg-faint">
            <Loader2 size={18} className="animate-spin-slow" />
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyState
              icon={<FolderOpen size={26} />}
              title="Workspace"
              description={
                isActive
                  ? "Select a file from the tree, create one, or drop files to upload."
                  : `Archived view of ${manifest?.day ?? viewDay ?? ""} — read-only.`
              }
            />
          </div>
        )}
      </div>

      {searchOpen && isActive && (
        <SearchPanel
          epoch={epoch}
          actionId="workspace.search"
          identityKey={`workspace|${manifest?.day ?? activeDay ?? ""}`}
          title="Search workspace"
          placeholder="Search the workspace…"
          scopes={scopes}
          run={runSearch}
          onOpenRef={(ref) => void openSearchRef(ref)}
          onClose={() => setSearchOpen(false)}
        />
      )}
    </div>
  );
}
