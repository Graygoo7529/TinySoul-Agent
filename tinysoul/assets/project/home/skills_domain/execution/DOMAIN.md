# Execution

Use `execution.create_script` for a new complete script, `execution.rewrite_script` for a complete replacement of an existing script, and `execution.patch_script` for a precise local edit under `workspace:scripts/` or `home:skills/<skill>/scripts/`. In the authoring instruction, state the current goal and a reasonable scope or approximate size when useful, without forcing a fixed output shape. Prefer general, reusable logic; avoid embedding substantial target document content in a script when a Workspace content Action fits. A Workspace script remains temporary unless `execution.promote_script` copies it into an existing general skill.

Use `execution.run_python_script` or `execution.run_bash_script` for maintained code. Use `execution.run_powershell`, `execution.run_cmd`, or `execution.run_bash_command` for immediate commands that do not need a maintained Script resource. Prefer PowerShell for structured Windows work, Cmd only for Cmd-specific built-ins, and Bash only when the project exposes it.

All run actions execute without interactive stdin in a transactional mirror of the active Workspace. This provides transaction isolation, limits, process-tree termination, and explicit Workspace commit; it is not an OS security sandbox. A process may still access host paths, environment, network, or child processes outside the mirror, and those effects cannot be rolled back.

A successful process with changes becomes `ready_to_apply`, not committed. Inspect bounded logs and candidate metadata, use `execution.read_candidate` when needed, then choose `execution.apply` or `execution.discard`. A successful immediate command with no Workspace changes completes without requiring apply or discard; its resources are reclaimed before the next execution or when the Turn ends. Failed, timed-out, or stopped jobs cannot be applied and remain available only for inspection and discard.

Use `core.job.status` to inspect an active Execution job, `core.job.wait` to wait for its terminal state or an explicit timeout, and `core.job.stop` when it should be terminated. New user instructions can interrupt a wait. Resolve the active Execution job before answering.

A successful `execution.apply` is the authoritative Workspace commit for the reported links and revision. Read committed content afterward only when the user requested verification or correctness cannot be established from the result and candidate metadata. After apply or discard resolves the job and the user goal is complete, update task state and answer.

When an immediate command is a fallback for another capability, change the execution mechanism without weakening the user's content, evidence, citation, structure, or completeness requirements. Apply only a complete candidate that still satisfies those requirements.
