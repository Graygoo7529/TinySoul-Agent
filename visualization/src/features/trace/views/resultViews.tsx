/**
 * Result-family views (plan §9.1) — one Action family per file; shared
 * pieces live in resultShared.tsx.
 */

import type { ComponentType } from "react";
import type { ActionFamily, ResultViewProps } from "../model/registry";
import { GenericView } from "./resultShared";
import { SearchFamilyView, InspectView, WriteView } from "./resultSearchInspect";
import { WebView } from "./resultWeb";
import { AnalysisView } from "./resultAnalysis";
import { ExecutionView, JobControlView, AcpView, McpView } from "./resultExecution";
import { SessionOrganizeView, ReflectionWriteView, CoreDialogView } from "./resultSession";

// ---------------------------------------------------------------------------
// Family resolution
// ---------------------------------------------------------------------------

export const FAMILY_VIEWS: Readonly<
  Record<ActionFamily, ComponentType<ResultViewProps>>
> = {
  search: SearchFamilyView,
  inspect: InspectView,
  write: WriteView,
  web: WebView,
  analysis: AnalysisView,
  execution: ExecutionView,
  "job-control": JobControlView,
  acp: AcpView,
  mcp: McpView,
  "session-organize": SessionOrganizeView,
  "reflection-write": ReflectionWriteView,
  "core-dialog": CoreDialogView,
  generic: GenericView,
};
