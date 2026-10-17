/** One project-scoped read/save flow shared by the shell and settings page. */
import { useAppStore } from "../../store/appStore";
import { useConnectionStore } from "../../store/connectionStore";
import {
  initialUiPrefsState,
  prefsFromApi,
  prefsPatchToApi,
  useUiPrefsStore,
  type UiPrefs,
} from "../../store/uiPrefsStore";
import { settingsText } from "./i18n";

let readRequest: AbortController | null = null;
let writeRequest: AbortController | null = null;

function current(epoch: number, request: AbortController): boolean {
  return !request.signal.aborted && useConnectionStore.getState().epoch === epoch;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function resetPresentation(): void {
  readRequest?.abort();
  writeRequest?.abort();
  readRequest = null;
  writeRequest = null;
  useUiPrefsStore.setState(initialUiPrefsState());
}

export async function refreshInterface(discardPending = false): Promise<void> {
  const { clients, epoch, phase, unreachable } = useConnectionStore.getState();
  const state = useUiPrefsStore.getState();
  if (!clients || phase !== "connected" || unreachable || state.saving) return;
  if (!discardPending && Object.keys(state.pending).length > 0) return;
  readRequest?.abort();
  const request = new AbortController();
  readRequest = request;
  useUiPrefsStore.setState({ phase: "loading", loadError: null });
  try {
    const document = await clients.presentation.configuration({ signal: request.signal });
    if (!current(epoch, request)) return;
    useUiPrefsStore.setState({
      saved: prefsFromApi(document.values),
      defaults: prefsFromApi(document.defaults),
      pending: {},
      phase: "ready",
      saveError: null,
    });
  } catch (error) {
    if (!current(epoch, request)) return;
    useUiPrefsStore.setState({ phase: "error", loadError: errorMessage(error) });
  } finally {
    if (readRequest === request) readRequest = null;
  }
}

export function updateInterface(changes: Partial<UiPrefs>): void {
  const connection = useConnectionStore.getState();
  const state = useUiPrefsStore.getState();
  if (connection.phase !== "connected" || connection.unreachable || state.phase !== "ready") return;
  useUiPrefsStore.setState({ pending: { ...state.pending, ...changes } });
  if (!state.saveError) void savePendingInterface();
}

export function setInterfacePref<K extends keyof UiPrefs>(key: K, value: UiPrefs[K]): void {
  updateInterface({ [key]: value });
}

export function resetInterfaceDefaults(): void {
  updateInterface(useUiPrefsStore.getState().defaults);
}

export async function retryInterfaceSave(): Promise<void> {
  useUiPrefsStore.setState({ saveError: null });
  await savePendingInterface();
}

async function savePendingInterface(): Promise<void> {
  const { clients, epoch, phase, unreachable } = useConnectionStore.getState();
  const initial = useUiPrefsStore.getState();
  if (!clients || phase !== "connected" || unreachable || initial.phase !== "ready" || initial.saving) return;
  if (Object.keys(initial.pending).length === 0) return;
  const request = new AbortController();
  writeRequest = request;
  useUiPrefsStore.setState({ saving: true });
  try {
    while (current(epoch, request)) {
      const sent = useUiPrefsStore.getState().pending;
      if (Object.keys(sent).length === 0) break;
      const document = await clients.presentation.saveConfiguration(prefsPatchToApi(sent), { signal: request.signal });
      if (!current(epoch, request)) return;
      const pending = { ...useUiPrefsStore.getState().pending };
      for (const key of Object.keys(sent) as (keyof UiPrefs)[]) {
        if (pending[key] === sent[key]) delete pending[key];
      }
      useUiPrefsStore.setState({ saved: prefsFromApi(document.values), pending, saveError: null });
    }
  } catch (error) {
    if (!current(epoch, request)) return;
    const message = errorMessage(error);
    useUiPrefsStore.setState({ saveError: message });
    useAppStore.getState().pushToast("error", `${settingsText("Interface settings could not be saved.")} ${message}`, {
      label: settingsText("Retry saving"),
      onClick: () => {
        if (useConnectionStore.getState().epoch === epoch) void retryInterfaceSave();
      },
    });
  } finally {
    if (writeRequest === request) {
      writeRequest = null;
      useUiPrefsStore.setState({ saving: false });
    }
  }
}
