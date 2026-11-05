/**
 * Interaction answers and cancels (split from turnController.ts): question
 * replies, budget grants, queued-request and reflection cancellation — each a
 * single intent POST on top of the shared helpers in ./turnShared.
 */

import {
  message,
} from "../../i18n/core";
import type { QuestionAnswer } from "../../api/v2/types";
import {
  apiErrorCode,
} from "../../api/v2/errors";
import {
  useTurnStore,
  requestIdForTurn,
} from "../../store/turnStore";
import { randomId } from "../../utils/randomId";
import { postCancelIntent, refreshCommandTarget } from "./turnController";
import { clientsFor, errorMessage, toast } from "./turnShared";

/** Reply to the currently pending question (choice with comment, or text). */
export async function replyToQuestion(
  epoch: number,
  turnId: string,
  questionId: string,
  answer: QuestionAnswer,
  displayText: string,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null) return false;
  const requestId = requestIdForTurn(turnId);
  const store = useTurnStore.getState();
  const echoId = randomId();
  store.addEcho({
    echoId,
    kind: "reply",
    requestId,
    questionId,
    text: displayText,
    state: "sending",
    error: null,
    turnClosed: false,
  });
  try {
    const receipt = await clients.turns.reply(requestId, {
      question_id: questionId,
      answer,
    });
    if (clientsFor(epoch) === null) return true;
    if (receipt.accepted === false) {
      // Already answered earlier: the formal reply will render; no error.
      useTurnStore.getState().removeEcho(echoId);
    } else {
      useTurnStore.getState().updateEcho(echoId, { state: "accepted" });
    }
    refreshCommandTarget(epoch, requestId);
    return true;
  } catch (error) {
    if (clientsFor(epoch) === null) return true;
    // The echo goes away; the question card keeps its draft and shows the
    // failure next to the submit control.
    useTurnStore.getState().removeEcho(echoId);
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      refreshCommandTarget(epoch, requestId);
    }
    throw error;
  }
}

/** Grant cycles for the open budget request. */

/** Grant cycles for the open budget request. */
export async function grantBudget(
  epoch: number,
  rootRequestId: string,
  requestId: string,
  count: number,
): Promise<boolean> {
  const clients = clientsFor(epoch);
  if (clients === null || count <= 0) return false;
  try {
    await clients.turns.grant(rootRequestId, { budget_request_id: requestId, count });
    refreshCommandTarget(epoch, rootRequestId);
    return true;
  } catch (error) {
    if (clientsFor(epoch) === null) return false;
    const code = apiErrorCode(error);
    if (code === "turn.command_rejected" || code === "turn.not_found") {
      refreshCommandTarget(epoch, rootRequestId);
      toast("info", message("chat.budgetClosed"));
      return false;
    }
    toast("error", message("chat.budgetFailed", { detail: errorMessage(error) }));
    return false;
  }
}

/** Ask the active turn to stop; the receipt only confirms the intent. */

/** Runtime queue management targets a specific request, independent of Chat. */
export async function cancelQueuedTurn(epoch: number, turnId: string): Promise<void> {
  await postCancelIntent(epoch, turnId);
}

export async function cancelReflection(epoch: number, turnId: string): Promise<void> {
  await postCancelIntent(epoch, turnId);
}

/** Re-send a failed echo with its original request identity. */
