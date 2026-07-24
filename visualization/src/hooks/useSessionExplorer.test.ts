import { describe, expect, it } from "vitest";

import type {
  SessionActions,
  SessionHistory,
  SessionHistoryItem,
  SessionTrace,
} from "../types";
import {
  MAX_TRAIL_PAGES,
  createSessionExplorerState,
  sessionExplorerReducer,
} from "./useSessionExplorer";

describe("sessionExplorerReducer", () => {
  it("rejects detail responses that belong to an earlier Turn", () => {
    let state = createSessionExplorerState();
    state = sessionExplorerReducer(state, {
      type: "turn_selected",
      item: turn("session:a"),
      actionsRequestId: 1,
      traceRequestId: 2,
    });
    state = sessionExplorerReducer(state, {
      type: "turn_selected",
      item: turn("session:b"),
      actionsRequestId: 3,
      traceRequestId: 4,
    });

    state = sessionExplorerReducer(state, {
      type: "actions_request_succeeded",
      ref: "session:a",
      requestId: 1,
      page: actionsPage(0),
    });
    state = sessionExplorerReducer(state, {
      type: "trace_request_succeeded",
      ref: "session:a",
      requestId: 2,
      page: tracePage(0),
    });

    expect(state.detail?.ref).toBe("session:b");
    expect(state.detail?.actions.pages).toEqual([]);
    expect(state.detail?.trace.pages).toEqual([]);
  });

  it("settles actions and trace independently", () => {
    let state = createSessionExplorerState();
    state = sessionExplorerReducer(state, {
      type: "turn_selected",
      item: turn("session:b"),
      actionsRequestId: 10,
      traceRequestId: 11,
    });
    state = sessionExplorerReducer(state, {
      type: "actions_request_failed",
      ref: "session:b",
      requestId: 10,
      error: "actions unavailable",
    });
    const trace = tracePage(0);
    state = sessionExplorerReducer(state, {
      type: "trace_request_succeeded",
      ref: "session:b",
      requestId: 11,
      page: trace,
    });

    expect(state.detail?.actions.error).toBe("actions unavailable");
    expect(state.detail?.actions.loading).toBe(false);
    expect(state.detail?.trace.pages).toEqual([trace]);
    expect(state.detail?.trace.error).toBe("");
  });

  it("rejects an older request for the currently selected Turn", () => {
    let state = createSessionExplorerState();
    state = sessionExplorerReducer(state, {
      type: "turn_selected",
      item: turn("session:b"),
      actionsRequestId: 20,
      traceRequestId: 21,
    });
    state = sessionExplorerReducer(state, {
      type: "trace_request_started",
      ref: "session:b",
      requestId: 22,
    });

    state = sessionExplorerReducer(state, {
      type: "trace_request_succeeded",
      ref: "session:b",
      requestId: 21,
      page: tracePage(1),
    });

    expect(state.detail?.trace.pages).toEqual([]);
    expect(state.detail?.trace.pendingRequestId).toBe(22);
    expect(state.detail?.trace.loading).toBe(true);
  });

  it("keeps cached pages and parent levels available for backward navigation", () => {
    let state = createSessionExplorerState();
    state = sessionExplorerReducer(state, {
      type: "root_request_started",
      requestId: 1,
    });
    state = sessionExplorerReducer(state, {
      type: "history_request_succeeded",
      levelIndex: 0,
      requestId: 1,
      page: historyPage(0, true),
      append: false,
    });
    state = sessionExplorerReducer(state, {
      type: "history_request_started",
      levelIndex: 0,
      requestId: 2,
    });
    state = sessionExplorerReducer(state, {
      type: "history_request_succeeded",
      levelIndex: 0,
      requestId: 2,
      page: historyPage(1, false),
      append: true,
    });

    state = sessionExplorerReducer(state, { type: "history_previous" });
    expect(state.historyPath[0].trail.current).toBe(0);
    state = sessionExplorerReducer(state, { type: "history_next_cached" });
    expect(state.historyPath[0].trail.current).toBe(1);

    state = sessionExplorerReducer(state, {
      type: "history_level_opened",
      ref: "session:summary",
      label: "summary",
      requestId: 3,
    });
    state = sessionExplorerReducer(state, {
      type: "history_request_succeeded",
      levelIndex: 1,
      requestId: 3,
      page: historyPage(0, false),
      append: false,
    });
    state = sessionExplorerReducer(state, { type: "history_back" });

    expect(state.historyPath).toHaveLength(1);
    expect(state.historyPath[0].trail.pages).toHaveLength(2);
    expect(state.historyPath[0].trail.current).toBe(1);
  });

  it("bounds the retained forward page trail", () => {
    let state = createSessionExplorerState();
    state = sessionExplorerReducer(state, {
      type: "root_request_started",
      requestId: 1,
    });
    state = sessionExplorerReducer(state, {
      type: "history_request_succeeded",
      levelIndex: 0,
      requestId: 1,
      page: historyPage(0, true),
      append: false,
    });

    for (let index = 1; index <= MAX_TRAIL_PAGES + 2; index += 1) {
      const requestId = index + 1;
      state = sessionExplorerReducer(state, {
        type: "history_request_started",
        levelIndex: 0,
        requestId,
      });
      state = sessionExplorerReducer(state, {
        type: "history_request_succeeded",
        levelIndex: 0,
        requestId,
        page: historyPage(index, true),
        append: true,
      });
    }

    expect(state.historyPath[0].trail.pages).toHaveLength(MAX_TRAIL_PAGES);
    expect(state.historyPath[0].trail.current).toBe(MAX_TRAIL_PAGES - 1);
    expect(state.historyPath[0].trail.pages[0].cursor.entry_index).toBe(3);
  });

  it("resets navigation and detail state when a new root snapshot starts", () => {
    let state = createSessionExplorerState();
    state = sessionExplorerReducer(state, {
      type: "history_level_opened",
      ref: "session:summary",
      label: "summary",
      requestId: 1,
    });
    state = sessionExplorerReducer(state, {
      type: "turn_selected",
      item: turn("session:a"),
      actionsRequestId: 2,
      traceRequestId: 3,
    });

    state = sessionExplorerReducer(state, {
      type: "root_request_started",
      requestId: 4,
    });

    expect(state.historyPath).toHaveLength(1);
    expect(state.historyPath[0].trail.pages).toEqual([]);
    expect(state.historyPath[0].trail.pendingRequestId).toBe(4);
    expect(state.selected).toBeNull();
    expect(state.detail).toBeNull();
  });
});

function turn(ref: string): SessionHistoryItem {
  return {
    item_id: ref,
    ref,
    kind: "turn",
    char_count: 1,
    child_count: 0,
    preview: {},
  };
}

function historyPage(index: number, hasNext: boolean): SessionHistory {
  return {
    source: {},
    items: [],
    cursor_unit: "history_item",
    entry_count: index + 1,
    returned_entry_count: 0,
    returned_entry_indexes: [],
    entry_coverage: [index, index],
    remaining_entry_count: hasNext ? 1 : 0,
    requested_max_chars: 8000,
    effective_max_chars: 8000,
    requested_max_entries: 20,
    effective_max_entries: 20,
    cursor: { entry_index: index, char_offset: 0 },
    next_cursor: hasNext
      ? { entry_index: index + 1, char_offset: 0 }
      : null,
    page_complete: !hasNext,
    truncated: hasNext,
  };
}

function tracePage(index: number): SessionTrace {
  return {
    source: {},
    cursor_unit: "trace_entry",
    entry_count: 1,
    returned_entry_count: 1,
    returned_entry_indexes: [index],
    entry_coverage: [index, index + 1],
    remaining_entry_count: 0,
    requested_max_chars: 8000,
    effective_max_chars: 8000,
    requested_max_entries: 20,
    effective_max_entries: 20,
    cursor: { entry_index: index, char_offset: 0 },
    next_cursor: null,
    page_complete: true,
    truncated: false,
    trace: [{}],
  };
}

function actionsPage(cursor: number): SessionActions {
  return {
    source: {},
    summary: {
      trace_digest: "digest",
      outcome: {
        call_count: 0,
        result_count: 0,
        success_count: 0,
        failed_count: 0,
        timeout_count: 0,
        unmatched_call_count: 0,
        unmatched_result_count: 0,
        pairing_issue_count: 0,
        scan_complete: true,
        pairing_complete: true,
      },
      by_action: [],
      failure_groups: [],
    },
    details: [],
    detail_count: 0,
    requested_max_items: 20,
    effective_max_items: 20,
    returned_detail_count: 0,
    cursor,
    next_cursor: null,
    coverage: [cursor, cursor],
    remaining: 0,
    page_complete: true,
    truncated: false,
  };
}
