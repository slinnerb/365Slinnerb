@echo off
REM Launch MLB Stats Viewer using the local Python install.
REM Edit PYTHON_EXE below if your Python is somewhere else.

setlocal
set "PYTHON_EXE=C:\Users\slinnerb\miniconda3\python.exe"
if not exist "%PYTHON_EXE%" (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python not found. Edit PYTHON_EXE in run.bat, or install Python.
    pause
    exit /b 1
  )
  set "PYTHON_EXE=python"
)

pushd "%~dp0"
"%PYTHON_EXE%" main.py
popd
endlocal
