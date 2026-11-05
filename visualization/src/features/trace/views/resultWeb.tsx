/**
 * Web result views (search/fetch/discover).
 */

import { t, useI18n } from "../../../i18n";
import { ExternalLink } from "lucide-react";
import { Badge } from "../../../components/ui/Badge";
import { asString, asStringArray } from "../model/facts";
import {
  type WebDiscoveryResult,
  type WebFetchResult,
  type WebSearchResult,
  webPageStateLabel,
  webPageStateTone,
  webResult,
} from "../model/webModel";
import { openExternal } from "../../resources/router";
import type { ResultViewProps } from "../model/registry";
import {
  ReferenceButton,
  Excerpt,
  LinksBlock,
  EmptyResult,
  GenericView,
} from "./resultShared";

// ---------------------------------------------------------------------------
// web
// ---------------------------------------------------------------------------

export function WebView({ action, result, params, nav }: ResultViewProps) {
  useI18n();
  if (result === null) return <EmptyResult />;
  const model = webResult(action, result);
  if (model === null) return <GenericView result={result} params={params} nav={nav} />;
  const warningCodes = asStringArray(result.warning_codes);
  return (
    <div className="space-y-2">
      {model.kind === "search" && <WebSearchDetails model={model} />}
      {model.kind === "fetch" && (
        <WebFetchDetails
          model={model}
          sourceUrl={params !== null ? asString(params.url) : null}
        />
      )}
      {model.kind === "discover" && <WebDiscoveryDetails model={model} />}
      {warningCodes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {warningCodes.map((code) => (
            <Badge key={code} tone="yellow">
              {code}
            </Badge>
          ))}
        </div>
      )}
      {result.untrusted_external_content === true && (
        <div className="text-[11px] text-fg-faint">
          {t("trace.externalContent")}</div>
      )}
      <LinksBlock payload={result} onOpen={nav.openReference} title={t("trace.producedResources")} />
      {result.truncated === true && asString(result.see_more_at) !== null && (
        <ReferenceButton
          reference={asString(result.see_more_at)!}
          label={t("trace.fullResultAt", { ref: asString(result.see_more_at) ?? "" })}
          onOpen={nav.openReference}
        />
      )}
    </div>
  );
}

function WebSearchDetails({ model }: { model: WebSearchResult }) {
  const { t } = useI18n();
  const resultCount =
    model.resultCount !== null && model.resultCount !== model.sources.length
      ? ` / ${model.resultCount}`
      : "";
  return (
    <div className="space-y-2">
      {model.answer !== null && model.answer !== "" && (
        <Excerpt text={model.answer} max={1200} />
      )}
      {model.sources.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium text-fg-faint">
            {t("trace.sourceCount", { count: `${model.sources.length}${resultCount}` })}
          </div>
          {model.sources.slice(0, 12).map((source, index) => {
            const title = source.title ?? source.url;
            if (title === null) return null;
            return (
              <div key={source.url ?? index} className="rounded-lg border border-line/60 bg-bg-elev px-2.5 py-1.5">
                <ExternalTitleLink url={source.url} title={title} />
                {source.snippet !== null && source.snippet !== "" && (
                  <div className="mt-0.5 line-clamp-2 text-[11px] leading-4.5 text-fg-muted">
                    {source.snippet}
                  </div>
                )}
                {source.url !== null && (
                  <div className="mt-0.5 truncate font-mono text-[10px] text-fg-faint" title={source.url}>
                    {source.url}
                  </div>
                )}
              </div>
            );
          })}
          {model.sources.length > 12 && (
            <div className="text-[11px] text-fg-faint">
              … {model.sources.length - 12} {t("trace.moreSources")}</div>
          )}
        </div>
      )}
    </div>
  );
}

function WebFetchDetails({ model, sourceUrl }: { model: WebFetchResult; sourceUrl: string | null }) {
  useI18n();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {model.extractor !== null && <Badge tone="teal">{model.extractor}</Badge>}
        {model.contentChars !== null && (
          <span className="text-[11px] text-fg-faint">
            {t("trace.body")}{model.contentChars.toLocaleString()} {t("home.chars")}</span>
        )}
      </div>
      {model.title !== null && model.title !== "" && (
        <div className="text-[13px] font-medium text-fg">{model.title}</div>
      )}
      {model.excerpt !== null && model.excerpt !== "" && (
        <Excerpt text={model.excerpt} />
      )}
      {sourceUrl !== null && (
        <button
          type="button"
          onClick={() => openExternal(sourceUrl)}
          className="flex max-w-full items-center gap-1 text-left text-[11px] text-accent hover:underline"
          title={sourceUrl}
        >
          <ExternalLink size={11} className="shrink-0" />
          <span className="truncate">{t("trace.originalPage")}</span>
        </button>
      )}
    </div>
  );
}

function WebDiscoveryDetails({ model }: { model: WebDiscoveryResult }) {
  const { t } = useI18n();
  const metrics = [
    model.pageCount !== null ? t("trace.pageCount", { count: model.pageCount }) : null,
    model.visitedCount !== null ? t("trace.visitedCount", { count: model.visitedCount }) : null,
    model.failedCount !== null && model.failedCount > 0 ? t("trace.failedCount", { count: model.failedCount }) : null,
    model.candidateCount !== null ? t("trace.candidateCount", { count: model.candidateCount }) : null,
    model.skippedCount !== null && model.skippedCount > 0 ? t("trace.skippedCount", { count: model.skippedCount }) : null,
    model.stopReason !== null ? t("trace.stopReason", { reason: model.stopReason }) : null,
  ].filter((value): value is string => value !== null);
  return (
    <div className="space-y-2">
      <div>
        {(model.sourceTitle !== null && model.sourceTitle !== "") || model.sourceUrl !== null ? (
          <>
            <div className="text-[13px] font-medium text-fg">
              {model.sourceTitle || model.sourceUrl}
            </div>
            {model.sourceUrl !== null && (
              <button
                type="button"
                onClick={() => openExternal(model.sourceUrl!)}
                className="mt-0.5 flex max-w-full items-center gap-1 text-left font-mono text-[11px] text-accent hover:underline"
                title={model.sourceUrl}
              >
                <ExternalLink size={11} className="shrink-0" />
                <span className="truncate">{model.sourceUrl}</span>
              </button>
            )}
          </>
        ) : null}
      </div>
      {metrics.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-faint">
          {metrics.map((metric) => <span key={metric}>{metric}</span>)}
        </div>
      )}
      {model.pages.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] font-medium text-fg-faint">
            {t("trace.pageCount", { count: model.pages.length })}
          </div>
          {model.pages.slice(0, 24).map((page, index) => {
            if (page.title === null) return null;
            return (
              <div key={page.url ?? index} className="flex items-start gap-2 rounded-lg border border-line/60 bg-bg-elev px-2.5 py-1.5">
                <Badge tone={webPageStateTone(page.state)}>
                  {webPageStateLabel(page.state)}
                </Badge>
                <div className="min-w-0 flex-1">
                  <ExternalTitleLink url={page.url} title={page.title} />
                  {page.url !== null && (
                    <div className="mt-0.5 truncate font-mono text-[10px] text-fg-faint" title={page.url}>
                      {page.url}
                    </div>
                  )}
                  {page.state === "failed" && page.failureReason !== null && (
                    <div className="mt-0.5 text-[11px] text-danger/80">
                      {page.failureReason}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          {model.pages.length > 24 && (
            <div className="text-[11px] text-fg-faint">
              … {model.pages.length - 24} {t("trace.morePages")}</div>
          )}
        </div>
      )}
    </div>
  );
}

function ExternalTitleLink({ url, title }: { url: string | null; title: string }) {
  if (url === null) return <span className="text-[12px] text-fg-muted">{title}</span>;
  return (
    <button
      type="button"
      onClick={() => openExternal(url)}
      className="flex max-w-full items-center gap-1 text-left text-[12px] text-accent hover:underline"
      title={url}
    >
      <ExternalLink size={11} className="shrink-0" />
      <span className="truncate">{title}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------