import { useCallback, useEffect, useReducer, useRef } from "react";

import { TinySoulApiError, type TinySoulClient } from "../api/tinysoul";
import type {
  SessionActions,
  SessionCursor,
  SessionHistory,
  SessionHistoryItem,
  SessionTrace,
} from "../types";

const PAGE_CHARS = 8000;
const PAGE_ENTRIES = 20;
export const MAX_TRAIL_PAGES = 32;

export interface PageTrail<T> {
  pages: T[];
  current: number;
  pendingRequestId: number | null;
  loading: boolean;
  error: string;
}

export interface HistoryLevelState {
  ref?: string;
  label: string;
  trail: PageTrail<SessionHistory>;
}

export interface TurnDetailState {
  ref: string;
  actions: PageTrail<SessionActions>;
  trace: PageTrail<SessionTrace>;
}

export interface SessionExplorerState {
  historyPath: HistoryLevelState[];
  selected: SessionHistoryItem | null;
  detail: TurnDetailState | null;
}

export type SessionExplorerAction =
  | { type: "reset" }
  | { type: "root_request_started"; requestId: number }
  | {
      type: "history_level_opened";
      ref: string;
      label: string;
      requestId: number;
    }
  | { type: "history_request_started"; levelIndex: number; requestId: number }
  | {
      type: "history_request_succeeded";
      levelIndex: number;
      requestId: number;
      page: SessionHistory;
      append: boolean;
    }
  | {
      type: "history_request_failed";
      levelIndex: number;
      requestId: number;
      error: string;
    }
  | { type: "history_previous" }
  | { type: "history_next_cached" }
  | { type: "history_back" }
  | {
      type: "turn_selected";
      item: SessionHistoryItem;
      actionsRequestId: number;
      traceRequestId: number;
    }
  | {
      type: "actions_request_started";
      ref: string;
      requestId: number;
    }
  | {
      type: "actions_request_succeeded";
      ref: string;
      requestId: number;
      page: SessionActions;
    }
  | {
      type: "actions_request_failed";
      ref: string;
      requestId: number;
      error: string;
    }
  | { type: "actions_previous" }
  | { type: "actions_next_cached" }
  | {
      type: "trace_request_started";
      ref: string;
      requestId: number;
    }
  | {
      type: "trace_request_succeeded";
      ref: string;
      requestId: number;
      page: SessionTrace;
    }
  | {
      type: "trace_request_failed";
      ref: string;
      requestId: number;
      error: string;
    }
  | { type: "trace_previous" }
  | { type: "trace_next_cached" };

export function createSessionExplorerState(): SessionExplorerState {
  return {
    historyPath: [rootHistoryLevel()],
    selected: null,
    detail: null,
  };
}

export function currentTrailPage<T>(trail: PageTrail<T>): T | null {
  return trail.pages[trail.current] ?? null;
}

export function sessionExplorerReducer(
  state: SessionExplorerState,
  action: SessionExplorerAction,
): SessionExplorerState {
  switch (action.type) {
    case "reset":
      return createSessionExplorerState();
    case "root_request_started":
      return {
        historyPath: [
          {
            ...rootHistoryLevel(),
            trail: pendingTrail(action.requestId),
          },
        ],
        selected: null,
        detail: null,
      };
    case "history_level_opened":
      return {
        historyPath: [
          ...state.historyPath,
          {
            ref: action.ref,
            label: action.label,
            trail: pendingTrail(action.requestId),
          },
        ],
        selected: null,
        detail: null,
      };
    case "history_request_started":
      return updateHistoryLevel(state, action.levelIndex, (level) => ({
        ...level,
        trail: startRequest(level.trail, action.requestId),
      }));
    case "history_request_succeeded":
      return updateHistoryLevel(
        state,
        action.levelIndex,
        (level) => {
          if (level.trail.pendingRequestId !== action.requestId) return level;
          return {
            ...level,
            trail: finishRequest(level.trail, action.page, action.append),
          };
        },
        true,
      );
    case "history_request_failed":
      return updateHistoryLevel(state, action.levelIndex, (level) => {
        if (level.trail.pendingRequestId !== action.requestId) return level;
        return {
          ...level,
          trail: failRequest(level.trail, action.error),
        };
      });
    case "history_previous":
      return moveCurrentHistory(state, -1);
    case "history_next_cached":
      return moveCurrentHistory(state, 1);
    case "history_back":
      if (state.historyPath.length === 1) return state;
      return {
        historyPath: state.historyPath.slice(0, -1),
        selected: null,
        detail: null,
      };
    case "turn_selected":
      return {
        ...state,
        selected: action.item,
        detail: {
          ref: action.item.ref,
          actions: pendingTrail(action.actionsRequestId),
          trace: pendingTrail(action.traceRequestId),
        },
      };
    case "actions_request_started":
      return updateDetail(state, action.ref, (detail) => ({
        ...detail,
        actions: startRequest(detail.actions, action.requestId),
      }));
    case "actions_request_succeeded":
      return updateDetail(state, action.ref, (detail) => {
        if (detail.actions.pendingRequestId !== action.requestId) return detail;
        return {
          ...detail,
          actions: finishRequest(detail.actions, action.page, true),
        };
      });
    case "actions_request_failed":
      return updateDetail(state, action.ref, (detail) => {
        if (detail.actions.pendingRequestId !== action.requestId) return detail;
        return {
          ...detail,
          actions: failRequest(detail.actions, action.error),
        };
      });
    case "actions_previous":
      return moveDetailTrail(state, "actions", -1);
    case "actions_next_cached":
      return moveDetailTrail(state, "actions", 1);
    case "trace_request_started":
      return updateDetail(state, action.ref, (detail) => ({
        ...detail,
        trace: startRequest(detail.trace, action.requestId),
      }));
    case "trace_request_succeeded":
      return updateDetail(state, action.ref, (detail) => {
        if (detail.trace.pendingRequestId !== action.requestId) return detail;
        return {
          ...detail,
          trace: finishRequest(detail.trace, action.page, true),
        };
      });
    case "trace_request_failed":
      return updateDetail(state, action.ref, (detail) => {
        if (detail.trace.pendingRequestId !== action.requestId) return detail;
        return {
          ...detail,
          trace: failRequest(detail.trace, action.error),
        };
      });
    case "trace_previous":
      return moveDetailTrail(state, "trace", -1);
    case "trace_next_cached":
      return moveDetailTrail(state, "trace", 1);
  }
}

export function useSessionExplorer(client: TinySoulClient | null | undefined) {
  const [state, dispatch] = useReducer(
    sessionExplorerReducer,
    undefined,
    createSessionExplorerState,
  );
  const requestSequence = useRef(0);
  const historyControllers = useRef(new Set<AbortController>());
  const actionsController = useRef<AbortController | null>(null);
  const traceController = useRef<AbortController | null>(null);

  const nextRequestId = useCallback(() => {
    requestSequence.current += 1;
    return requestSequence.current;
  }, []);

  const abortDetails = useCallback(() => {
    actionsController.current?.abort();
    traceController.current?.abort();
    actionsController.current = null;
    traceController.current = null;
  }, []);

  const abortAll = useCallback(() => {
    for (const controller of historyControllers.current) controller.abort();
    historyControllers.current.clear();
    abortDetails();
  }, [abortDetails]);

  const loadRoot = useCallback(() => {
    abortAll();
    if (!client) {
      dispatch({ type: "reset" });
      return;
    }
    const requestId = nextRequestId();
    const controller = trackController(historyControllers.current);
    dispatch({ type: "root_request_started", requestId });
    void client
      .sessionHistory({
        maxChars: PAGE_CHARS,
        maxEntries: PAGE_ENTRIES,
        signal: controller.signal,
      })
      .then((page) => {
        dispatch({
          type: "history_request_succeeded",
          levelIndex: 0,
          requestId,
          page,
          append: false,
        });
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          dispatch({
            type: "history_request_failed",
            levelIndex: 0,
            requestId,
            error: errorMessage(error),
          });
        }
      })
      .finally(() => historyControllers.current.delete(controller));
  }, [abortAll, client, nextRequestId]);

  useEffect(() => {
    loadRoot();
    return abortAll;
  }, [abortAll, loadRoot]);

  const requestHistoryPage = useCallback(
    (
      levelIndex: number,
      ref: string | undefined,
      cursor: SessionCursor | undefined,
      append: boolean,
      requestId: number,
    ) => {
      if (!client) return;
      const controller = trackController(historyControllers.current);
      void client
        .sessionHistory({
          ref,
          cursor,
          maxChars: PAGE_CHARS,
          maxEntries: PAGE_ENTRIES,
          signal: controller.signal,
        })
        .then((page) => {
          dispatch({
            type: "history_request_succeeded",
            levelIndex,
            requestId,
            page,
            append,
          });
        })
        .catch((error: unknown) => {
          if (isAbortError(error)) return;
          if (
            levelIndex === 0 &&
            ref === undefined &&
            cursor !== undefined &&
            error instanceof TinySoulApiError &&
            error.code === "session.revision_changed"
          ) {
            loadRoot();
            return;
          }
          dispatch({
            type: "history_request_failed",
            levelIndex,
            requestId,
            error: errorMessage(error),
          });
        })
        .finally(() => historyControllers.current.delete(controller));
    },
    [client, loadRoot],
  );

  const openSummary = useCallback(
    (item: SessionHistoryItem) => {
      if (!client || item.kind !== "summary") return;
      abortDetails();
      const requestId = nextRequestId();
      const levelIndex = state.historyPath.length;
      dispatch({
        type: "history_level_opened",
        ref: item.ref,
        label: shortRef(item.ref),
        requestId,
      });
      requestHistoryPage(levelIndex, item.ref, undefined, false, requestId);
    },
    [
      abortDetails,
      client,
      nextRequestId,
      requestHistoryPage,
      state.historyPath.length,
    ],
  );

  const historyPrevious = useCallback(() => {
    abortDetails();
    dispatch({ type: "history_previous" });
  }, [abortDetails]);

  const historyNext = useCallback(() => {
    const levelIndex = state.historyPath.length - 1;
    const level = state.historyPath[levelIndex];
    if (!level || level.trail.loading) return;
    if (level.trail.current < level.trail.pages.length - 1) {
      abortDetails();
      dispatch({ type: "history_next_cached" });
      return;
    }
    const page = currentTrailPage(level.trail);
    if (!page?.next_cursor) return;
    abortDetails();
    const requestId = nextRequestId();
    dispatch({ type: "history_request_started", levelIndex, requestId });
    requestHistoryPage(
      levelIndex,
      level.ref,
      page.next_cursor,
      true,
      requestId,
    );
  }, [
    abortDetails,
    nextRequestId,
    requestHistoryPage,
    state.historyPath,
  ]);

  const historyBack = useCallback(() => {
    abortDetails();
    dispatch({ type: "history_back" });
  }, [abortDetails]);

  const selectTurn = useCallback(
    (item: SessionHistoryItem) => {
      if (!client || item.kind !== "turn") return;
      abortDetails();
      const actionsRequestId = nextRequestId();
      const traceRequestId = nextRequestId();
      dispatch({
        type: "turn_selected",
        item,
        actionsRequestId,
        traceRequestId,
      });

      const actionRequest = new AbortController();
      actionsController.current = actionRequest;
      void client
        .sessionActions({
          ref: item.ref,
          maxItems: PAGE_ENTRIES,
          signal: actionRequest.signal,
        })
        .then((page) => {
          dispatch({
            type: "actions_request_succeeded",
            ref: item.ref,
            requestId: actionsRequestId,
            page,
          });
        })
        .catch((error: unknown) => {
          if (!isAbortError(error)) {
            dispatch({
              type: "actions_request_failed",
              ref: item.ref,
              requestId: actionsRequestId,
              error: errorMessage(error),
            });
          }
        })
        .finally(() => {
          if (actionsController.current === actionRequest) {
            actionsController.current = null;
          }
        });

      const traceRequest = new AbortController();
      traceController.current = traceRequest;
      void client
        .sessionTrace({
          ref: item.ref,
          maxChars: PAGE_CHARS,
          maxEntries: PAGE_ENTRIES,
          signal: traceRequest.signal,
        })
        .then((page) => {
          dispatch({
            type: "trace_request_succeeded",
            ref: item.ref,
            requestId: traceRequestId,
            page,
          });
        })
        .catch((error: unknown) => {
          if (!isAbortError(error)) {
            dispatch({
              type: "trace_request_failed",
              ref: item.ref,
              requestId: traceRequestId,
              error: errorMessage(error),
            });
          }
        })
        .finally(() => {
          if (traceController.current === traceRequest) {
            traceController.current = null;
          }
        });
    },
    [abortDetails, client, nextRequestId],
  );

  const actionsPrevious = useCallback(() => {
    dispatch({ type: "actions_previous" });
  }, []);

  const actionsNext = useCallback(() => {
    const detail = state.detail;
    if (!client || !detail || detail.actions.loading) return;
    if (detail.actions.current < detail.actions.pages.length - 1) {
      dispatch({ type: "actions_next_cached" });
      return;
    }
    const page = currentTrailPage(detail.actions);
    if (page?.next_cursor == null) return;
    actionsController.current?.abort();
    const requestId = nextRequestId();
    const controller = new AbortController();
    actionsController.current = controller;
    dispatch({
      type: "actions_request_started",
      ref: detail.ref,
      requestId,
    });
    void client
      .sessionActions({
        ref: detail.ref,
        cursor: page.next_cursor,
        maxItems: PAGE_ENTRIES,
        signal: controller.signal,
      })
      .then((nextPage) => {
        dispatch({
          type: "actions_request_succeeded",
          ref: detail.ref,
          requestId,
          page: nextPage,
        });
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          dispatch({
            type: "actions_request_failed",
            ref: detail.ref,
            requestId,
            error: errorMessage(error),
          });
        }
      })
      .finally(() => {
        if (actionsController.current === controller) {
          actionsController.current = null;
        }
      });
  }, [client, nextRequestId, state.detail]);

  const tracePrevious = useCallback(() => {
    dispatch({ type: "trace_previous" });
  }, []);

  const requestTrace = useCallback(
    (cursor: SessionCursor, maxEntries: number) => {
      const detail = state.detail;
      if (!client || !detail) return;
      traceController.current?.abort();
      const requestId = nextRequestId();
      const controller = new AbortController();
      traceController.current = controller;
      dispatch({
        type: "trace_request_started",
        ref: detail.ref,
        requestId,
      });
      void client
        .sessionTrace({
          ref: detail.ref,
          cursor,
          maxChars: PAGE_CHARS,
          maxEntries,
          signal: controller.signal,
        })
        .then((page) => {
          dispatch({
            type: "trace_request_succeeded",
            ref: detail.ref,
            requestId,
            page,
          });
        })
        .catch((error: unknown) => {
          if (!isAbortError(error)) {
            dispatch({
              type: "trace_request_failed",
              ref: detail.ref,
              requestId,
              error: errorMessage(error),
            });
          }
        })
        .finally(() => {
          if (traceController.current === controller) {
            traceController.current = null;
          }
        });
    },
    [client, nextRequestId, state.detail],
  );

  const traceNext = useCallback(() => {
    const detail = state.detail;
    if (!detail || detail.trace.loading) return;
    if (detail.trace.current < detail.trace.pages.length - 1) {
      dispatch({ type: "trace_next_cached" });
      return;
    }
    const page = currentTrailPage(detail.trace);
    if (page?.next_cursor) requestTrace(page.next_cursor, PAGE_ENTRIES);
  }, [requestTrace, state.detail]);

  const loadTraceIndex = useCallback(
    (index: number) => {
      requestTrace({ entry_index: index, char_offset: 0 }, 1);
    },
    [requestTrace],
  );

  const historyLevel = state.historyPath[state.historyPath.length - 1];
  const history = currentTrailPage(historyLevel.trail);
  const actions = state.detail
    ? currentTrailPage(state.detail.actions)
    : null;
  const trace = state.detail ? currentTrailPage(state.detail.trace) : null;

  return {
    state,
    historyLevel,
    history,
    actions,
    trace,
    historyCanPrevious: historyLevel.trail.current > 0,
    historyCanNext:
      historyLevel.trail.current < historyLevel.trail.pages.length - 1 ||
      history?.next_cursor != null,
    actionsCanPrevious: (state.detail?.actions.current ?? 0) > 0,
    actionsCanNext:
      state.detail !== null &&
      (state.detail.actions.current < state.detail.actions.pages.length - 1 ||
        actions?.next_cursor != null),
    traceCanPrevious: (state.detail?.trace.current ?? 0) > 0,
    traceCanNext:
      state.detail !== null &&
      (state.detail.trace.current < state.detail.trace.pages.length - 1 ||
        trace?.next_cursor != null),
    refresh: loadRoot,
    openSummary,
    historyPrevious,
    historyNext,
    historyBack,
    selectTurn,
    actionsPrevious,
    actionsNext,
    tracePrevious,
    traceNext,
    loadTraceIndex,
  };
}

function emptyTrail<T>(): PageTrail<T> {
  return {
    pages: [],
    current: 0,
    pendingRequestId: null,
    loading: false,
    error: "",
  };
}

function pendingTrail<T>(requestId: number): PageTrail<T> {
  return {
    ...emptyTrail<T>(),
    pendingRequestId: requestId,
    loading: true,
  };
}

function rootHistoryLevel(): HistoryLevelState {
  return {
    label: "Active head",
    trail: emptyTrail(),
  };
}

function startRequest<T>(trail: PageTrail<T>, requestId: number): PageTrail<T> {
  return {
    ...trail,
    pendingRequestId: requestId,
    loading: true,
    error: "",
  };
}

function finishRequest<T>(
  trail: PageTrail<T>,
  page: T,
  append: boolean,
): PageTrail<T> {
  if (!append) {
    return {
      pages: [page],
      current: 0,
      pendingRequestId: null,
      loading: false,
      error: "",
    };
  }
  const pages = [...trail.pages.slice(0, trail.current + 1), page].slice(
    -MAX_TRAIL_PAGES,
  );
  return {
    pages,
    current: pages.length - 1,
    pendingRequestId: null,
    loading: false,
    error: "",
  };
}

function failRequest<T>(trail: PageTrail<T>, error: string): PageTrail<T> {
  return {
    ...trail,
    pendingRequestId: null,
    loading: false,
    error,
  };
}

function updateHistoryLevel(
  state: SessionExplorerState,
  levelIndex: number,
  update: (level: HistoryLevelState) => HistoryLevelState,
  clearSelection = false,
): SessionExplorerState {
  const level = state.historyPath[levelIndex];
  if (!level) return state;
  const nextLevel = update(level);
  if (nextLevel === level) return state;
  const historyPath = [...state.historyPath];
  historyPath[levelIndex] = nextLevel;
  return {
    historyPath,
    selected: clearSelection ? null : state.selected,
    detail: clearSelection ? null : state.detail,
  };
}

function moveCurrentHistory(
  state: SessionExplorerState,
  offset: -1 | 1,
): SessionExplorerState {
  const levelIndex = state.historyPath.length - 1;
  return updateHistoryLevel(
    state,
    levelIndex,
    (level) => {
      const current = level.trail.current + offset;
      if (current < 0 || current >= level.trail.pages.length) return level;
      return {
        ...level,
        trail: { ...level.trail, current, error: "" },
      };
    },
    true,
  );
}

function updateDetail(
  state: SessionExplorerState,
  ref: string,
  update: (detail: TurnDetailState) => TurnDetailState,
): SessionExplorerState {
  if (!state.detail || state.detail.ref !== ref) return state;
  const detail = update(state.detail);
  return detail === state.detail ? state : { ...state, detail };
}

function moveDetailTrail(
  state: SessionExplorerState,
  channel: "actions" | "trace",
  offset: -1 | 1,
): SessionExplorerState {
  if (!state.detail) return state;
  const trail = state.detail[channel];
  const current = trail.current + offset;
  if (current < 0 || current >= trail.pages.length) return state;
  return {
    ...state,
    detail: {
      ...state.detail,
      [channel]: { ...trail, current, error: "" },
    },
  };
}

function trackController(
  controllers: Set<AbortController>,
): AbortController {
  const controller = new AbortController();
  controllers.add(controller);
  return controller;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function shortRef(ref: string): string {
  return ref.split("/").slice(-1)[0] || ref;
}
