import { describe, expect, it } from "vitest";

import jobDetail from "../../../../test/fixtures/contracts/job-detail.json";
import jobOutput from "../../../../test/fixtures/contracts/job-output.json";
import {
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { JobsClient } from "./jobs";
import { jobOutputContinuation } from "../pagination";

describe("JobsClient", () => {
  it("lists the jobs of a turn", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({ turn_id: "contract-turn", jobs: [jobDetail] }),
    );
    const list = await new JobsClient(transport).list("contract-turn");
    expect(list.jobs[0]?.job_id).toBe("job_1");
    expect(new URL(requests[0]!.url).pathname).toBe(
      "/v2/requests/contract-turn/jobs",
    );
  });

  it("detail and stop share the job route", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(jobDetail),
    );
    const client = new JobsClient(transport);
    const detail = await client.get("contract-turn", "job_1");
    expect(detail.state).toBe("running");
    expect(detail.result_refs.length).toBeGreaterThan(0);
    const stopped = await client.stop("contract-turn", "job_1");
    expect(stopped.job_id).toBe("job_1");
    expect(requests.map((r) => [r.method, new URL(r.url).pathname])).toEqual([
      ["GET", "/v2/requests/contract-turn/jobs/job_1"],
      ["POST", "/v2/requests/contract-turn/jobs/job_1/stop"],
    ]);
  });

  it("output keeps the polling token even for empty pages", async () => {
    const { transport, requests } = createTestTransport((request) =>
      jsonResponse(
        queryOf(request, "continuation") === null
          ? jobOutput
          : { ...jobOutput, items: [] },
      ),
    );
    const client = new JobsClient(transport);
    const first = await client.output("contract-turn", "job_1");
    expect(first.items.map((item) => item.channel)).toEqual([
      "stdout",
      "stderr",
    ]);
    expect(first.result_locators).toHaveLength(3);
    const second = await client.output("contract-turn", "job_1", {
      continuation: jobOutputContinuation(first),
    });
    expect(second.items).toEqual([]);
    expect(jobOutputContinuation(second)).toBe("continuation_2");
    expect(queryOf(requests[1]!, "continuation")).toBe("continuation_2");
  });
});
