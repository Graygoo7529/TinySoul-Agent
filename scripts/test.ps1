$ErrorActionPreference = "Stop"

if ($env:TINYSOUL_PYTHON) {
    $pythonPath = $env:TINYSOUL_PYTHON
} else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
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
$environmentNames = @("TEMP", "TMP", "LOCALAPPDATA", "TINYSOUL_PYTHON")
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
    $env:LOCALAPPDATA = $localAppDataRoot
    Remove-Item Env:TINYSOUL_PYTHON -ErrorAction SilentlyContinue

    Push-Location $repositoryRoot
    $locationPushed = $true
    & $pythonPath -m pytest tests --basetemp $pytestRoot -o "cache_dir=$pytestCacheRoot"
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
