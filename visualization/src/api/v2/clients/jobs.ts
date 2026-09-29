/**
 * API-14: Turn-owned Jobs. Output pages always carry a next_continuation —
 * an empty page while the Job runs is a polling position, and a terminal Job
 * may still have unread output. Stopping a Job never cancels its Turn.
 */

import type { JobDetail, JobList, JobOutputPage } from "../types";
import type { RequestOptions, V2Transport } from "../transport";
import type { ContinuationParams } from "./paging";

export class JobsClient {
  constructor(private readonly transport: V2Transport) {}

  /** GET /v2/turns/{id}/jobs — live job summaries of one Turn. */
  list(turnId: string, options?: RequestOptions): Promise<JobList> {
    return this.transport.get<JobList>(
      `/turns/${encodeURIComponent(turnId)}/jobs`,
      options,
    );
  }

  /** GET /v2/turns/{id}/jobs/{job_id} — owner describe projection. */
  get(
    turnId: string,
    jobId: string,
    options?: RequestOptions,
  ): Promise<JobDetail> {
    return this.transport.get<JobDetail>(
      `/turns/${encodeURIComponent(turnId)}/jobs/${encodeURIComponent(jobId)}`,
      options,
    );
  }

  /** GET /v2/turns/{id}/jobs/{job_id}/output — bounded channel/text page. */
  output(
    turnId: string,
    jobId: string,
    params?: ContinuationParams,
    options?: RequestOptions,
  ): Promise<JobOutputPage> {
    return this.transport.get<JobOutputPage>(
      `/turns/${encodeURIComponent(turnId)}/jobs/${encodeURIComponent(jobId)}/output`,
      { ...options, query: { ...params } },
    );
  }

  /** POST /v2/turns/{id}/jobs/{job_id}/stop — stop intent, not Turn cancel. */
  stop(
    turnId: string,
    jobId: string,
    options?: RequestOptions,
  ): Promise<JobDetail> {
    return this.transport.post<JobDetail>(
      `/turns/${encodeURIComponent(turnId)}/jobs/${encodeURIComponent(jobId)}/stop`,
      options,
    );
  }
}
