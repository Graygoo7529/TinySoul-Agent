# Script

Use `script.write`, `script.rewrite`, and `script.patch` to maintain complete scripts under `workspace:scripts/` or `home:how/<skill>/scripts/`. A long-term Home target requires an existing general HOW. A Workspace script remains temporary unless `script.promote` explicitly copies it into an existing HOW; Home Maintenance later reviews that Home diff.

Run Python and Bash through their separate actions. Script execution uses a transactional mirror of the active Workspace and policy checks, not a hard security sandbox. A successful process only becomes `ready_to_apply`: inspect logs and candidate paths, use `script.read_candidate` for bounded text inspection when needed, then explicitly choose `script.apply` or `script.discard`. Failed, timed-out, or stopped jobs cannot be applied. Use `script.wait` to supervise longer work at a bounded pace, and resolve the active Script or Shell job before producing a final answer.
