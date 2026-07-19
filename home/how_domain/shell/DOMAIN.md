# Shell

Use Shell for immediate PowerShell, Cmd, or optional Bash commands that do not need a maintained Script resource. Prefer PowerShell for structured Windows work, Cmd only for Cmd-specific built-ins, and Bash only when the project exposes it. Commands run without interactive stdin in a transactional mirror of the active Workspace.

Shell provides transaction isolation, limits, process-tree termination, and explicit Workspace commit; it is not an OS security sandbox. A command may still access host paths, environment, network, or child processes outside the mirror, and those effects cannot be rolled back. Do not use Shell when that trust boundary is unacceptable.

If a successful command changes no Workspace files, it completes and cleans itself automatically. If it produces a diff, inspect bounded logs and candidate metadata, use `shell.read_candidate` when needed, then choose `shell.apply` or `shell.discard`. Failed, timed-out, or stopped jobs cannot be applied and remain available only for inspection and discard. Use `shell.wait` for paced supervision, and resolve the active Script or Shell job before answering.
