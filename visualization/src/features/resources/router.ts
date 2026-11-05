import { message, type UiText } from "../../i18n/core";
/**
 * ResourceRouter (plan §21.2).
 *
 * One entry point turns a reference plus its reading origin into a page
 * navigation. References that already carry a formal locator (a resolve
 * response, a Context/Session binding) route directly; relative references,
 * dynamic Memory references and origin-bound identities go through API-18.
 * A dynamic reference without a recorded binding is an explicit dead end —
 * it never silently becomes today's latest.
 *
 * The three operations stay distinct everywhere a reference surfaces:
 * follow (open), copy the original reference, and "quote in conversation"
 * (an editable Composer draft that keeps the source day/view/turn; it never
 * sends itself and never attaches content).
 */

import type { ResourceLocator, ResourceResolve } from "../../api/v2/types";
import { hasApiCode } from "../../api/v2/errors";
import type { V2Clients } from "../../api/v2/clients";
import { useAppStore } from "../../store/appStore";
import {
  selectActiveDay,
  selectActiveTurnId,
  useConnectionStore,
} from "../../store/connectionStore";
import { isTauriShell } from "../../app/discovery";
import { useComposerDraft } from "../chat/composer/composerDraft";
import {
  backToLiveTurn,
  openHistoryConversation,
  pushSessionRef,
} from "../history/entries";
import { pushContextInspect } from "../context/entries";
import { useWorkspacePage } from "../workspace/store";
import {
  classifyReference,
  splitFragment,
  traceTurnId,
  type ResourceOrigin,
} from "./reference";
import { useResourceTargets } from "./targetsStore";

/** Where a resolved reference leads. */
export type RouteTarget =
  | { kind: "workspace"; ref: string; day: string | null; fragment: string | null }
  | { kind: "home"; ref: string; view: string; fragment: string | null }
  | { kind: "memory"; ref: string; day: string | null; fragment: string | null }
  | { kind: "session"; ref: string; day: string }
  | { kind: "trace"; ref: string; turnId: string | null; day: string | null }
  | { kind: "external"; url: string };

export interface ResolvedReference {
  /** The reference as the user saw it (fragment included). */
  reference: string;
  kind: RouteTarget["kind"];
  locator: ResourceLocator;
  target: RouteTarget;
}

export type ResolveOutcome =
  | { status: "resolved"; value: ResolvedReference }
  | {
      /** A dynamic Memory reference without its recorded binding. */
      status: "unbound";
      reference: string;
      detail: UiText;
    }
  | { status: "failed"; reference: string; detail: UiText };

export interface ResolveOptions {
  /** An already-resolved locator (Context/Session binding); skips API-18. */
  locator?: ResourceLocator;
}

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

/**
 * Resolve one reference against its origin into a routable target. Pure with
 * respect to UI: the outcome describes where the reference leads; routing it
 * is a separate step.
 */
export async function resolveReference(
  clients: V2Clients,
  reference: string,
  origin: ResourceOrigin = {},
  options: ResolveOptions = {},
): Promise<ResolveOutcome> {
  const kind = classifyReference(reference);
  if (kind === "external") {
    return resolved(reference, { ref: reference }, { kind: "external", url: reference });
  }
  if (kind === "other") {
    return {
      status: "failed",
      reference,
      detail: message("resources.notReference"),
    };
  }
  if (options.locator !== undefined) {
    return fromLocator(reference, options.locator);
  }
  if (kind === "relative" && !origin.ref) {
    return {
      status: "failed",
      reference,
      detail: message("resources.relativeOrigin"),
    };
  }
  if (needsBackendResolve(kind, origin)) {
    return resolveViaBackend(clients, reference, origin);
  }
  return resolveLocally(reference, kind, origin);
}

/** True when the local origin facts are not enough and API-18 must decide. */
function needsBackendResolve(
  kind: ReturnType<typeof classifyReference>,
  origin: ResourceOrigin,
): boolean {
  switch (kind) {
    case "relative":
    case "memory-dynamic":
      return true;
    case "workspace":
      // A Turn-bound reference takes the Turn's day; only the backend binds it.
      return origin.day === undefined && origin.turnId !== undefined;
    case "session":
      return origin.day === undefined;
    case "home":
    case "memory":
    case "trace":
      return false;
    default:
      return false;
  }
}

function resolveLocally(
  reference: string,
  kind: ReturnType<typeof classifyReference>,
  origin: ResourceOrigin,
): ResolveOutcome {
  const { resource, fragment } = splitFragment(reference);
  switch (kind) {
    case "workspace": {
      const day = origin.day ?? null;
      return resolved(
        reference,
        { ref: resource, day },
        { kind: "workspace", ref: resource, day, fragment },
      );
    }
    case "home": {
      const view = origin.homeView ?? "effective";
      return resolved(
        reference,
        { ref: resource, view },
        { kind: "home", ref: resource, view, fragment },
      );
    }
    case "memory":
      return resolved(
        reference,
        { ref: resource },
        { kind: "memory", ref: resource, day: origin.day ?? null, fragment },
      );
    case "session":
      // needsBackendResolve guarantees a day here.
      return resolved(
        reference,
        { ref: reference, day: origin.day ?? null },
        { kind: "session", ref: reference, day: origin.day! },
      );
    case "trace":
      return resolved(
        reference,
        { ref: reference, turn_id: traceTurnId(reference), day: origin.day ?? null },
        {
          kind: "trace",
          ref: reference,
          turnId: traceTurnId(reference),
          day: origin.day ?? null,
        },
      );
    default:
      return {
        status: "failed",
        reference,
        detail: message("resources.unroutable"),
      };
  }
}

async function resolveViaBackend(
  clients: V2Clients,
  reference: string,
  origin: ResourceOrigin,
): Promise<ResolveOutcome> {
  let response: ResourceResolve;
  try {
    response = await clients.resources.resolve({
      ref: reference,
      origin_ref: origin.ref,
      day: origin.day,
      turn_id: origin.turnId,
      view: origin.homeView,
    });
  } catch (error) {
    if (hasApiCode(error, "resource.unresolved_origin")) {
      return {
        status: "unbound",
        reference,
        detail:
          message("resources.unbound"),
      };
    }
    return {
      status: "failed",
      reference,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
  return fromLocator(reference, response.locator);
}

/** Build the routable target from a formal locator (ref may carry #fragment). */
function fromLocator(reference: string, locator: ResourceLocator): ResolveOutcome {
  const ref = locator.ref;
  const day = typeof locator.day === "string" && locator.day !== "" ? locator.day : null;
  const turnId = typeof locator.turn_id === "string" ? locator.turn_id : null;
  const view = typeof locator.view === "string" ? locator.view : null;
  const source = ref;
  if (source === null) {
    return {
      status: "failed",
      reference,
      detail: message("resources.missingReference"),
    };
  }
  const { resource, fragment } = splitFragment(source);
  if (resource.startsWith("workspace:")) {
    return resolved(
      reference,
      { ...locator, ref: resource },
      { kind: "workspace", ref: resource, day, fragment },
    );
  }
  if (resource.startsWith("home:")) {
    return resolved(
      reference,
      { ...locator, ref: resource },
      { kind: "home", ref: resource, view: view ?? "effective", fragment },
    );
  }
  if (resource.startsWith("memory:")) {
    return resolved(
      reference,
      { ...locator, ref: resource },
      { kind: "memory", ref: resource, day, fragment },
    );
  }
  if (resource.startsWith("session:")) {
    if (day === null) {
      return {
        status: "unbound",
        reference,
        detail: message("resources.sessionDayMissing"),
      };
    }
    return resolved(
      reference,
      { ...locator, ref: source },
      { kind: "session", ref: source, day },
    );
  }
  if (resource.startsWith("turn:trace/")) {
    return resolved(
      reference,
      { ...locator, ref: source },
      { kind: "trace", ref: source, turnId: turnId ?? traceTurnId(resource), day },
    );
  }
  return {
    status: "failed",
    reference,
    detail: message("resources.ownerUnroutable", { resource }),
  };
}

function resolved(
  reference: string,
  locator: ResourceLocator,
  target: RouteTarget,
): ResolveOutcome {
  return { status: "resolved", value: { reference, kind: target.kind, locator, target } };
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

/**
 * Navigate to a resolved target. Workspace opens the real page; Home/Memory
 * record a pending target their F5-B pages consume; Session refs drill into
 * the history inspector; a Trace ref opens the live or retained record of
 * its Turn; web links leave the app.
 */
export function routeTarget(epoch: number, target: RouteTarget): void {
  const app = useAppStore.getState();
  switch (target.kind) {
    case "workspace":
      useWorkspacePage.getState().openFile({
        ref: target.ref,
        day: target.day,
        fragment: target.fragment,
      });
      app.setActiveTab("workspace");
      return;
    case "home":
      useResourceTargets.getState().openHome({
        ref: target.ref,
        view: target.view === "actual" ? "actual" : "effective",
        fragment: target.fragment,
      });
      app.setActiveTab("home");
      return;
    case "memory":
      useResourceTargets.getState().openMemory({
        ref: target.ref,
        day: target.day,
        fragment: target.fragment,
      });
      app.setActiveTab("memory");
      return;
    case "session":
      pushSessionRef(epoch, target.day, target.ref);
      return;
    case "trace": {
      const state = useConnectionStore.getState();
      const activeTurn = selectActiveTurnId(state);
      if (target.turnId !== null && target.turnId === activeTurn) {
        backToLiveTurn(epoch);
        pushContextInspect(epoch, target.turnId, target.ref, { canQuery: true });
        return;
      }
      if (target.turnId !== null && target.day !== null) {
        openHistoryConversation(epoch, target.turnId, target.day);
        return;
      }
      app.pushToast(
        "info",
        message("resources.traceClosed"),
      );
      return;
    }
    case "external":
      openExternal(target.url);
      return;
  }
}

/** Resolve and follow one reference; failures surface as toasts. */
export async function openReference(
  epoch: number,
  reference: string,
  origin: ResourceOrigin = {},
  options: ResolveOptions = {},
): Promise<ResolveOutcome> {
  const app = useAppStore.getState();
  const clients = useConnectionStore.getState().clients;
  if (clients === null) {
    const detail = message("resources.notConnected");
    app.pushToast("error", detail);
    return { status: "failed", reference, detail };
  }
  const outcome = await resolveReference(clients, reference, origin, options);
  if (outcome.status === "resolved") {
    routeTarget(epoch, outcome.value.target);
    return outcome;
  }
  app.pushToast(
    outcome.status === "unbound" ? "info" : "error",
    outcome.detail,
  );
  return outcome;
}

/** Open a web ref: the system browser under Tauri, a new tab in Browser. */
export function openExternal(url: string): void {
  if (isTauriShell()) {
    void import("@tauri-apps/plugin-opener")
      .then((plugin) => plugin.openUrl(url))
      .catch(() => window.open(url, "_blank", "noopener,noreferrer"));
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

/** Copy the original reference text (no resolution, no rewrite). */
export function copyReference(reference: string): void {
  const write = navigator.clipboard?.writeText(reference);
  if (write) {
    void write.then(
      () => useAppStore.getState().pushToast("success", message("resources.referenceCopied")),
      () => useAppStore.getState().pushToast("error", message("resources.copyFailed")),
    );
  }
}

// ---------------------------------------------------------------------------
// Quote in conversation
// ---------------------------------------------------------------------------

/**
 * Place an editable quote draft into the Composer and switch to the chat
 * tab. The draft keeps the original reference plus the source facts needed
 * to recognise the resource (archived day, Home view, Turn day, or the
 * binding a dynamic reference resolved to). It never sends and never
 * attaches content.
 */
export function quoteReference(
  reference: string,
  origin: ResourceOrigin = {},
  resolvedValue?: ResolvedReference,
): void {
  useComposerDraft.getState().setDraft(buildQuoteText(reference, origin, resolvedValue));
  useAppStore.getState().setActiveTab("chat");
}

export function buildQuoteText(
  reference: string,
  origin: ResourceOrigin = {},
  resolvedValue?: ResolvedReference,
): string {
  const source = describeSource(reference, origin, resolvedValue);
  return source === null
    ? `Please refer to ${reference}.`
    : `Please refer to ${reference} (${source}).`;
}

function describeSource(
  reference: string,
  origin: ResourceOrigin,
  resolvedValue?: ResolvedReference,
): string | null {
  const target = resolvedValue?.target;
  const day = (target && "day" in target ? target.day : null) ?? origin.day ?? null;
  switch (target?.kind ?? classifyQuoteKind(reference, origin)) {
    case "workspace": {
      if (day === null) return null;
      const active = selectActiveDay(useConnectionStore.getState());
      return day === active
        ? `from today's workspace`
        : `from the archived workspace of ${day}`;
    }
    case "home": {
      const view =
        target?.kind === "home" ? target.view : (origin.homeView ?? "effective");
      return `from Home, ${view} view`;
    }
    case "memory": {
      if (resolvedValue !== undefined && resolvedValue.locator.ref) {
        const bound = String(resolvedValue.locator.ref);
        if (bound !== reference) {
          return day !== null ? `bound to ${bound}, ${day}` : `bound to ${bound}`;
        }
      }
      return day !== null ? `from ${day}` : null;
    }
    case "session":
      return day !== null ? `from the conversation record of ${day}` : null;
    case "trace":
      return day !== null ? `from the run of ${day}` : null;
    default:
      return day !== null ? `from ${day}` : null;
  }
}

function classifyQuoteKind(
  reference: string,
  origin: ResourceOrigin,
): RouteTarget["kind"] | null {
  // The quoted reference is authoritative; the origin ref is the fallback
  // (e.g. a relative reference quoted from inside a workspace document).
  for (const candidate of [reference, origin.ref]) {
    if (candidate === undefined) continue;
    const kind = classifyReference(candidate);
    switch (kind) {
      case "workspace":
      case "home":
      case "memory":
      case "session":
      case "trace":
        return kind;
      case "memory-dynamic":
        return "memory";
      default:
        continue;
    }
  }
  return null;
}
