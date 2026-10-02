import { useEffect, useState } from "react";
import type { ContextMessage } from "../../api/v2/types";
import { createPageAssembler, nextContinuation } from "../../api/v2/pagination";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { readEventWindow } from "../trace/eventWindow";
import { asObject, asString } from "../trace/facts";
import { narrowMessage } from "../context/messages";
import { presentationStore } from "./presentationStore";
import type { WorkingState } from "./presentation";

const EMPTY: WorkingState = { todos: [], milestones: [] };

/** Reads the installed plan; never reconstructs it from model tool intentions. */
export function workingFromMessages(messages: ContextMessage[]): WorkingState {
  for (const message of messages) {
    const view = narrowMessage(message.message);
    if (view?.label !== "plan") continue;
    const values: unknown[] = view.extras.flatMap((part) => {
      const object = asObject(part);
      return object?.type === "json" ? [object.value] : [];
    });
    for (const text of view.texts) {
      try { values.push(JSON.parse(text)); } catch { /* Plain text is not a plan. */ }
    }
    for (const value of values) {
      const plan = asObject(value);
      if (plan === null) continue;
      return {
        todos: (Array.isArray(plan.todos) ? plan.todos : []).flatMap((value) => {
          const todo = asObject(value);
          const id = asString(todo?.key), content = asString(todo?.content), status = todo?.status;
          if (id === null || content === null || !["pending", "in_progress", "done", "cancelled"].includes(String(status))) return [];
          return [{ id, text: content, status: status as WorkingState["todos"][number]["status"] }];
        }),
        milestones: (Array.isArray(plan.milestones) ? plan.milestones : []).flatMap((value) => {
          const milestone = asObject(value);
          const id = asString(milestone?.key), content = asString(milestone?.content);
          return id !== null && content !== null ? [{ id, text: content }] : [];
        }),
      };
    }
  }
  return EMPTY;
}

/** The live card owns these bounded reads for its mounted Turn only. */
export function useActivityDetails() {
  const epoch = useConnectionStore((s) => s.epoch);
  const installed = useConnectionStore((s) => s.contextGeneration);
  const clients = useConnectionStore((s) => s.clients);
  const eventsPhase = useConnectionStore((s) => s.eventsPhase);
  const gap = useConnectionStore((s) => s.eventGap);
  const turnId = useTurnStore((s) => s.turnId);
  const active = useTurnStore((s) => s.snapshot !== null && s.snapshot.state !== "finished");
  const [working, setWorking] = useState<{ turnId: string; value: WorkingState } | null>(null);

  useEffect(() => {
    if (!clients || !turnId || gap) return;
    const controller = new AbortController();
    const buffer = presentationStore.getState().activityBuffer;
    // Recover the retained activity after mounting/reconnecting. Merge by sequence
    // with the live stream, which may have advanced while the read was in flight.
    void readEventWindow(clients, { mode: "model", turn_id: turnId }, {
      through: useConnectionStore.getState().eventCursor, signal: controller.signal,
    }).then((window) => {
      if (controller.signal.aborted || presentationStore.getState().activityBuffer !== buffer) return;
      presentationStore.getState().loadEvents(window.events);
      if (window.truncated) buffer?.markIncomplete();
      presentationStore.getState().refresh();
    }).catch(() => { if (!controller.signal.aborted) presentationStore.getState().markIncomplete(); });
    return () => controller.abort();
  }, [clients, epoch, turnId, eventsPhase, gap]);

  useEffect(() => {
    if (!clients || !turnId || !active) return;
    const controller = new AbortController();
    const signal = controller.signal;
    const read = async () => {
      const overview = await clients.context.overview(turnId, { signal });
      const segment = overview.segments.find((entry) => entry.id === "plan" && entry.slot === "working");
      if (!segment) { if (!signal.aborted) setWorking({ turnId, value: EMPTY }); return; }
      const assembler = createPageAssembler<ContextMessage>((value) => value as ContextMessage);
      const messages: ContextMessage[] = [];
      let continuation: string | null = null;
      do {
        const page = await clients.context.segment(turnId, segment.id, { continuation: continuation ?? undefined }, { signal });
        messages.push(...assembler.push({ items: page.messages, content_fragment: page.content_fragment }));
        continuation = nextContinuation(page);
      } while (continuation !== null && !signal.aborted);
      if (!signal.aborted) setWorking({ turnId, value: workingFromMessages(messages) });
    };
    // A closed Context keeps its last installed view; no owner mutation or retry.
    void read().catch(() => {});
    return () => controller.abort();
  }, [clients, epoch, turnId, active, installed]);
  return working?.turnId === turnId ? working.value : EMPTY;
}
