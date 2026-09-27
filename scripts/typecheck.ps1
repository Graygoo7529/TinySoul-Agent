$ErrorActionPreference = "Stop"

if ($env:TINYSOUL_PYTHON) {
    $pythonPath = $env:TINYSOUL_PYTHON
} else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
}

& $pythonPath --version
& $pythonPath -m ty --version
& $pythonPath -m ty check --python $pythonPath
exit $LASTEXITCODE
