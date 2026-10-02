import { settingsText } from "../i18n";
/**
 * Workspace settings (config-coverage §5.1): the daily workspace root and its
 * read/write/search/analysis bounds. pinned/tmp/library are manifest tags and
 * never change the day lifecycle — the note sits next to the root.
 */

import { Badge } from "../../../components/ui/Badge";
import { FieldSection, SettingsPageBody } from "./controls";

export function WorkspacePage() {
  return (
    <SettingsPageBody>
      <FieldSection
        title={settingsText("Location & Capacity")}
        description={settingsText("The daily workspace root and how many resources it tracks.")}
        paths={[
          "workspace.root",
          "workspace.max_files",
          "workspace.max_read_chars",
          "workspace.max_write_chars",
          "workspace.max_image_bytes",
          "workspace.ignore_dirs",
        ]}
        overrides={{
          "workspace.max_files": { min: 1 },
          "workspace.max_read_chars": { min: 1 },
          "workspace.max_write_chars": { min: 1 },
          "workspace.max_image_bytes": { min: 1 },
        }}
      />
      <div className="-mt-2 rounded-lg border border-line bg-bg-elev px-3.5 py-2.5 text-[12px] leading-5 text-fg-muted">
        <Badge tone="gray">pinned</Badge> <Badge tone="gray">tmp</Badge>{" "}
        <Badge tone="gray">library</Badge> 是 Workspace 的资源标签，不改变按日归档的生命周期。
      </div>
      <FieldSection
        title={settingsText("Watching & Search")}
        description={settingsText("External change hints and lexical search bounds; formal writes never depend on watching.")}
        paths={[
          "workspace.watch.enabled",
          "workspace.watch.debounce_ms",
          "workspace.search.max_query_chars",
          "workspace.search.max_scan_chars",
        ]}
        overrides={{
          "workspace.watch.debounce_ms": { min: 0 },
          "workspace.search.max_query_chars": { min: 1 },
          "workspace.search.max_scan_chars": { min: 1 },
        }}
      />
      <FieldSection
        title={settingsText("Analysis")}
        description={settingsText("Bounds of the workspace analyze action.")}
        paths={[
          "workspace.analysis.max_intent_chars",
          "workspace.analysis.max_reference_links",
          "workspace.analysis.max_source_chars",
          "workspace.analysis.max_chars_per_reference",
          "workspace.analysis.max_answer_chars",
        ]}
        overrides={{
          "workspace.analysis.max_intent_chars": { min: 1 },
          "workspace.analysis.max_reference_links": { min: 1 },
          "workspace.analysis.max_source_chars": { min: 1 },
          "workspace.analysis.max_chars_per_reference": { min: 1 },
          "workspace.analysis.max_answer_chars": { min: 1 },
        }}
      />
    </SettingsPageBody>
  );
}
