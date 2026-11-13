# pyprof - PowerShell shim (Windows / pwsh)
$dir = Join-Path $PSScriptRoot "..\python"
if ($env:PYPROF_PYTHON) { $py = $env:PYPROF_PYTHON }
elseif ($env:VIRTUAL_ENV) { $py = Join-Path $env:VIRTUAL_ENV $(if ($IsWindows -or $env:OS -eq "Windows_NT") { "Scripts\python.exe" } else { "bin/python" }) }
elseif ($env:CONDA_PREFIX) { $py = Join-Path $env:CONDA_PREFIX "python.exe" }
else { $py = "python" }
& $py -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from _vscode_pyprof.launcher import cli_main; cli_main()" $dir @args
exit $LASTEXITCODE
