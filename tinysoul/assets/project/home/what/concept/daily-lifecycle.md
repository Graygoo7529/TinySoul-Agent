# TinySoul Daily Lifecycle

TinySoul separates deterministic daily rollover from autonomous Home and Memory Maintenance so a new Business Day never depends on model availability.

Session, Workspace, and active Trash roll over together at the Business Day boundary. The active Home overlay is not archived and remains the effective Home until a Maintenance Turn accepts, rejects, or rewrites every difference; completed Home Maintenance then removes the empty runtime Home. Memory Maintenance derives one date-scoped Memory document from archived Session facts, the archived Workspace projection, and an optional existing Memory for an explicit rebuild.

A Daily Maintenance request performs rollover preflight, Home Maintenance, and at most the previous calendar day's Memory Maintenance through one MaintenanceEngine workflow. Earlier missed Memory days remain in the persistent availability projection until a manual request targets each date explicitly. Scheduled and manual Daily requests use the same autonomous Program path and task outcomes. Related entity: <home:what@entity/tiny-soul>. Related rationale: <home:why@why-is-updating-home-important>.
