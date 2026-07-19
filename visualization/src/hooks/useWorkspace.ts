/**
 * Workspace operations hook.
 */

import { useCallback } from "react";

import { useAppStore } from "../store/appStore";
import type {
  TrashItem,
  WorkspaceResourceRecord,
  WorkspaceTextRead,
} from "../types";

export function useWorkspace() {
  const store = useAppStore();
  const client = store.client;

  const refresh = useCallback(async () => {
    if (!client) return;
    store.setWorkspaceLoading(true);
    try {
      const manifest = await client.workspaceManifest();
      store.setWorkspace(manifest);
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
        return read;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        store.setWorkspace(null, message);
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
        store.openWorkspaceResource({
          link: response.record.link,
          text,
          truncated: false,
          size: new Blob([text]).size,
          digest: response.record.digest || expectedDigest,
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        store.setWorkspace(null, message);
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
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        store.setWorkspace(null, message);
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
        if (store.openResource?.link === link) {
          store.closeResource();
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        store.setWorkspace(null, message);
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
      store.setWorkspace(null, message);
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
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        store.setWorkspace(null, message);
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
