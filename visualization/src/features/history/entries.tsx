/**
 * History navigation entries (plan §7).
 *
 * The history browser and the Session map live in the shared Inspector
 * drawer: days → one day's turns → the read-only conversation in the chat
 * view; map → topic/annotation details → evidence facts. Entries form the
 * drawer's back stack; shared nodes keep their ref identity across entries
 * (each visit is a new stack level keyed uniquely, the data model stays flat).
 *
 * The imports of the panels are deferred to the render closures, so the
 * factory ↔ panel import cycle never evaluates a component before both
 * modules finish loading.
 */

import { useAppStore } from "../../store/appStore";
import { useInspectorStore } from "../../store/inspectorStore";
import { useTurnStore } from "../../store/turnStore";
import type { DayEntry } from "../../api/v2/types";
import { openSessionTurn, syncFromStatus } from "../chat/turnController";
import { shortRef } from "./disclosure";
import { DayListPanel } from "./DayListPanel";
import { DayTurnsPanel } from "./DayTurnsPanel";
import { SessionMapPanel } from "./SessionMapPanel";
import { SessionRefPanel } from "./SessionRefPanel";

/** Root of the history browser: the day directory. */
export function openHistoryBrowser(epoch: number): void {
  useInspectorStore.getState().open({
    key: "history:days",
    title: "History",
    subtitle: "Pick a day to browse its conversations",
    render: () => <DayListPanel epoch={epoch} />,
  });
}

/** One day's committed turns (plus the live/queued rows of the active day). */
export function pushDayTurns(epoch: number, day: DayEntry): void {
  useInspectorStore.getState().push({
    key: `history:day:${day.day}`,
    title: day.day,
    subtitle: day.active ? "Active day" : "Archived day · read-only",
    render: () => <DayTurnsPanel epoch={epoch} day={day} />,
  });
}

/** The Session map of one day: topics, interpretations, turns. */
export function openSessionMap(epoch: number, day: string): void {
  useInspectorStore.getState().open({
    key: `session-map:${day}`,
    title: "Session map",
    subtitle: day,
    render: () => <SessionMapPanel epoch={epoch} day={day} />,
  });
}

let refEntryCounter = 0;

/** Push an inspect detail for one Session ref (topic, edge, turn, fact…). */
export function pushSessionRef(
  epoch: number,
  day: string,
  ref: string,
  title?: string,
): void {
  refEntryCounter += 1;
  useInspectorStore.getState().push({
    key: `session-ref:${day}:${ref}:${refEntryCounter}`,
    title: title ?? shortRef(ref),
    subtitle: ref,
    copyText: ref,
    render: () => <SessionRefPanel epoch={epoch} day={day} targetRef={ref} />,
  });
}

/** Push a deterministic locate-in-scope result for one Session ref. */
export function pushSessionQuery(
  epoch: number,
  day: string,
  ref: string,
  query: string,
): void {
  refEntryCounter += 1;
  useInspectorStore.getState().push({
    key: `session-ref:${day}:${ref}:query:${refEntryCounter}`,
    title: `Locate: ${query}`,
    subtitle: ref,
    render: () => (
      <SessionRefPanel epoch={epoch} day={day} targetRef={ref} initialQuery={query} />
    ),
  });
}

/** Open a committed turn read-only in the chat view, leaving the drawer. */
export function openHistoryConversation(
  epoch: number,
  turnId: string,
  day: string,
): void {
  useInspectorStore.getState().close();
  useAppStore.getState().setActiveTab("chat");
  void openSessionTurn(epoch, turnId, day);
}

/** Leave history and return to the live turn (or the day list when idle). */
export function backToLiveTurn(epoch: number): void {
  useInspectorStore.getState().close();
  useAppStore.getState().setActiveTab("chat");
  useTurnStore.getState().clearTurn();
  void syncFromStatus(epoch);
}
