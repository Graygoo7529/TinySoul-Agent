/**
 * Session-organize, reflection-write and core-dialog result views.
 */

import { useI18n } from "../../../i18n";
import { Badge } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { asObject, asString, asStringArray } from "../model/facts";
import { DiffGlimpse } from "../../chat/live/ActivityGlimpse";
import { Markdown } from "../../../components/markdown/Markdown";
import type { ResultViewProps } from "../model/registry";
import {
  ReferenceButton,
  Excerpt,
  EmptyResult,
  GenericView,
} from "./resultShared";

// ---------------------------------------------------------------------------
// session organize / reflection writes / core dialog
// ---------------------------------------------------------------------------

export function SessionOrganizeView({ result, nav }: ResultViewProps) {
  const { t } = useI18n();
  if (result === null) return <EmptyResult />;
  const changed = asStringArray(result.changed_refs);
  const created = asObject(result.created_refs);
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-fg-faint">
        {t("trace.interpretationHint")}</div>
      {created !== null && Object.keys(created).length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.createdInterpretations")}</div>
          {Object.entries(created).map(([name, ref]) => (
            <div key={name} className="flex items-baseline gap-2">
              <span className="shrink-0 text-[11px] text-fg-faint">{name}</span>
              {typeof ref === "string" && (
                <ReferenceButton reference={ref} onOpen={nav.openReference} />
              )}
            </div>
          ))}
        </div>
      )}
      {changed.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.changedRefs")}</div>
          {changed.map((ref) => (
            <ReferenceButton key={ref} reference={ref} onOpen={nav.openReference} />
          ))}
        </div>
      )}
      {changed.length === 0 && (created === null || Object.keys(created).length === 0) && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

/** Home review/diff and Memory persistent writes (Reflection scope). */
export function ReflectionWriteView({ action, result, params, nav }: ResultViewProps) {
  const { t } = useI18n();
  if (result === null) return <EmptyResult />;
  const items = Array.isArray(result.items) ? result.items : null;
  const link = asString(result.ref);
  const markdown = params !== null ? asString(params.markdown) : null;
  return (
    <div className="space-y-2">
      {link !== null && (
        <div className="flex items-baseline gap-2">
          <span className="shrink-0 text-[11px] text-fg-faint">{t("trace.committed")}</span>
          <ReferenceButton reference={link} onOpen={nav.openReference} />
          {result.written === true && <Badge tone="green">{t("chat.written")}</Badge>}
        </div>
      )}
      {markdown !== null && markdown.trim() !== "" &&
        (action === "memory.write" || action === "memory.write_daily") && (
        <Collapsible title={t("trace.submittedContentChars", { count: markdown.length })} defaultOpen={markdown.length <= 1200}>
          <Markdown className="md-calm text-[12px]" origin={{ ref: "" }}>
            {markdown}
          </Markdown>
        </Collapsible>
      )}
      {items !== null && (
        <div className="space-y-1">
          {items.map((entry, index) => {
            const item = asObject(entry);
            if (item === null) return null;
            const itemLink = asString(item.ref);
            const decision = asString(item.decision);
            const reason = asString(item.reason);
            const kind = asString(item.kind);
            const before = asString(asObject(item.actual)?.text) ?? "";
            const after = asString(asObject(item.runtime)?.text) ?? "";
            const hasDiff = action === "home.diff" && before !== after;
            return (
              <div
                key={index}
                className="space-y-2 rounded-md border border-line/60 px-2.5 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1">
                    {itemLink !== null ? (
                      <ReferenceButton reference={itemLink} onOpen={nav.openReference} />
                    ) : (
                      <span className="text-[12px] text-fg-muted">{t("trace.item")}{index + 1}</span>
                    )}
                  </span>
                  {item.reviewed === true && <Badge tone="green">{t("trace.reviewed")}</Badge>}
                  {item.reviewed === false && (
                    <Badge tone="gray" title={reason ?? undefined}>
                      {t("trace.notReviewed")}{reason !== null ? `: ${reason}` : ""}
                    </Badge>
                  )}
                  {decision !== null && (
                    <Badge tone={decision === "accept" ? "green" : "yellow"}>
                      {decision}
                    </Badge>
                  )}
                  {kind !== null && <Badge tone="gray">{kind}</Badge>}
                </div>
                {hasDiff && <DiffGlimpse oldText={before} newText={after} />}
              </div>
            );
          })}
        </div>
      )}
      {link === null && items === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

/**
 * core.reason / core.answer / core.ask: the model-disclosed content and its
 * references. core.ask's interactive card lives in the conversation stream.
 */
export function CoreDialogView({ result, nav }: ResultViewProps) {
  const { t } = useI18n();
  if (result === null) return <EmptyResult />;
  const text = asString(result.text);
  const references = asStringArray(result.references);
  const options = Array.isArray(result.options) ? result.options : null;
  return (
    <div className="space-y-2">
      {options !== null && (
        <div className="text-[11px] text-fg-faint">
          {t("trace.questionHint")}</div>
      )}
      {text !== null && <Excerpt text={text} max={2000} />}
      {options !== null && (
        <div className="space-y-1">
          {options.map((entry, index) => {
            const option = asObject(entry);
            if (option === null) return null;
            return (
              <div
                key={index}
                className="rounded-md border border-line/60 px-2.5 py-1.5 text-[12px]"
              >
                <span className="font-medium">{asString(option.label) ?? "?"}</span>
                {asString(option.description) !== null && (
                  <span className="text-fg-faint"> — {asString(option.description)}</span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {references.length > 0 && (
        <div className="space-y-0.5">
          <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
            {t("trace.references")}</div>
          {references.map((reference) => (
            <ReferenceButton
              key={reference}
              reference={reference}
              onOpen={nav.openReference}
            />
          ))}
        </div>
      )}
      {text === null && options === null && (
        <GenericView result={result} params={null} nav={nav} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------