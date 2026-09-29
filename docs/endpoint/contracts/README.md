# TinySoul Endpoint v2 contracts

These files describe the stable response envelope used by the remote
visualization. They are a contract projection at the HTTP boundary; the
runtime owner remains responsible for the full JSON value and may add owner
fields through `additionalProperties`.

The current protocol is v2. A response is scoped to the generation and, when a
day or Turn is present, to that lease. The frontend must keep the returned
`generation_id`, `day`, `turn_id`, `ref`, and continuation together. It should
discard a continuation after a generation/day change or when the server
returns an invalid-continuation error.

Fixed envelopes are defined in `schemas/`: runtime status, command receipts,
Turn snapshots, configuration, resource locators, and Context overviews.
`page.json` is the shared read-only page envelope for owner content, while
`search-page.json` adds Search operation metadata. `examples/` contains
sanitized representative responses from the fake/local owner paths. IDs,
timestamps, and paths in examples are deliberately synthetic.

HTTP errors keep the existing `{code, message, details}` shape and are covered
by `schemas/error.json`. The frontend
should branch on `code`, preserve the structured `details`, and avoid parsing
human-facing `message` text. Page and Search responses are read-only
projections; receiving a page does not imply a write or an implicit resource
load.

The OpenAPI document exposes the fixed response models on the critical v2
routes. Polymorphic owner content remains represented by the common page
envelope rather than being copied into a second business DTO hierarchy.
