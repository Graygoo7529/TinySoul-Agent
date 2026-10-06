/**
 * Workspace write operations (plan §10/P06).
 *
 * Every write route acts on the active Workspace only. Operations run
 * strictly serialized — the owner commits short operations in order and the
 * page never issues two writes at once. Each success carries the committed
 * record plus the full manifest, which the page installs directly; failures
 * surface as toasts and nothing here fakes a result. There is no
 * digest/revision CAS and no rollback of committed files.
 */

import { useCallback, useRef, useState } from "react";

import type { V2Clients } from "../../api/v2/clients";
import type {
  WorkspaceManifest,
  WorkspaceResourceRecord,
  WorkspaceTag,
} from "../../api/v2/types";
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import { isValidWorkspacePath, normalizeWorkspacePath } from "./tree";

export interface WorkspaceMutations {
  /** A write is in flight; triggers stay disabled until it settles. */
  busy: boolean;
  saveText: (ref: string, text: string) => Promise<WorkspaceResourceRecord | null>;
  createFile: (path: string) => Promise<string | null>;
  createDirectory: (path: string) => Promise<string | null>;
  move: (ref: string, targetPath: string) => Promise<string | null>;
  setTags: (ref: string, tags: WorkspaceTag[]) => Promise<WorkspaceResourceRecord | null>;
  append: (ref: string, text: string) => Promise<WorkspaceResourceRecord | null>;
  replaceText: (
    ref: string,
    oldText: string,
    newText: string,
  ) => Promise<WorkspaceResourceRecord | null>;
  trash: (ref: string) => Promise<boolean>;
  restore: (trashRef: string) => Promise<boolean>;
  upload: (files: File[], targetDir: string) => Promise<void>;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function toast(kind: "success" | "error" | "info", text: string): void {
  useAppStore.getState().pushToast(kind, text);
}

/**
 * @param onManifest installs the manifest of a committed write; the page
 * applies it only while viewing the active day.
 */
export function useWorkspaceMutations(
  onManifest: (manifest: WorkspaceManifest) => void,
): WorkspaceMutations {
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const manifestRef = useRef(onManifest);
  manifestRef.current = onManifest;

  const execute = useCallback(
    async <T,>(
      thunk: (clients: V2Clients) => Promise<{ manifest: WorkspaceManifest; value: T }>,
      failure: string,
    ): Promise<T | null> => {
      if (busyRef.current) {
        toast("info", "Another workspace operation is still running.");
        return null;
      }
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        toast("error", "Not connected to a backend.");
        return null;
      }
      busyRef.current = true;
      setBusy(true);
      try {
        const result = await thunk(clients);
        manifestRef.current(result.manifest);
        return result.value;
      } catch (error) {
        toast("error", `${failure}: ${errorMessage(error)}`);
        return null;
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [],
  );

  const checkedPath = useCallback((input: string): string | null => {
    const path = normalizeWorkspacePath(input);
    if (!isValidWorkspacePath(path)) {
      toast("error", `"${input}" is not a valid workspace path.`);
      return null;
    }
    return path;
  }, []);

  const saveText = useCallback(
    (ref: string, text: string) =>
      execute(
        async (clients) => {
          const result = await clients.workspace.writeText({
            ref,
            text,
            overwrite: true,
          });
          return { manifest: result.manifest, value: result.record };
        },
        "Save failed",
      ),
    [execute],
  );

  const createFile = useCallback(
    async (input: string): Promise<string | null> => {
      const path = checkedPath(input);
      if (path === null) return null;
      const record = await execute(
        async (clients) => {
          const result = await clients.workspace.writeText({
            ref: `workspace:${path}`,
            text: "",
            overwrite: false,
          });
          return { manifest: result.manifest, value: result.record };
        },
        "Create file failed",
      );
      return record === null ? null : path;
    },
    [execute, checkedPath],
  );

  const createDirectory = useCallback(
    async (input: string): Promise<string | null> => {
      const path = checkedPath(input);
      if (path === null) return null;
      const record = await execute(
        async (clients) => {
          const result = await clients.workspace.createDirectory({
            ref: `workspace:${path}`,
          });
          return { manifest: result.manifest, value: result.record };
        },
        "Create folder failed",
      );
      return record === null ? null : path;
    },
    [execute, checkedPath],
  );

  const move = useCallback(
    async (ref: string, targetInput: string): Promise<string | null> => {
      const target = checkedPath(targetInput);
      if (target === null) return null;
      const record = await execute(
        async (clients) => {
          const result = await clients.workspace.move({
            source_ref: ref,
            target_ref: `workspace:${target}`,
          });
          return { manifest: result.manifest, value: result.record };
        },
        "Move failed",
      );
      return record === null ? null : target;
    },
    [execute, checkedPath],
  );

  const setTags = useCallback(
    (ref: string, tags: WorkspaceTag[]) =>
      execute(
        async (clients) => {
          const result = await clients.workspace.setTags({ ref, tags });
          return { manifest: result.manifest, value: result.record };
        },
        "Update tags failed",
      ),
    [execute],
  );

  const append = useCallback(
    (ref: string, text: string) =>
      execute(
        async (clients) => {
          const result = await clients.workspace.append({ ref, text });
          return { manifest: result.manifest, value: result.record };
        },
        "Append failed",
      ),
    [execute],
  );

  const replaceText = useCallback(
    (ref: string, oldText: string, newText: string) =>
      execute(
        async (clients) => {
          const result = await clients.workspace.edit({
            ref,
            edits: [{ old_text: oldText, new_text: newText }],
          });
          return { manifest: result.manifest, value: result.record };
        },
        "Replace failed",
      ),
    [execute],
  );

  const trash = useCallback(
    async (ref: string): Promise<boolean> => {
      const result = await execute(
        async (clients) => {
          const outcome = await clients.workspace.trash({ ref });
          return { manifest: outcome.manifest, value: true };
        },
        "Move to trash failed",
      );
      return result === true;
    },
    [execute],
  );

  const restore = useCallback(
    async (trashRef: string): Promise<boolean> => {
      const result = await execute(
        async (clients) => {
          const outcome = await clients.workspace.restore({ trash_ref: trashRef });
          return { manifest: outcome.manifest, value: true };
        },
        "Restore failed",
      );
      return result === true;
    },
    [execute],
  );

  const upload = useCallback(
    async (files: File[], targetDir: string): Promise<void> => {
      if (busyRef.current) {
        toast("info", "Another workspace operation is still running.");
        return;
      }
      const clients = useConnectionStore.getState().clients;
      if (clients === null) {
        toast("error", "Not connected to a backend.");
        return;
      }
      busyRef.current = true;
      setBusy(true);
      let uploaded = 0;
      const failed: string[] = [];
      try {
        for (const file of files) {
          const relative =
            targetDir === "" ? file.name : `${targetDir}/${file.name}`;
          if (!isValidWorkspacePath(relative)) {
            failed.push(`${file.name} (invalid path)`);
            continue;
          }
          try {
            const result = await clients.workspace.writeBlob(
              { ref: `workspace:${relative}`, overwrite: false },
              file,
            );
            manifestRef.current(result.manifest);
            uploaded += 1;
          } catch (error) {
            failed.push(`${file.name} (${errorMessage(error)})`);
          }
        }
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
      if (failed.length === 0) {
        toast("success", `Uploaded ${uploaded} file${uploaded === 1 ? "" : "s"}.`);
      } else {
        toast(
          "error",
          `${failed.length} of ${files.length} uploads failed: ${failed.join(", ")}`,
        );
      }
    },
    [],
  );

  return {
    busy,
    saveText,
    createFile,
    createDirectory,
    move,
    setTags,
    append,
    replaceText,
    trash,
    restore,
    upload,
  };
}
