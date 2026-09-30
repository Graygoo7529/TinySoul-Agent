/**
 * Web & Resource Fetching settings (config-coverage §4.3/§4.4). The external
 * Web search/fetch providers are configured here; the internal Search
 * pipelines live under Behavior → Search Policies.
 */

import { FieldSection, SettingsPageBody } from "./controls";

/** kimi-k2.5/k2.6 are the only models the backend accepts (catalog has no choices). */
const KIMI_MODEL_CHOICES = [
  { value: "kimi-k2.6", label: "kimi-k2.6 (default)" },
  { value: "kimi-k2.5", label: "kimi-k2.5" },
];

export function WebPage() {
  return (
    <SettingsPageBody>
      <div className="rounded-lg border border-line bg-bg-elev px-3.5 py-2.5 text-[12px] leading-5 text-fg-muted">
        This page configures the external web search, page discovery and
        fetching providers. The internal Search pipelines (query/backlinks/
        directory, select/rerank/filter) are edited under{" "}
        <span className="font-medium text-fg">Behavior → Search Policies</span>.
      </div>
      <FieldSection
        title="Kimi Web Search"
        description="Tool-assisted web search through the Kimi provider."
        paths={[
          "capabilities.web.search_by_kimi.enabled",
          "capabilities.web.search_by_kimi.base_url",
          "capabilities.web.search_by_kimi.api_key_env",
          "capabilities.web.search_by_kimi.model",
          "capabilities.web.search_by_kimi.max_query_chars",
          "capabilities.web.search_by_kimi.max_result_chars",
          "capabilities.web.search_by_kimi.max_inline_chars",
          "capabilities.web.search_by_kimi.max_tool_rounds",
          "capabilities.web.search_by_kimi.max_search_tokens",
          "capabilities.web.search_by_kimi.max_output_tokens",
        ]}
        overrides={{
          "capabilities.web.search_by_kimi.model": {
            choices: KIMI_MODEL_CHOICES,
          },
          "capabilities.web.search_by_kimi.max_tool_rounds": { min: 1 },
        }}
      />
      <FieldSection
        title="Page Discovery"
        description="Bounded crawling that discovers pages from seed links."
        paths={[
          "capabilities.web.discover_pages.enabled",
          "capabilities.web.discover_pages.max_visit_depth",
          "capabilities.web.discover_pages.max_pages",
          "capabilities.web.discover_pages.max_candidates",
          "capabilities.web.discover_pages.max_links_per_page",
          "capabilities.web.discover_pages.max_result_chars",
          "capabilities.web.discover_pages.max_inline_chars",
          "capabilities.web.discover_pages.max_concurrency",
          "capabilities.web.discover_pages.max_tasks_per_minute",
          "capabilities.web.discover_pages.max_request_retries",
          "capabilities.web.discover_pages.max_crawl_seconds",
          "capabilities.web.discover_pages.allow_query_links",
        ]}
        overrides={{
          "capabilities.web.discover_pages.max_visit_depth": { min: 1 },
          "capabilities.web.discover_pages.max_pages": { min: 1 },
          "capabilities.web.discover_pages.max_concurrency": { min: 1 },
          "capabilities.web.discover_pages.max_crawl_seconds": { min: 1 },
        }}
      />
      <FieldSection
        title="Fetchers"
        description="Readable-content extraction implementations."
        paths={[
          "capabilities.web.fetch_with_trafilatura.enabled",
          "capabilities.web.fetch_with_defuddle.enabled",
        ]}
      />
      <FieldSection
        title="Shared Web Limits"
        description="Download, storage and request behavior shared by the web providers."
        paths={[
          "capabilities.web.request_timeout_seconds",
          "capabilities.web.max_source_bytes",
          "capabilities.web.max_output_chars",
          "capabilities.web.max_excerpt_chars",
          "capabilities.web.max_redirects",
          "capabilities.web.user_agent",
        ]}
        overrides={{
          "capabilities.web.request_timeout_seconds": { min: 1 },
        }}
      />
      <FieldSection
        title="Resource Conversion"
        description="Document-to-markdown conversion (MarkItDown / PyPDF) and its bounds."
        paths={[
          "capabilities.resource.render_pdf_pages",
          "capabilities.resource.convert_with_markitdown.enabled",
          "capabilities.resource.convert_with_markitdown.formats",
          "capabilities.resource.convert_with_markitdown.extract_images",
          "capabilities.resource.convert_with_markitdown.extract_attachments",
          "capabilities.resource.convert_with_pypdf.enabled",
          "capabilities.resource.convert_with_pypdf.extract_images",
          "capabilities.resource.convert_with_pypdf.extract_attachments",
          "capabilities.resource.max_source_bytes",
          "capabilities.resource.max_output_chars",
          "capabilities.resource.max_assets",
          "capabilities.resource.max_total_asset_bytes",
          "capabilities.resource.max_pdf_pages",
        ]}
        overrides={{
          "capabilities.resource.max_source_bytes": { min: 1 },
          "capabilities.resource.max_assets": { min: 1 },
          "capabilities.resource.max_pdf_pages": { min: 1 },
        }}
      />
    </SettingsPageBody>
  );
}
