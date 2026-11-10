/**
 * Analysis result views (analyze/describe/compose/convert).
 */

import { t, useI18n } from "../../../i18n";
import { Badge } from "../../../components/ui/Badge";
import { Collapsible } from "../../../components/ui/Collapsible";
import { asNumber, asObject, asString, asStringArray } from "../model/facts";
import { Markdown } from "../../../components/markdown/Markdown";
import { analysisNarrative } from "../model/analysisModel";
import type { ResultViewProps } from "../model/registry";
import {
  ReferenceButton,
  FactRow,
  FactGrid,
  LinksBlock,
  EmptyResult,
  analysisCoverageLine,
} from "./resultShared";

// ---------------------------------------------------------------------------
// analysis (analyze / describe / compose / convert)
// ---------------------------------------------------------------------------

export function AnalysisView({ action, result, params, nav }: ResultViewProps) {
  useI18n();
  if (result === null) return <EmptyResult />;
  const narrative = analysisNarrative(action, result);
  const intent =
    asString(result.intent) ??
    asString(result.instruction) ??
    (params !== null
      ? (asString(params.intent) ?? asString(params.instruction))
      : null);
  const targetRef = params !== null ? asString(params.target_ref) : null;
  const sourceRef = params !== null ? asString(params.source_ref) : null;
  const requestedRefs = params !== null ? asStringArray(params.references) : [];
  const sources = Array.isArray(result.sources) ? result.sources : [];
  const converter = asString(result.converter);
  const visualRefs = asStringArray(result.visual_refs);
  const warningCodes = asStringArray(result.warning_codes);
  const coverage = asObject(result.coverage);
  const coverageLine = coverage !== null ? analysisCoverageLine(coverage) : null;
  const hasPlanZone =
    intent !== null ||
    targetRef !== null ||
    sourceRef !== null ||
    requestedRefs.length > 0;
  return (
    <div className="space-y-2">
      {hasPlanZone && (
        <div>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-accent">
            {t("trace.planningInput")}</div>
          {intent !== null && (
            <div className="mb-1.5 text-[12px] leading-5 text-fg-muted">{intent}</div>
          )}
          {(sourceRef !== null || targetRef !== null) && (
            <FactGrid>
              {sourceRef !== null && <FactRow label={t("trace.source")} value={sourceRef} />}
              {targetRef !== null && <FactRow label={t("trace.target")} value={targetRef} />}
            </FactGrid>
          )}
          {requestedRefs.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {requestedRefs.map((link) => (
                <span key={link} className="max-w-full rounded-md bg-accent-soft/50 px-1.5 py-0.5">
                  <ReferenceButton reference={link} onOpen={nav.openReference} />
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      <div className={hasPlanZone ? "border-t border-line/60 pt-2" : ""}>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-success">
          {t("trace.executionResult")}</div>
        <div className="space-y-2">
          {narrative?.kind === "report" && (
            <Collapsible
              title={t("trace.analysisReportChars", { count: narrative.text.length })}
              defaultOpen={narrative.text.length <= 3000}
              className="border-accent/20"
            >
              <Markdown density="compact" origin={{ ref: "" }}>
                {narrative.text}
              </Markdown>
            </Collapsible>
          )}
          {narrative?.kind === "description" && (
            <Collapsible
              title={t("trace.resourceDescriptionChars", { count: narrative.text.length })}
              defaultOpen={narrative.text.length <= 1500}
              className="border-accent/20"
            >
              <div className="whitespace-pre-wrap text-[12px] leading-5 text-fg-muted">
                {narrative.text}
              </div>
            </Collapsible>
          )}
          {(converter !== null ||
            asString(result.content_status) !== null ||
            asNumber(result.generated_resource_count) !== null) && (
            <FactGrid>
              {converter !== null && <FactRow label={t("trace.converter")} value={converter} />}
              {asString(result.content_status) !== null && (
                <FactRow label={t("trace.content")} value={asString(result.content_status)} />
              )}
              {asNumber(result.generated_resource_count) !== null && (
                <FactRow
                  label={t("trace.generated")}
                  value={t("trace.resourceCount", { count: asNumber(result.generated_resource_count) ?? 0 })}
                />
              )}
            </FactGrid>
          )}
          {(coverageLine !== null || narrative !== null) && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-faint">
              {coverageLine !== null && <span>{coverageLine}</span>}
              {narrative !== null && <span>{narrative.text.length} {t("home.chars")}</span>}
            </div>
          )}
          {sources.length > 0 && (
            <div className="space-y-0.5">
              <div className="text-[11px] font-medium text-fg-faint">
                {t("trace.reportReferences", { count: sources.length })}
              </div>
              {sources.map((entry, index) => {
                const object = asObject(entry);
                const link = object !== null ? asString(object.ref) : null;
                return link !== null ? (
                  <ReferenceButton key={index} reference={link} onOpen={nav.openReference} />
                ) : null;
              })}
            </div>
          )}
          <LinksBlock payload={result} onOpen={nav.openReference} title={t("trace.outputResources")} />
          {visualRefs.length > 0 && (
            <div className="space-y-0.5">
              <div className="text-[11px] font-medium tracking-wide text-fg-faint uppercase">
                {t("trace.visualReferences")}</div>
              {visualRefs.map((link) => (
                <ReferenceButton key={link} reference={link} onOpen={nav.openReference} />
              ))}
            </div>
          )}
          {warningCodes.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {warningCodes.map((code) => (
                <Badge key={code} tone="yellow">
                  {code}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------