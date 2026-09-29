/**
 * Job detail and output pages.
 * Schemas: job.json, job-output.json, job-list.json.
 * Examples: job-detail, job-output.
 */

import type { ResourceLocator } from "./common";
import type { JsonObject, JsonValue } from "./json";
import type { JobSummary } from "./turn";

/** Schema: job.json (GET /v2/turns/{id}/jobs/{job_id}). */
export interface JobDetail extends JobSummary {
  details?: JsonObject | null;
}

/** Schema: job-list.json (GET /v2/turns/{id}/jobs). */
export interface JobList {
  turn_id: string;
  jobs: JobSummary[];
  [key: string]: unknown;
}

/** JobOutputPage.items[]: one bounded channel chunk. */
export interface JobOutputItem {
  channel: string;
  text: string;
  [key: string]: unknown;
}

/**
 * Schema: job-output.json (GET /v2/turns/{id}/jobs/{job_id}/output).
 * `next_continuation` is always present: an empty page while the Job runs is
 * a polling position, not the end. `truncated` marks a bounded read, never
 * data loss. Job terminal state and output read progress are independent.
 */
export interface JobOutputPage {
  job_id: string;
  items: JobOutputItem[];
  next_continuation: string;
  truncated: boolean;
  result_locators: (ResourceLocator | JsonValue)[];
  [key: string]: unknown;
}
