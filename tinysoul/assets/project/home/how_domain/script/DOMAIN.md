# Script

Use `script.write`, `script.rewrite`, and `script.patch` to maintain complete scripts under `workspace:scripts/` or `home:how/<skill>/scripts/`. Prefer general, reusable logic; avoid embedding substantial target document content in a script when a Workspace content Action fits. A Workspace script remains temporary unless `script.promote` copies it into an existing general HOW.

Run Python and Bash through their separate actions. A successful process becomes `ready_to_apply`, not committed: inspect the result as needed, then use `script.apply` or `script.discard`. Use `script.wait` for longer work, and resolve the active Script or Shell job before answering.
