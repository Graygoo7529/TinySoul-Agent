param(
    [ValidateSet("Fast", "Full", "External")]
    [string]$Suite = "Fast",
    [Alias("Path")]
    [string[]]$TestPath = @("tests"),
    [string]$Filter = "",
    [ValidateRange(0, 100)]
    [int]$Durations = 10
)

$ErrorActionPreference = "Stop"

if ($env:TINYSOUL_PYTHON) {
    $pythonPath = $env:TINYSOUL_PYTHON
} else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
}

& $pythonPath -c "import pytest" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw (
        "Selected Python '$pythonPath' cannot import pytest. " +
        "Activate Conda environment 'TinySoul' or set TINYSOUL_PYTHON."
    )
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$localTestRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot ".local-test")
)
$runRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $localTestRoot ("runs\" + [guid]::NewGuid().ToString("N")))
)
$expectedPrefix = $localTestRoot.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
if (-not $runRoot.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Test run root must stay under .local-test"
}

$pytestRoot = Join-Path $runRoot "pytest"
$pytestCacheRoot = Join-Path $runRoot "pytest-cache"
$tempRoot = Join-Path $runRoot "temp"
$localAppDataRoot = Join-Path $runRoot "local-app-data"
$environmentNames = @(
    "TEMP",
    "TMP",
    "TMPDIR",
    "LOCALAPPDATA",
    "PYTEST_TINYSOUL_RUN_ROOT",
    "TINYSOUL_PYTHON"
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable(
        $name,
        [System.EnvironmentVariableTarget]::Process
    )
}

$exitCode = 1
$locationPushed = $false
try {
    New-Item -ItemType Directory -Force $pytestRoot | Out-Null
    New-Item -ItemType Directory -Force $tempRoot | Out-Null
    New-Item -ItemType Directory -Force $localAppDataRoot | Out-Null
    $env:TEMP = $tempRoot
    $env:TMP = $tempRoot
    $env:TMPDIR = $tempRoot
    $env:LOCALAPPDATA = $localAppDataRoot
    $env:PYTEST_TINYSOUL_RUN_ROOT = $runRoot
    Remove-Item Env:TINYSOUL_PYTHON -ErrorAction SilentlyContinue

    Push-Location $repositoryRoot
    $locationPushed = $true
    switch ($Suite) {
        "Fast" { $markerExpression = "not release and not external" }
        "Full" { $markerExpression = "not external" }
        "External" { $markerExpression = "external" }
    }
    $pytestArguments = @(
        $TestPath
        "-m"
        $markerExpression
        "--basetemp"
        $pytestRoot
        "-o"
        "cache_dir=$pytestCacheRoot"
    )
    if ($Filter) {
        $pytestArguments += @("-k", $Filter)
    }
    if ($Durations -gt 0) {
        $pytestArguments += @("--durations", $Durations)
    }
    Write-Host "TinySoul test suite: $($Suite.ToUpperInvariant())"
    Write-Host "TinySoul test paths: $($TestPath -join ', ')"
    Write-Host "TinySoul test run root: $runRoot"
    & $pythonPath -m pytest @pytestArguments
    $exitCode = $LASTEXITCODE
} finally {
    if ($locationPushed) {
        Pop-Location
    }
    foreach ($name in $environmentNames) {
        $value = $previousEnvironment[$name]
        if ($null -eq $value) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item "Env:$name" $value
        }
    }
    if ($exitCode -eq 0 -and (Test-Path -LiteralPath $runRoot)) {
        Remove-Item -Recurse -Force -LiteralPath $runRoot
    }
}

if ($exitCode -ne 0) {
    Write-Host "Test artifacts retained at $runRoot"
}
exit $exitCode
