@echo off
rem pyprof - profile a Python program from a VS Code terminal (Windows).
setlocal
set "PYPROF_DIR=%~dp0..\python"
if defined PYPROF_PYTHON (set "PY=%PYPROF_PYTHON%") else if defined VIRTUAL_ENV (set "PY=%VIRTUAL_ENV%\Scripts\python.exe") else if defined CONDA_PREFIX (set "PY=%CONDA_PREFIX%\python.exe") else (set "PY=python")
"%PY%" -c "import sys; sys.path.insert(0, sys.argv.pop(1)); from _vscode_pyprof.target.launcher import cli_main; cli_main()" "%PYPROF_DIR%" %*
exit /b %ERRORLEVEL%
