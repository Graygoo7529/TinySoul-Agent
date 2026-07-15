# TinySoul Daily Lifecycle

TinySoul separates deterministic daily rollover from review-driven Home and Memory Maintenance so a new Business Day never depends on model availability or a review decision.

Session, Workspace, and active Trash roll over together at the Business Day boundary. The active Home overlay is not archived or cleared and remains the effective Home until Home Maintenance applies or discards its changes. Memory Maintenance independently derives one date-scoped Memory document from archived Session facts and an optional existing Memory for the same date.

Rollover, Home Maintenance, and Memory Maintenance are separate Program work with independent failure outcomes. Related entity: <home:what@entity/tiny-soul>. Related rationale: <home:why@why-is-updating-home-important>.
