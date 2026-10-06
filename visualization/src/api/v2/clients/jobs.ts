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

  /** GET /v2/requests/{id}/jobs — live job summaries of one Turn. */
  list(requestId: string, options?: RequestOptions): Promise<JobList> {
    return this.transport.get<JobList>(
      `/requests/${encodeURIComponent(requestId)}/jobs`,
      options,
    );
  }

  /** GET /v2/requests/{id}/jobs/{job_id} — owner describe projection. */
  get(
    requestId: string,
    jobId: string,
    options?: RequestOptions,
  ): Promise<JobDetail> {
    return this.transport.get<JobDetail>(
      `/requests/${encodeURIComponent(requestId)}/jobs/${encodeURIComponent(jobId)}`,
      options,
    );
  }

  /** GET /v2/requests/{id}/jobs/{job_id}/output — bounded channel/text page. */
  output(
    requestId: string,
    jobId: string,
    params?: ContinuationParams,
    options?: RequestOptions,
  ): Promise<JobOutputPage> {
    return this.transport.get<JobOutputPage>(
      `/requests/${encodeURIComponent(requestId)}/jobs/${encodeURIComponent(jobId)}/output`,
      { ...options, query: { ...params } },
    );
  }

  /** POST /v2/requests/{id}/jobs/{job_id}/stop — stop intent, not Turn cancel. */
  stop(
    requestId: string,
    jobId: string,
    options?: RequestOptions,
  ): Promise<JobDetail> {
    return this.transport.post<JobDetail>(
      `/requests/${encodeURIComponent(requestId)}/jobs/${encodeURIComponent(jobId)}/stop`,
      options,
    );
  }
}
