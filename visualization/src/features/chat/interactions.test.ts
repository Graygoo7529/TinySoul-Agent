import { describe, expect, it } from "vitest";

import type { Interaction, TurnSnapshot } from "../../api/v2/types";
import type { OutgoingEcho } from "../../store/turnStore";
import {
  makeStatus,
  runningSnapshot,
  waitingSnapshot,
} from "../../app/testing";
import {
  canCancelActiveTurn,
  convergeEchoes,
  formalItemForEcho,
  mergeInteractions,
  pendingItemForEcho,
  resolveComposerIntent,
} from "./interactions";

function interaction(
  partial: Partial<Interaction> & { id: string; role: Interaction["role"] },
): Interaction {
  return { kind: "interaction", ref: `turn:t#${partial.id}`, ...partial };
}

function echo(partial: Partial<OutgoingEcho> & { echoId: string }): OutgoingEcho {
  return {
    kind: "append",
    turnId: null,
    questionId: null,
    text: "text",
    state: "accepted",
    error: null,
    ...partial,
  };
}

describe("mergeInteractions", () => {
  it("returns the current list when nothing arrives", () => {
    const current = [interaction({ id: "a", role: "user.input" })];
    expect(mergeInteractions(current, [])).toBe(current);
  });

  it("updates by id in place and keeps positions", () => {
    const current = [
      interaction({ id: "a", role: "user.input", text: "old" }),
      interaction({ id: "b", role: "agent.output", text: "answer" }),
    ];
    const merged = mergeInteractions(current, [
      interaction({ id: "a", role: "user.input", text: "new" }),
    ]);
    expect(merged.map((item) => item.id)).toEqual(["a", "b"]);
    expect(merged[0]?.text).toBe("new");
    expect(merged).toHaveLength(2);
  });

  it("appends new items after the existing ones, in arrival order", () => {
    const current = [interaction({ id: "a", role: "user.input" })];
    const merged = mergeInteractions(current, [
      interaction({ id: "c", role: "agent.reason" }),
      interaction({ id: "b", role: "agent.output" }),
      interaction({ id: "a", role: "user.input", text: "updated" }),
    ]);
    expect(merged.map((item) => item.id)).toEqual(["a", "c", "b"]);
    expect(merged[0]?.text).toBe("updated");
  });
});

describe("formalItemForEcho", () => {
  it("matches an append echo by interaction id", () => {
    const item = interaction({ id: "in-1", role: "user.append" });
    expect(
      formalItemForEcho(echo({ echoId: "in-1", kind: "append" }), [item]),
    ).toBe(item);
  });

  it("matches an append echo by the #input/ ref suffix", () => {
    const item = interaction({
      id: "server-side-id",
      role: "user.input",
      ref: "turn:t#input/in-2",
    });
    expect(
      formalItemForEcho(echo({ echoId: "in-2", kind: "append" }), [item]),
    ).toBe(item);
  });

  it("never matches an append echo against agent roles", () => {
    const item = interaction({ id: "in-1", role: "agent.output" });
    expect(
      formalItemForEcho(echo({ echoId: "in-1", kind: "append" }), [item]),
    ).toBeNull();
  });

  it("matches a reply echo by question_id on user.reply items only", () => {
    const reply = interaction({
      id: "r1",
      role: "user.reply",
      question_id: "q1",
    });
    const otherQuestion = interaction({
      id: "r2",
      role: "user.reply",
      question_id: "q2",
    });
    const agentQuestion = interaction({
      id: "r3",
      role: "agent.question",
      question_id: "q1",
    });
    const target = echo({ echoId: "e", kind: "reply", questionId: "q1" });
    expect(formalItemForEcho(target, [otherQuestion, agentQuestion, reply])).toBe(
      reply,
    );
  });

  it("matches a new-turn echo by role + exact text once the turn is known", () => {
    const item = interaction({ id: "s1", role: "user.input", text: "hello" });
    const known = echo({
      echoId: "e",
      kind: "new-turn",
      turnId: "t1",
      text: "hello",
    });
    expect(formalItemForEcho(known, [item])).toBe(item);
    // Without the receipt's turn_id the identity is not established yet.
    expect(
      formalItemForEcho(echo({ echoId: "e", kind: "new-turn", text: "hello" }), [
        item,
      ]),
    ).toBeNull();
    // Text must match exactly.
    expect(
      formalItemForEcho(
        echo({ echoId: "e", kind: "new-turn", turnId: "t1", text: "hello " }),
        [item],
      ),
    ).toBeNull();
  });
});

describe("pendingItemForEcho", () => {
  const pending = {
    record_id: "in-1",
    sequence: 1,
    kind: "input",
    payload: {},
    state: "accepted",
  };

  it("matches append/new-turn echoes by record_id", () => {
    expect(
      pendingItemForEcho(echo({ echoId: "in-1", kind: "append" }), [pending]),
    ).toBe(pending);
    expect(
      pendingItemForEcho(echo({ echoId: "other", kind: "append" }), [pending]),
    ).toBeNull();
  });

  it("matches reply echoes through the reply_<question_id> record", () => {
    const replyPending = { ...pending, record_id: "reply_q1" };
    expect(
      pendingItemForEcho(echo({ echoId: "e", kind: "reply", questionId: "q1" }), [
        replyPending,
      ]),
    ).toBe(replyPending);
    expect(
      pendingItemForEcho(echo({ echoId: "reply_q1", kind: "reply", questionId: "q2" }), [
        replyPending,
      ]),
    ).toBeNull();
  });
});

describe("convergeEchoes", () => {
  it("consumes echoes covered by pending or formal projections", () => {
    const echoes = [
      echo({ echoId: "a1", kind: "append", turnId: "t1" }),
      echo({ echoId: "a2", kind: "append", turnId: "t1" }),
      echo({ echoId: "a3", kind: "append", turnId: "t1" }),
    ];
    const pendingItems = [
      { record_id: "a1", sequence: 1, kind: "input", payload: {}, state: "accepted" },
    ];
    const items = [interaction({ id: "a2", role: "user.append" })];
    const result = convergeEchoes(echoes, items, pendingItems, "t1");
    expect(result.consumed).toEqual(["a1", "a2"]);
    expect(result.waiting.map((item) => item.echoId)).toEqual(["a3"]);
  });

  it("keeps failed echoes until the user retries or dismisses them", () => {
    const failed = echo({
      echoId: "a1",
      kind: "append",
      turnId: "t1",
      state: "failed",
      error: "boom",
    });
    const items = [interaction({ id: "a1", role: "user.append" })];
    const result = convergeEchoes([failed], items, [], "t1");
    expect(result.consumed).toEqual([]);
    expect(result.waiting).toEqual([failed]);
  });

  it("keeps echoes bound to another (e.g. still queued) turn", () => {
    const queued = echo({
      echoId: "a1",
      kind: "new-turn",
      turnId: "t2",
      text: "hello",
    });
    const items = [interaction({ id: "s1", role: "user.input", text: "hello" })];
    const result = convergeEchoes([queued], items, [], "t1");
    expect(result.consumed).toEqual([]);
    expect(result.waiting).toEqual([queued]);
  });

  it("matches against the projection when no turn is displayed", () => {
    const target = echo({ echoId: "a1", kind: "append", turnId: "t1" });
    const items = [interaction({ id: "a1", role: "user.append" })];
    expect(convergeEchoes([target], items, [], null).consumed).toEqual(["a1"]);
  });
});

describe("resolveComposerIntent", () => {
  it("is unavailable while offline", () => {
    expect(resolveComposerIntent(null, null, false)).toEqual({
      kind: "unavailable",
      reason: "offline",
    });
    expect(resolveComposerIntent(makeStatus(), null, false)).toEqual({
      kind: "unavailable",
      reason: "offline",
    });
    expect(resolveComposerIntent(null, null, true)).toEqual({
      kind: "unavailable",
      reason: "offline",
    });
  });

  it("is unavailable while the backend is not ready", () => {
    expect(
      resolveComposerIntent(makeStatus({ ready: false }), null, true),
    ).toEqual({ kind: "unavailable", reason: "not-ready" });
  });

  it("starts a new turn while idle", () => {
    expect(resolveComposerIntent(makeStatus(), null, true)).toEqual({
      kind: "new-turn",
      queued: false,
    });
  });

  it("queues the new turn when earlier requests already wait", () => {
    expect(
      resolveComposerIntent(makeStatus({ queuedTurnIds: ["t9"] }), null, true),
    ).toEqual({ kind: "new-turn", queued: true });
  });

  it("appends to the active user turn in preparing/running/waiting", () => {
    for (const snapshot of [
      runningSnapshot(),
      waitingSnapshot(),
      { ...runningSnapshot(), state: "preparing" } as TurnSnapshot,
    ]) {
      const status = makeStatus({
        activity: "user_turn",
        activeTurnId: "contract-turn",
      });
      expect(resolveComposerIntent(status, snapshot, true)).toEqual({
        kind: "append",
        turnId: "contract-turn",
      });
    }
  });

  it("queues a new turn while the active turn is finalizing", () => {
    const status = makeStatus({
      activity: "user_turn",
      activeTurnId: "contract-turn",
    });
    const snapshot = {
      ...runningSnapshot(),
      state: "finalizing",
    } as TurnSnapshot;
    expect(resolveComposerIntent(status, snapshot, true)).toEqual({
      kind: "new-turn",
      queued: true,
    });
  });

  it("queues a new turn while a reflection turn is active", () => {
    const status = makeStatus({
      activity: "reflection_turn",
      activeTurnId: "reflection-turn",
    });
    const snapshot = {
      ...runningSnapshot("reflection-turn"),
      kind: "memory",
    } as TurnSnapshot;
    expect(resolveComposerIntent(status, snapshot, true)).toEqual({
      kind: "new-turn",
      queued: true,
    });
  });

  it("queues a new turn while the active snapshot is unknown or stale", () => {
    const status = makeStatus({
      activity: "user_turn",
      activeTurnId: "contract-turn",
    });
    // Snapshot still loading: no snapshot to trust.
    expect(resolveComposerIntent(status, null, true)).toEqual({
      kind: "new-turn",
      queued: true,
    });
    // Snapshot of a different turn: not the active one's authority.
    expect(resolveComposerIntent(status, runningSnapshot("other-turn"), true)).toEqual(
      { kind: "new-turn", queued: true },
    );
  });
});

describe("canCancelActiveTurn", () => {
  const status = makeStatus({
    activity: "user_turn",
    activeTurnId: "contract-turn",
  });

  it("allows cancelling queued/preparing/running/waiting snapshots", () => {
    for (const state of ["queued", "preparing", "running", "waiting"]) {
      const snapshot = { ...runningSnapshot(), state } as TurnSnapshot;
      expect(canCancelActiveTurn(status, snapshot)).toBe(true);
    }
  });

  it("rejects finished, already-cancelled, stale or missing snapshots", () => {
    const finished = { ...runningSnapshot(), state: "finished" } as TurnSnapshot;
    expect(canCancelActiveTurn(status, finished)).toBe(false);
    const cancelled = { ...runningSnapshot(), cancel_requested: true };
    expect(canCancelActiveTurn(status, cancelled)).toBe(false);
    expect(canCancelActiveTurn(status, runningSnapshot("other-turn"))).toBe(false);
    expect(canCancelActiveTurn(status, null)).toBe(false);
    expect(canCancelActiveTurn(null, runningSnapshot())).toBe(false);
  });
});
