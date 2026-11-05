/**
 * Search, inspect and write result views.
 */

import { t, useI18n } from "../../../i18n";
import type { JsonObject } from "../../../api/v2/types";
import { Badge } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { JsonTree } from "../../../components/ui/JsonTree";
import { asNumber, asObject, asString, asStringArray } from "../model/facts";
import { DiffGlimpse } from "../../chat/live/ActivityGlimpse";
import type { ResultViewProps } from "../model/registry";
import { isSearchPage, SearchResultView } from "../panels/SearchResultView";
import {
  ReferenceButton,
  FactRow,
  FactGrid,
  Excerpt,
  EmptyResult,
  GenericView,
  readRangeLine,
  referenceFields,
} from "./resultShared";

// ---------------------------------------------------------------------------
// search / inspect / write
// ---------------------------------------------------------------------------

export function SearchFamilyView({ result, params, nav }: ResultViewProps) {
  if (result === null || !isSearchPage(result)) {
    return <GenericView result={result} params={params} nav={nav} />;
  }
  return (
    <SearchResultView
      result={result}
      params={params}
      onOpenReference={nav.openReference}
    />
  );
}

function ReadTextWithLines({
  text,
  requested,
  actual,
}: {
  text: string;
  requested: JsonObject | null;
  actual: JsonObject | null;
}) {
  const actualStart = actual !== null ? asObject(actual.start) : null;
  const actualLine = actualStart !== null ? asNumber(actualStart.line) : null;
  const requestedLine = requested !== null ? asNumber(requested.start_line) : null;
  const startLine = actualLine ?? requestedLine;
  if (startLine === null) return <Excerpt text={text} max={4000} />;
  const boundedText = text.length > 4000 ? `${text.slice(0, 4000)}…` : text;
  return (
    <div className="overflow-hidden rounded-md border border-line/60 bg-bg-sunken">
      {boundedText.split("\n").map((line, index) => (
        <div key={index} className="grid grid-cols-[2.75rem_1fr]">
          <span
            data-line-number={startLine + index}
            className="select-none border-r border-line/60 px-1.5 py-0.5 text-right font-mono text-[10px] leading-5 text-fg-faint"
          >
            {startLine + index}
          </span>
          <span className="whitespace-pre-wrap break-words px-2 py-0.5 font-mono text-[12px] leading-5 text-fg-muted">
            {line === "" ? "\u00a0" : line}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Inspect/read: DisclosurePage-style {ref, items}, workspace.read text
 * ranges, directory listings. Shows what was read; "open" goes to the
 * owner's current content, labelled as such.
 */
export function InspectView({ result, nav }: ResultViewProps) {
  const { t } = useI18n();
  if (result === null) return <EmptyResult />;
  const text = asString(result.text);
  const link = asString(result.ref);
  const items = Array.isArray(result.items) ? result.items : null;
  const resources = Array.isArray(result.resources) ? result.resources : null;
  const truncated = result.truncated === true;
  const complete = result.complete;
  const requested = asObject(result.requested);
  const actual = asObject(result.actual);
  // workspace.trash_list: every entry carries the trash ref + original link.
  const trashItems =
    items !== null &&
    items.length > 0 &&
    items.every((entry) => {
      const record = asObject(entry);
      return (
        record !== null &&
        asString(record.ref) !== null &&
        asString(record.target_ref) !== null
      );
    })
      ? items
      : null;
  return (
    <div className="space-y-2">
      {link !== null && (
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1">
            <ReferenceButton reference={link} onOpen={nav.openReference} />
          </span>
          {nav.openReference !== undefined && (
            <span className="shrink-0 text-[11px] text-fg-faint">
              {t("trace.currentContentHint")}
            </span>
          )}
        </div>
      )}
      {requested !== null && (
        <div className="text-[11px] text-fg-faint">
          {readRangeLine(requested, actual)}
        </div>
      )}
      {text !== null && (
        <Collapsible title={t("trace.readTextChars", { count: text.length })} defaultOpen={text.length <= 1200}>
          <ReadTextWithLines text={text} requested={requested} actual={actual} />
        </Collapsible>
      )}
      {truncated && (
        <div className="text-[11px] text-fg-faint">
          {t("trace.boundedRead")}</div>
      )}
      {complete === false && (
        <div className="text-[11px] text-warning">{t("trace.partialRead")}</div>
      )}
      {trashItems !== null && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.trashItems")} ({trashItems.length}
            {asNumber(result.total) !== null &&
            asNumber(result.total) !== trashItems.length
              ? t("trace.ofTotal", { total: asNumber(result.total) ?? 0 })
              : ""}
            )
          </div>
          {trashItems.slice(0, 24).map((entry, index) => {
            const record = asObject(entry);
            if (record === null) return null;
            const itemLink = asString(record.target_ref);
            const itemRef = asString(record.ref);
            const tags = asStringArray(record.tags);
            return (
              <div key={index} className="flex items-center gap-1.5">
                <span className="min-w-0 flex-1">
                  {itemLink !== null ? (
                    <ReferenceButton
                      reference={itemLink}
                      onOpen={nav.openReference}
                    />
                  ) : null}
                </span>
                {tags.map((tag) => (
                  <Badge key={tag} tone="gray">
                    {tag}
                  </Badge>
                ))}
                {itemRef !== null && (
                  <span
                    className="shrink-0 font-mono text-[10px] text-fg-faint"
                    title={itemRef}
                  >
                    {itemRef}
                  </span>
                )}
              </div>
            );
          })}
          {trashItems.length > 24 && (
            <div className="text-[11px] text-fg-faint">
              … {trashItems.length - 24} {t("trace.moreTrash")}</div>
          )}
        </div>
      )}
      {resources !== null && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.directory")} ({resources.length}
            {asNumber(result.total) !== null && asNumber(result.total) !== resources.length
              ? t("trace.ofTotal", { total: asNumber(result.total) ?? 0 })
              : ""}
            )
          </div>
          {resources.slice(0, 24).map((entry, index) => {
            const record = asObject(entry);
            const entryLink =
              record !== null
                ? (asString(record.ref) ?? asString(record.ref))
                : null;
            return entryLink !== null ? (
              <ReferenceButton
                key={index}
                reference={entryLink}
                onOpen={nav.openReference}
              />
            ) : null;
          })}
        </div>
      )}
      {items !== null && text === null && trashItems === null && (
        <Collapsible title={t("trace.pageItems", { count: items.length })} defaultOpen={items.length <= 8}>
          <JsonTree value={items} defaultExpanded={false} />
        </Collapsible>
      )}
      {text === null && items === null && resources === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

/**
 * Workspace/Home/Memory writes: the operation, its target and the settled
 * links. Without recorded before/after there is no diff — the view shows the
 * operation and locator only; opening shows the owner's current content.
 */
export function WriteView({ result, params, nav }: ResultViewProps) {
  useI18n();
  if (result === null) return <EmptyResult />;
  const operation = asString(result.operation) ?? asString(result.action);
  const links = referenceFields(result);
  // When the call carried before/after text, show the recorded diff — the
  // detail view is never weaker than the gist.
  const patches =
    params !== null && Array.isArray(params.edits)
      ? params.edits.map(asObject).filter((entry) => entry !== null)
      : params !== null && asString(params.old_text) !== null
        ? [params]
        : [];
  const instruction = params !== null ? asString(params.instruction) : null;
  // write/append carry full content rather than patches: show target + preview.
  const writeText = params !== null ? asString(params.text) : null;
  const targetRef =
    params !== null
      ? (asString(params.target_ref) ?? asString(params.ref))
      : null;
  const sourceRef = params !== null ? asString(params.source_ref) : null;
  const trashRef = params !== null ? asString(params.trash_ref) : null;
  const tags = params !== null ? asStringArray(params.tags) : [];
  const memorizeOps =
    params !== null && Array.isArray(params.operations)
      ? params.operations.map(asObject).filter((entry) => entry !== null)
      : [];
  const hasPlanZone =
    patches.length > 0 ||
    instruction !== null ||
    writeText !== null ||
    targetRef !== null ||
    memorizeOps.length > 0;
  return (
    <div className="space-y-2">
      {hasPlanZone && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-accent">
            {t("trace.planningInput")}</div>
          {instruction !== null && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
              <dt className="text-fg-faint">{t("trace.instruction")}</dt>
              <dd className="min-w-0 break-words text-fg-muted">{instruction}</dd>
            </dl>
          )}
          {(targetRef !== null || sourceRef !== null || trashRef !== null) && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
              {sourceRef !== null && (
                <>
                  <dt className="text-fg-faint">{t("trace.source")}</dt>
                  <dd className="min-w-0 break-words font-mono text-[11px] text-fg-muted">{sourceRef}</dd>
                </>
              )}
              {targetRef !== null && (
                <>
                  <dt className="text-fg-faint">{t("trace.target")}</dt>
                  <dd className="min-w-0 break-words font-mono text-[11px] text-fg-muted">{targetRef}</dd>
                </>
              )}
              {trashRef !== null && (
                <>
                  <dt className="text-fg-faint">{t("trace.trash")}</dt>
                  <dd className="min-w-0 break-words font-mono text-[11px] text-fg-muted">{trashRef}</dd>
                </>
              )}
            </dl>
          )}
          {tags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {tags.map((tag) => (
                <span key={tag} className="rounded bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                  {tag}
                </span>
              ))}
            </div>
          )}
          {patches.length > 0 && (
            <div className="mt-1 space-y-1">
              {patches.map((patch, index) => (
                <DiffGlimpse
                  key={index}
                  oldText={asString(patch.old_text) ?? ""}
                  newText={asString(patch.new_text) ?? ""}
                />
              ))}
            </div>
          )}
          {writeText !== null && (
            <div className="mt-1">
              <div className="mb-0.5 text-[10px] text-fg-faint">
                {t("trace.writtenCharacters", { count: writeText.length })}
              </div>
              <Excerpt text={writeText} max={600} />
            </div>
          )}
          {memorizeOps.length > 0 && (
            <div className="mt-1 space-y-1">
              {memorizeOps.map((op, index) => {
                const kind = asString(op.kind) ?? "?";
                const oldText = asString(op.old_text);
                const newText = asString(op.new_text) ?? asString(op.text);
                return (
                  <div key={index} className="flex items-start gap-2 text-[11.5px]">
                    <span className="mt-px rounded bg-hover px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                      {kind}
                    </span>
                    {oldText !== null && newText !== null ? (
                      <span className="min-w-0 flex-1">
                        <DiffGlimpse oldText={oldText} newText={newText} />
                      </span>
                    ) : (
                      <span className="min-w-0 flex-1 break-words text-fg-muted">
                        {newText ?? ""}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      <div className={hasPlanZone ? "border-t border-line/60 pt-2" : ""}>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-success">
          {t("trace.executionResult")}</div>
        <FactGrid>
          {operation !== null && <FactRow label={t("trace.operation")} value={operation} />}
          {result.written === true && <FactRow label={t("chat.written")} value="yes" />}
          {asNumber(result.chars) !== null && (
            <FactRow label={t("home.chars")} value={asNumber(result.chars)} />
          )}
          {result.changed === true && <FactRow label={t("trace.changed")} value="yes" />}
          {result.cleared === true && <FactRow label={t("trace.cleared")} value="yes" />}
        </FactGrid>
      </div>
      {links.length > 0 ? (
        <div className="space-y-1">
          {links.map(({ key, value }) => (
            <div key={key} className="flex items-baseline gap-2">
              <span className="shrink-0 text-[11px] text-fg-faint">{key}</span>
              <ReferenceButton reference={value} onOpen={nav.openReference} />
            </div>
          ))}
          <div className="text-[11px] text-fg-faint">
            {t("trace.noDiff")}</div>
        </div>
      ) : (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------