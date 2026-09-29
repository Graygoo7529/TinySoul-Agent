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

Fixed envelopes are defined by the public Pydantic response models in
`tinysoul/gateway/endpoint/http/schemas/responses.py`. `schemas/` exports their
`model_json_schema(mode="serialization")` with the Draft 2020-12 declaration;
the contract tests compare these files with the model export and the actual
OpenAPI field definitions. Owner content remains JSON-safe dynamic data.

| Response family | Schema | Example |
| --- | --- | --- |
| Owner/Disclosure page | `page.json` | `home-effective`, `memory-document`, `context-trace-page` |
| Installed Context messages | `context-messages.json` | `context-messages` |
| Turn and history | `turn-snapshot.json`, `interaction-page.json` | `turn-waiting`, `turn-finished`, `interactions`, `question-reply` |
| Search result | `search-page.json` | `search-evidence` |
| Job detail/output | `job.json`, `job-output.json` | `job-detail`, `job-output` |
| Configuration and presets | `configuration.json`, `config-mutation.json`, `preset.json` | `config-views`, `config-apply`, `preset` |
| Navigation and runtime | `context-overview.json`, `resource-resolve.json`, `runtime-status.json` | `context-overview`, `memory-fragment`, `runtime-status` |

`tests/gateway/endpoint/test_contracts.py::collect_contract_responses` runs the
local Agent, SDK and ASGI paths that supply `examples/`. Only model outputs are
fake; owners, paging, question/reply, budget recovery, configuration activation
and the local process Job are real. IDs, timestamps and opaque continuation
tokens are normalized for readability, without removing fields or nulls.
Example tokens are illustrative and cannot be sent to a running server.

`home-fragment` and `home-fragment-end` show the first and final pages of one
long item, not adjacent pages; the test consumes all intermediate pages and
decodes the assembled canonical JSON. Always consume the current items and
fragment before checking `next_continuation`. A final fragment may have no
next token. Job output tokens instead support polling after an empty read.

`config-views` and `preset` come from a minimal local ConfigController to keep
the full source and field serialization small; absent model settings remain
null in the preset snapshot. The HTTP test also validates saved/active and
preset responses from the assembled Agent. `capabilities` captures an
unconfigured ACP/MCP directory, not a simulated live connection.
`model-observation` is a real retrieval invocation event linking the consumer,
Search step and model task; it is not a page response.

HTTP errors keep the existing `{error: {code, message, details}}` shape and are covered
by `schemas/error.json`. The frontend
should branch on `code`, preserve the structured `details`, and avoid parsing
human-facing `message` text. Page and Search responses are read-only
projections; receiving a page does not imply a write or an implicit resource
load.

The OpenAPI document exposes the fixed response models on the critical v2
routes. Ordinary pages, Search results, Job output and model observations
retain their separate envelopes; no second business DTO hierarchy is implied.
