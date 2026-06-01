@echo off
REM Build a single-file portable .exe of MLB Stats Viewer using PyInstaller.
REM Output: dist\MLB-Stats-Viewer.exe  — copy this anywhere; no install needed.

setlocal
set "PYTHON_EXE=C:\Users\slinnerb\miniconda3\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

pushd "%~dp0"

echo Installing/upgrading build dependencies...
"%PYTHON_EXE%" -m pip install --upgrade pyinstaller customtkinter requests Pillow tzdata || goto :err

echo.
echo Building portable executable (this may take a few minutes)...
"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name "MLB-Stats-Viewer" ^
  --collect-all customtkinter ^
  --collect-all tzdata ^
  main.py || goto :err

echo.
echo ================================================================
echo  Build complete.
echo  Portable .exe:  %CD%\dist\MLB-Stats-Viewer.exe
echo  Copy that file anywhere (USB stick, OneDrive, Desktop) and run.
echo ================================================================
popd
endlocal
exit /b 0

:err
echo.
echo Build failed. See output above.
popd
endlocal
exit /b 1
