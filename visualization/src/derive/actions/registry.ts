/**
 * Action presentation registry.
 *
 * `descriptorFor(action)` resolves the presentation descriptor for one action
 * name; unknown actions fall back to a generic descriptor (verb "Executing",
 * family "generic", default target extraction and result summary).
 */

import type { ActionResultView } from "../model";
import { targetLabel } from "../activitySemantics";
import type { ActionDescriptor, ResultSummary } from "./types";
import { defaultResultSummary, defaultTargetOf } from "./common";
import { CORE_ACTIONS } from "./core";
import { WORKSPACE_ACTIONS } from "./workspace";
import { EXECUTION_ACTIONS } from "./execution";
import { WEB_ACTIONS } from "./web";
import { HOME_ACTIONS } from "./home";

export type {
  ActionFamily,
  CallSummary,
  ResultSummary,
  ActionDescriptor,
} from "./types";

const DESCRIPTORS = new Map<string, ActionDescriptor>(
  [
    ...CORE_ACTIONS,
    ...WORKSPACE_ACTIONS,
    ...EXECUTION_ACTIONS,
    ...WEB_ACTIONS,
    ...HOME_ACTIONS,
  ].map((descriptor) => [descriptor.action, descriptor]),
);

const genericCache = new Map<string, ActionDescriptor>();

function genericDescriptor(action: string): ActionDescriptor {
  let descriptor = genericCache.get(action);
  if (!descriptor) {
    descriptor = {
      action,
      verb: "Executing",
      family: "generic",
      summarizeCall: (params) => {
        const target = defaultTargetOf(action, params);
        const label = targetLabel(target);
        return { headline: label ? `执行 ${label}` : "执行", target };
      },
      summarizeResult: defaultResultSummary,
    };
    genericCache.set(action, descriptor);
  }
  return descriptor;
}

/** Presentation descriptor for an action, generic fallback when unknown. */
export function descriptorFor(action: string): ActionDescriptor {
  return DESCRIPTORS.get(action) ?? genericDescriptor(action);
}

/** Present-tense verb phrase for an action, used while it runs. */
export function actionVerb(action: string): string {
  return descriptorFor(action).verb;
}

/** Result summary for an action result, honoring descriptor overrides. */
export function resultSummaryFor(action: string, result: ActionResultView): ResultSummary {
  const descriptor = descriptorFor(action);
  return descriptor.summarizeResult?.(result) ?? defaultResultSummary(result);
}
