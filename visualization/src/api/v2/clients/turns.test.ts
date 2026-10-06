import { describe, expect, it } from "vitest";

import interactions from "../../../../test/fixtures/contracts/interactions.json";
import questionReply from "../../../../test/fixtures/contracts/question-reply.json";
import turnReceipts from "../../../../test/fixtures/contracts/turn-receipts.json";
import turnWaiting from "../../../../test/fixtures/contracts/turn-waiting.json";
import type { InteractionPage } from "../types";
import {
  bodyJson,
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { TurnsClient } from "./turns";

describe("TurnsClient", () => {
  it("create posts kind=user with command_id and client_message_id", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(turnReceipts.create, 202),
    );
    const client = new TurnsClient(transport);
    const receipt = await client.create({
      kind: "user",
      text: "analyze the workspace",
      command_id: "command_123",
      metadata: { client_message_id: "msg_123" },
    });
    expect(receipt).toMatchObject({
      accepted: true,
      command_id: "contract-turn",
      turn_id: "contract-turn",
      state: "queued",
    });
    expect(requests[0]?.method).toBe("POST");
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/requests");
    expect(bodyJson(requests[0]!)).toEqual({
      kind: "user",
      text: "analyze the workspace",
      command_id: "command_123",
      metadata: { client_message_id: "msg_123" },
    });
  });

  it("get returns the TurnSnapshot with question and budget request", async () => {
    const { transport } = createTestTransport(() => jsonResponse(turnWaiting));
    const snapshot = await new TurnsClient(transport).get("contract-turn");
    expect(snapshot.state).toBe("waiting");
    expect(snapshot.question?.question_id).toBe("action_result_1");
    expect(snapshot.budget_request?.request_id).toBe("budget_1");
  });

  it("input, reply, grant and cancel carry their documented bodies", async () => {
    const { transport, requests } = createTestTransport((request) => {
      if (request.url.endsWith("/grant")) {
        return jsonResponse({ turn_id: "t1", request_id: "b1", accepted: true });
      }
      if (request.url.endsWith("/cancel")) {
        return jsonResponse({ turn_id: "t1", accepted: true });
      }
      return jsonResponse({ sequence: 3, record_id: "rec_3", accepted: true });
    });
    const client = new TurnsClient(transport);

    const input = await client.appendInput("t1", { text: "更多约束", input_id: "in_1" });
    expect(input).toMatchObject({ sequence: 3, record_id: "rec_3", accepted: true });
    expect(bodyJson(requests[0]!)).toEqual({ text: "更多约束", input_id: "in_1" });

    const reply = await client.reply("t1", {
      question_id: "q1",
      answer: { kind: "choice", option_id: "execute", comment: "先完成后端" },
    });
    expect(reply.record_id).toBe("rec_3");
    expect(bodyJson(requests[1]!)).toEqual({
      question_id: "q1",
      answer: { kind: "choice", option_id: "execute", comment: "先完成后端" },
    });

    const grant = await client.grant("t1", { budget_request_id: "b1", count: 4 });
    expect(grant).toMatchObject({ turn_id: "t1", request_id: "b1", accepted: true });
    expect(bodyJson(requests[2]!)).toEqual({ budget_request_id: "b1", count: 4 });

    const cancel = await client.cancel("t1");
    expect(cancel).toEqual({ turn_id: "t1", accepted: true });
    expect(requests[3]?.bodyText).toBeUndefined();

    expect(requests.map((r) => new URL(r.url).pathname)).toEqual([
      "/v2/requests/t1/input",
      "/v2/requests/t1/reply",
      "/v2/requests/t1/grant",
      "/v2/requests/t1/cancel",
    ]);
  });

  it("interactions passes continuation and keeps items/pending_items split", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(interactions),
    );
    const page = await new TurnsClient(transport).interactions("contract-turn", {
      continuation: "continuation_2",
      limit: 50,
    });
    expect(queryOf(requests[0]!, "continuation")).toBe("continuation_2");
    expect(queryOf(requests[0]!, "limit")).toBe("50");
    expect(page.turn_id).toBe("contract-turn");
    expect(page.items[0]?.role).toBe("user.input");
    expect(page.pending_items).toEqual([]);
    expect(page.next_continuation).toBe("continuation_3");
  });

  it("question-reply fixture flows through the interaction item shape", async () => {
    const { transport } = createTestTransport(() =>
      jsonResponse({
        ...interactions,
        items: [questionReply.question, questionReply.reply],
      }),
    );
    const page: InteractionPage = await new TurnsClient(transport).interactions(
      "contract-turn",
    );
    const [question, reply] = page.items;
    expect(question?.role).toBe("agent.question");
    expect(reply?.role).toBe("user.reply");
    expect(reply?.question_id).toBe(question?.question_id);
  });
});
