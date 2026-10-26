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
$pythonPath = if ($env:TINYSOUL_PYTHON) {
    $env:TINYSOUL_PYTHON
} else {
    (Get-Command python -ErrorAction Stop).Source
}
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
& $pythonPath @testArguments
exit $LASTEXITCODE
