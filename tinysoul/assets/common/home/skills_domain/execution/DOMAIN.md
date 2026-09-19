# Execution

Use execution for deterministic local processing. Write and edit scripts through Workspace or Home, then run the explicit script Link with its configured interpreter. Use run_script/run_shell for bounded work, or start for a Job that needs supervision across Cycles.

The process writes directly to the daily Workspace. Its default working directory is its own jobs/<job_id> directory; use cwd_link to select an existing Workspace directory, or workspace: for the root. File effects remain after failure, cancellation or stopping. There is no apply/discard step.

Use core.job.status/wait/stop for lifecycle control and execution.collect for bounded stdout/stderr pages and result Links. Reuse the returned cursors to continue reading. Collect does not execute again and does not release or commit resources. For interactive input, execution.stdin reports accepted UTF-8 bytes; resend only the unaccepted suffix.

A silent process is still running unless explicit process facts prove otherwise. Finish or stop live Jobs before answering. Completed Jobs do not require a special finalization Action.
