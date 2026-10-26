$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
& uv run --directory $projectRoot --locked --extra dev ty check
exit $LASTEXITCODE
