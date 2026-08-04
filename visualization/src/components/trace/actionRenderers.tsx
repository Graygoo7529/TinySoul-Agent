/**
 * Domain-aware renderers for action inputs and results.
 *
 * Each renderer probes the well-known shapes of its action family
 * (workspace documents, execution terminal output, web results, answers).
 * Unknown shapes fall back to the raw JSON tree, so nothing is hidden.
 */

import type { ReactNode } from "react";
import type { ActionRecord } from "../../derive/model";
import { JsonTree } from "../ui/JsonTree";
import { Markdown } from "../markdown/Markdown";
import { LinkChip } from "./semantic";

/* ------------------------------- input ------------------------------- */

export function ActionInputPreview({ action }: { action: ActionRecord }) {
  const { action: name, params } = action;
  const link = str(params.link) ?? str(params.script) ?? str(params.url);
  const command = str(params.command);
  const text = str(params.text) ?? str(params.content) ?? str(params.instruction);
  const query = str(params.query);

  const rows: ReactNode[] = [];

  if (name === "core.answer" && text) {
    return (
      <div className="rounded-lg border border-line bg-bg-elev px-3 py-2">
        <Markdown>{text}</Markdown>
      </div>
    );
  }
  if (link) {
    rows.push(
      <div key="link" className="flex items-center gap-2">
        {link.startsWith("workspace:") || link.startsWith("home:") || link.startsWith("memory:") ? (
          <LinkChip link={link} />
        ) : (
          <span className="font-mono text-[11px] break-all text-info">{link}</span>
        )}
      </div>,
    );
  }
  if (command) {
    rows.push(
      <div key="cmd" className="term-block">
        <span className="term-cmd">$ {command}</span>
      </div>,
    );
  }
  if (query) {
    rows.push(
      <div key="q" className="text-[12px] text-fg">
        “{query}”
      </div>,
    );
  }
  if (text && !name.startsWith("core.answer") && text.length < 400) {
    rows.push(
      <div key="text" className="rounded-lg bg-bg-elev px-2.5 py-1.5 text-[12px] whitespace-pre-wrap text-fg-muted">
        {text}
      </div>,
    );
  }
  if (rows.length === 0) {
    return <JsonTree value={params} defaultExpanded={false} />;
  }
  return <div className="space-y-1.5">{rows}</div>;
}

/* ------------------------------- output ------------------------------ */

export function ActionResultBody({ action }: { action: ActionRecord }) {
  const payload = action.result?.payload;
  if (!payload) return null;

  const stdout = str(payload.stdout) ?? str(payload.output);
  const stderr = str(payload.stderr);
  const exitCode = num(payload.exit_code) ?? num(payload.exitCode);
  const duration = num(payload.duration_seconds) ?? num(payload.elapsed_seconds);
  const text = str(payload.text) ?? str(payload.content) ?? str(payload.markdown);
  const link = str(payload.link);
  const results = Array.isArray(payload.results) ? payload.results : null;

  const rows: ReactNode[] = [];

  if (link) {
    rows.push(
      <div key="link" className="flex items-center gap-2">
        <LinkChip link={link} />
        {num(payload.revision) !== null && (
          <span className="font-mono text-[10px] text-fg-faint">
            rev {num(payload.revision)}
          </span>
        )}
      </div>,
    );
  }

  if (exitCode !== null || stdout !== null || stderr !== null) {
    rows.push(
      <div key="term" className="term-block space-y-1">
        {exitCode !== null && (
          <div className={exitCode === 0 ? "text-[#7ee787]" : "term-stderr"}>
            exit code {exitCode}
            {duration !== null ? ` · ${duration.toFixed(1)}s` : ""}
          </div>
        )}
        {stdout && <div>{stdout.slice(0, 4000)}</div>}
        {stderr && <div className="term-stderr">{stderr.slice(0, 4000)}</div>}
      </div>,
    );
  }

  if (results && results.length > 0) {
    rows.push(
      <div key="results" className="space-y-1">
        {results.slice(0, 8).map((item, i) => (
          <ResultRow key={i} item={item} />
        ))}
        {results.length > 8 && (
          <div className="text-[10px] text-fg-faint">
            +{results.length - 8} more results
          </div>
        )}
      </div>,
    );
  }

  if (text && text.length <= 3000 && !stdout) {
    rows.push(
      <div key="text" className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5 text-[12px] whitespace-pre-wrap break-words text-fg-muted">
        {text}
      </div>,
    );
  }

  if (rows.length === 0) {
    return <JsonTree value={payload} defaultExpanded={false} />;
  }
  return <div className="space-y-1.5">{rows}</div>;
}

function ResultRow({ item }: { item: unknown }) {
  if (!item || typeof item !== "object") {
    return <div className="text-[12px] text-fg-muted">{String(item)}</div>;
  }
  const record = item as Record<string, unknown>;
  const title = str(record.title) ?? str(record.name) ?? str(record.link);
  const url = str(record.url);
  const snippet = str(record.snippet) ?? str(record.summary) ?? str(record.description);
  return (
    <div className="rounded-lg border border-line bg-bg-elev px-2.5 py-1.5">
      <div className="flex items-center gap-2">
        {title && <span className="min-w-0 flex-1 truncate text-[12px] font-medium">{title}</span>}
        {url && (
          <span className="shrink-0 font-mono text-[10px] text-info">{domainOf(url)}</span>
        )}
      </div>
      {snippet && (
        <div className="mt-0.5 line-clamp-2 text-[11px] text-fg-muted">{snippet}</div>
      )}
    </div>
  );
}

/* ------------------------------- helpers ----------------------------- */

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function domainOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
