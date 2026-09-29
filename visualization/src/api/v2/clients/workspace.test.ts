import { describe, expect, it } from "vitest";

import type { WorkspaceManifest, WorkspaceMutationResult } from "../types";
import {
  bodyJson,
  createTestTransport,
  jsonResponse,
  queryOf,
} from "./testing";
import { formatByteRange, WorkspaceClient } from "./workspace";

const manifest: WorkspaceManifest = {
  schema_version: 4,
  day: "2026-09-29",
  resources: [],
};

const mutation: WorkspaceMutationResult = {
  record: {
    link: "workspace:notes/a.md",
    relative_path: "notes/a.md",
    kind: "text",
    media_type: "text/markdown",
    suffix: ".md",
    summary: "",
    size: 12,
    mtime_ns: 1,
    description: "",
    tags: [],
  },
  manifest,
};

describe("formatByteRange", () => {
  it("formats the three supported forms", () => {
    expect(formatByteRange({ start: 0, end: 1023 })).toBe("bytes=0-1023");
    expect(formatByteRange({ start: 5 })).toBe("bytes=5-");
    expect(formatByteRange({ suffix: 500 })).toBe("bytes=-500");
  });
});

describe("WorkspaceClient", () => {
  it("manifest accepts an archive day", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(manifest),
    );
    const result = await new WorkspaceClient(transport).manifest({
      day: "2026-09-28",
    });
    expect(result.schema_version).toBe(4);
    expect(new URL(requests[0]!.url).pathname).toBe("/v2/workspace/manifest");
    expect(queryOf(requests[0]!, "day")).toBe("2026-09-28");
  });

  it("resource passes continuation and full=true", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse({
        link: "workspace:notes/a.md",
        locator: { link: "workspace:notes/a.md", day: "2026-09-29" },
        day: "2026-09-29",
        text: "完整正文",
        size: 12,
        media_type: "text/markdown",
        editable: true,
        truncated: false,
        complete: true,
      }),
    );
    const client = new WorkspaceClient(transport);
    const page = await client.resource({
      link: "workspace:notes/a.md",
      full: true,
    });
    expect(page.complete).toBe(true);
    expect(page.editable).toBe(true);
    expect(queryOf(requests[0]!, "full")).toBe("true");
    expect(queryOf(requests[0]!, "link")).toBe("workspace:notes/a.md");
  });

  it("readBlob sends Range and returns the raw Response", async () => {
    const { transport, requests } = createTestTransport(
      () =>
        new Response(new Uint8Array([9, 9]), {
          status: 206,
          headers: {
            "Content-Range": "bytes=4-5/20",
            "Content-Type": "image/png",
          },
        }),
    );
    const response = await new WorkspaceClient(transport).readBlob({
      link: "workspace:assets/logo.png",
      day: "2026-09-28",
      range: { start: 4, end: 5 },
    });
    expect(response.status).toBe(206);
    expect(response.headers.get("Content-Type")).toBe("image/png");
    expect(requests[0]?.headers.range).toBe("bytes=4-5");
    expect(queryOf(requests[0]!, "day")).toBe("2026-09-28");
  });

  it("write routes carry their documented bodies and query", async () => {
    const { transport, requests } = createTestTransport(() =>
      jsonResponse(mutation),
    );
    const client = new WorkspaceClient(transport);
    await client.writeText({ link: "workspace:notes/a.md", text: "hi", overwrite: true });
    await client.writeBlob(
      { link: "workspace:assets/logo.png", overwrite: false },
      new Blob([new Uint8Array([1])]),
    );
    await client.createDirectory({ link: "workspace:notes" });
    await client.move({
      link: "workspace:notes/a.md",
      target_link: "workspace:notes/b.md",
    });
    await client.setTags({ link: "workspace:notes/a.md", tags: ["pinned"] });
    await client.edit({
      link: "workspace:notes/a.md",
      edits: [{ old_text: "hi", new_text: "hello" }],
    });
    await client.append({ link: "workspace:notes/a.md", text: "\nmore" });

    expect(requests.map((r) => [r.method, new URL(r.url).pathname])).toEqual([
      ["PUT", "/v2/workspace/resource"],
      ["PUT", "/v2/workspace/blob"],
      ["POST", "/v2/workspace/directory"],
      ["POST", "/v2/workspace/move"],
      ["PUT", "/v2/workspace/tags"],
      ["POST", "/v2/workspace/edit"],
      ["POST", "/v2/workspace/append"],
    ]);
    expect(bodyJson(requests[0]!)).toEqual({
      link: "workspace:notes/a.md",
      text: "hi",
      overwrite: true,
    });
    expect(queryOf(requests[1]!, "link")).toBe("workspace:assets/logo.png");
    expect(queryOf(requests[1]!, "overwrite")).toBe("false");
    expect(bodyJson(requests[4]!)).toEqual({
      link: "workspace:notes/a.md",
      tags: ["pinned"],
    });
    expect(bodyJson(requests[5]!)).toEqual({
      link: "workspace:notes/a.md",
      edits: [{ old_text: "hi", new_text: "hello" }],
    });
  });

  it("trash list/trash/restore use the trash envelope", async () => {
    const trashItem = {
      ref: "trash:workspace/abc",
      trash_id: "abc",
      original: mutation.record,
      descendants: [],
      trashed_at: 1790668800,
      day: "2026-09-29",
    };
    const { transport, requests } = createTestTransport((request) => {
      if (request.method === "GET") {
        return jsonResponse({ day: "2026-09-29", items: [trashItem] });
      }
      if (request.url.endsWith("/trash")) {
        return jsonResponse({ trash: trashItem, manifest });
      }
      return jsonResponse(mutation);
    });
    const client = new WorkspaceClient(transport);

    const page = await client.listTrash({ day: "2026-09-28", limit: 10 });
    expect(page.items[0]?.ref).toBe("trash:workspace/abc");
    expect(page.day).toBe("2026-09-29");

    const trashed = await client.trash({ link: "workspace:notes/a.md" });
    expect(trashed.trash.trash_id).toBe("abc");
    expect(trashed.manifest.schema_version).toBe(4);

    const restored = await client.restore({ trash_ref: "trash:workspace/abc" });
    expect(restored.record.link).toBe("workspace:notes/a.md");

    expect(requests.map((r) => [r.method, new URL(r.url).pathname])).toEqual([
      ["GET", "/v2/workspace/trash"],
      ["POST", "/v2/workspace/trash"],
      ["POST", "/v2/workspace/restore"],
    ]);
    expect(bodyJson(requests[2]!)).toEqual({ trash_ref: "trash:workspace/abc" });
  });
});
