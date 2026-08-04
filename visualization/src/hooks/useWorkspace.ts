/**
 * Workspace operations hook.
 */

import { useCallback } from "react";

import { useAppStore, type AppState } from "../store/appStore";
import { TinySoulApiError, TinySoulClient } from "../api/tinysoul";
import type {
  TrashItem,
  WorkspaceResourceRecord,
  WorkspaceTextRead,
} from "../types";

function isConflictError(err: unknown): boolean {
  if (err instanceof TinySoulApiError) {
    return err.status === 409 || err.code.toLowerCase().includes("conflict");
  }
  return false;
}

export function useWorkspace() {
  const store = useAppStore();
  const client = store.client;

  const refresh = useCallback(async () => {
    if (!client) return;
    store.setWorkspaceLoading(true);
    try {
      const manifest = await client.workspaceManifest();
      store.setWorkspace(manifest);
      store.setWorkspaceConflict(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      store.setWorkspace(null, message);
    }
  }, [client, store]);

  const readText = useCallback(
    async (link: string): Promise<WorkspaceTextRead | undefined> => {
      if (!client) return;
      try {
        const read = await client.readWorkspaceText(link);
        store.openWorkspaceResource(read);
        store.setWorkspaceConflict(false);
        return read;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        store.pushToast("error", message);
      }
    },
    [client, store],
  );

  const saveText = useCallback(
    async (
      link: string,
      text: string,
      overwrite: boolean,
      expectedDigest: string,
    ) => {
      if (!client || !store.workspace) return;
      try {
        const response = await client.writeWorkspaceResource({
          link,
          text,
          overwrite,
          expected_digest: expectedDigest,
          expected_revision: store.workspace.revision,
        });
        store.setWorkspace(response.manifest);
        store.setWorkspaceConflict(false);
        store.openWorkspaceResource({
          link: response.record.link,
          text,
          truncated: false,
          size: new Blob([text]).size,
          digest: response.record.digest || expectedDigest,
        });
      } catch (err) {
        if (isConflictError(err)) {
          store.setWorkspaceConflict(true);
          // Refresh manifest and current baseline so the user can decide.
          void refreshOpenResource(client, store);
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        store.pushToast("error", message);
      }
    },
    [client, store],
  );

  const createResource = useCallback(
    async (
      link: string,
      text: string,
      retention: WorkspaceResourceRecord["retention"] = "day",
    ) => {
      if (!client || !store.workspace) return;
      try {
        const response = await client.writeWorkspaceResource({
          link,
          text,
          overwrite: false,
          expected_digest: "",
          expected_revision: store.workspace.revision,
          retention,
        });
        store.setWorkspace(response.manifest);
        store.setWorkspaceConflict(false);
      } catch (err) {
        if (isConflictError(err)) {
          store.setWorkspaceConflict(true);
          void refreshManifestOnly(client, store);
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        store.pushToast("error", message);
      }
    },
    [client, store],
  );

  const deleteResource = useCallback(
    async (link: string, digest: string) => {
      if (!client || !store.workspace) return;
      try {
        const response = await client.trashResource({
          link,
          expected_digest: digest,
          expected_revision: store.workspace.revision,
        });
        store.setWorkspace(response.manifest);
        store.setWorkspaceConflict(false);
        if (store.openResource?.link === link) {
          store.closeResource();
        }
      } catch (err) {
        if (isConflictError(err)) {
          store.setWorkspaceConflict(true);
          void refreshManifestOnly(client, store);
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        store.pushToast("error", message);
      }
    },
    [client, store],
  );

  const listTrash = useCallback(async (): Promise<TrashItem[]> => {
    if (!client) return [];
    try {
      const { items } = await client.listTrash();
      return items;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      store.pushToast("error", message);
      return [];
    }
  }, [client, store]);

  const restoreResource = useCallback(
    async (trashRef: string) => {
      if (!client || !store.workspace) return;
      try {
        const response = await client.restoreResource({
          trash_ref: trashRef,
          expected_revision: store.workspace.revision,
        });
        store.setWorkspace(response.manifest);
        store.setWorkspaceConflict(false);
      } catch (err) {
        if (isConflictError(err)) {
          store.setWorkspaceConflict(true);
          void refreshManifestOnly(client, store);
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        store.pushToast("error", message);
      }
    },
    [client, store],
  );

  return {
    refresh,
    readText,
    saveText,
    createResource,
    deleteResource,
    listTrash,
    restoreResource,
  };
}

async function refreshManifestOnly(client: TinySoulClient, store: AppState) {
  try {
    const manifest = await client.workspaceManifest();
    store.setWorkspace(manifest);
  } catch (error) {
    console.error("Workspace manifest refresh failed:", error);
  }
}

async function refreshOpenResource(client: TinySoulClient, store: AppState) {
  const draft = store.openResource?.draft;
  try {
    const [manifest, read] = await Promise.all([
      client.workspaceManifest(),
      store.openResource
        ? client.readWorkspaceText(store.openResource.link)
        : Promise.resolve(undefined),
    ]);
    store.setWorkspace(manifest);
    if (store.openResource && read) {
      // Update baseline digest but keep the user's draft for conflict resolution.
      store.openWorkspaceResource({ ...read });
      if (draft !== undefined) {
        store.updateResourceDraft(draft);
      }
    }
  } catch (error) {
    console.error("Workspace conflict refresh failed:", error);
  }
}
