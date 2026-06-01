@echo off
REM Build the portable .exe and publish a GitHub release in one go.
REM Requires:  gh CLI installed (https://cli.github.com) and `gh auth login` done once.
REM Reads VERSION from updater.py automatically.

setlocal enabledelayedexpansion
set "PYTHON_EXE=C:\Users\slinnerb\miniconda3\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

pushd "%~dp0"

REM 1) Read VERSION from updater.py
for /f "delims=" %%v in ('"%PYTHON_EXE%" -c "import updater; print(updater.VERSION)"') do set "VER=%%v"
if "%VER%"=="" (
  echo Could not read VERSION from updater.py.
  goto :err
)
echo Releasing v%VER%
echo.

REM 2) Check gh CLI is installed
where gh >nul 2>&1
if errorlevel 1 (
  echo The GitHub CLI ^(gh^) is not installed.
  echo Install from https://cli.github.com/ and run ^`gh auth login^` once, then re-run this script.
  goto :err
)

REM 3) Build the portable .exe
echo === Building portable .exe ===
call build_portable.bat
if errorlevel 1 goto :err
if not exist "dist\MLB-Stats-Viewer.exe" (
  echo Build produced no .exe at dist\MLB-Stats-Viewer.exe
  goto :err
)

REM 4) Publish the release
echo.
echo === Publishing GitHub release v%VER% ===
echo Enter release notes ^(what changed^). End with an empty line + Ctrl+Z + Enter:
set /p "NOTES=One-line summary: "

gh release create "v%VER%" "dist\MLB-Stats-Viewer.exe" --title "v%VER%" --notes "!NOTES!"
if errorlevel 1 goto :err

echo.
echo ================================================================
echo  Release v%VER% published.
echo  Your friend can now click "Check for Updates" in the app.
echo ================================================================
popd
endlocal
exit /b 0

:err
echo.
echo Release failed. See output above.
popd
endlocal
exit /b 1
