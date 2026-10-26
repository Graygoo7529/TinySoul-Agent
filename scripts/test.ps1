param(
    [ValidateSet("Fast", "Full", "Integration", "Packaging", "External")]
    [string]$Suite = "Fast",
    [Alias("Path")]
    [string[]]$TestPath = @("tests"),
    [string]$Filter = "",
    [string]$ArtifactRoot = ".local-test",
    [ValidateRange(0, 100)]
    [int]$Durations = 10,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$testArguments = @(
    (Join-Path $PSScriptRoot "test.py")
    "--suite"
    $Suite.ToLowerInvariant()
    "--artifact-root"
    $ArtifactRoot
    "--durations"
    $Durations
) + $TestPath
if ($Filter) { $testArguments += @("-k", $Filter) }
if ($KeepArtifacts) { $testArguments += "--keep-artifacts" }
& uv run --directory $projectRoot --locked --extra dev python @testArguments
exit $LASTEXITCODE
