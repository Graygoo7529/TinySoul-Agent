$ErrorActionPreference = "Stop"

if ($env:TINYSOUL_PYTHON) {
    $pythonPath = $env:TINYSOUL_PYTHON
} else {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
}

& $pythonPath -m ty check --python $pythonPath
