# Frontend-Assumed / Missing Backend Capabilities

This document records backend capabilities that the current frontend design could use but that are not exposed by `tinysoul/endpoint` today. The frontend has been implemented against the existing Endpoint contract (see `docs/endpoint/frontend integration.md`) and only assumes the interfaces below for future enhancements.

## Home / Agent Knowledge Browsing

The Top Links panel already derives loaded background entries from `context.background.snapshot` and `context.background.changed` events. To let users browse Agent Home proactively (outside of what Phase1 loads), the backend would need:

- `GET /v1/home/catalog` — list effective top-level Home entries (agent, what, why, how) with title/description.
- `GET /v1/home/resource?link=home:...` — read a Home resource by its Link.
- `GET /v1/home/search?q=...` — search WHAT/WHY/HOW metadata.

These would let the frontend add a "Home" tab for inspecting and optionally loading background knowledge without issuing a User Turn.

## Workspace Search and Analysis

The Workspace tab currently reads the manifest and individual resources. Additional read-only capabilities that would improve navigation:

- `GET /v1/workspace/search?link=...&q=...&scope=...` — expose `workspace.search_text` through the Endpoint so the UI can search file contents.
- `GET /v1/workspace/analyze` — expose `workspace.analyze` so the UI can run a constrained analysis over selected reference links.
- `GET /v1/workspace/summary` — return a compact summary of the active workspace (counts by kind, retention, total size) without reading the full manifest client-side.

## Binary Resource UX

- `POST /v1/workspace/blob/upload` (multipart/form-data) would make drag-and-drop file uploads simpler than the current `PUT /v1/workspace/blob` with `application/octet-stream`.
- Preview URLs for image blobs (`GET /v1/workspace/preview?link=...`) would let the UI render thumbnails without loading full blobs into memory.

## Instance Metadata

- A capability manifest in `GET /v1/status` could let the frontend hide controls that are unavailable in the effective Action Catalog. The existing project/instance identity and protocol version already cover connection validation.

## Maintenance

- Maintenance decisions currently expose only one pending change at a time. A list view of all pending Home changes (`GET /v1/maintenance/decisions`) would support batch review in the UI.
- More granular progress facts inside a long-running Home or Memory item could support a determinate progress view. Generic request, started, decision, and completed/failed events are already available.

## Model Observability

- `llm.model.request` already contains the full message stack, which satisfies the Model mode requirement. A future improvement could be a dedicated `GET /v1/llm/tasks?turn_id=...` to replay tasks for completed turns without relying on the bounded event buffer.

## Conclusion

None of the above are required for the current frontend to function. They are recorded here so that, if the backend later exposes them, the frontend can be extended without redesign.
