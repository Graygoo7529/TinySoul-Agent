# Execution

Use execution for deterministic local processing. Write and edit scripts through Workspace or Home, then run the explicit script reference with its configured interpreter. Use run for bounded work that can finish in the current Action, or start for a Job that needs supervision across Cycles. For run and start, provide either command or source_ref; command accepts bash, powershell, or cmd, while scripts also accept python.

Choose from the interpreters available in the current runtime. Python scripts can run directly through source_ref. Use a shell when its command syntax or native tools help with the task. Output encoding normally follows the interpreter configuration; set output_encoding when a child program uses a different encoding. Collected output and saved logs are UTF-8.

On Windows, use curl.exe for curl's native arguments; PowerShell's curl alias may refer to Invoke-WebRequest. Child programs receive the configured proxy environment. PowerShell HTTP cmdlets may need an explicit -Proxy when using a proxy, so choose the command according to the client's own proxy support.

The process writes directly to the daily Workspace. Its default working directory is its own jobs/<job_id> directory; use cwd_ref to select an existing Workspace directory, or workspace: for the root. File effects remain after failure, cancellation or stopping. There is no apply/discard step.

Use core.wait to pause until any Job produces a terminal or pending-input fact. Passive Workspace refreshes do not interrupt this ordinary Job wait; add an explicit event filter when the current Workspace must be monitored. Use core.job.status/stop for lifecycle control and execution.collect for bounded stdout/stderr pages and result references. Reuse the returned cursors to continue reading. Collect does not execute again and does not release or commit resources. For interactive input, execution.stdin reports accepted UTF-8 bytes; resend only the unaccepted suffix.

A silent process is still running unless explicit process facts prove otherwise. Finish or stop live Jobs before answering. Completed Jobs do not require a special finalization Action.

Status and collect also work while a Job is running, including output without a final newline. To check progress periodically, use core.wait with event_kind="job" and timeout_seconds, then inspect the Job and continue waiting as needed. An empty output page means no new captured text at that moment.
