@echo off
REM ====================================================================
REM  POST-WORKSHOP HBW SURVEY  --  DAILY DASHBOARD UPDATE
REM  Research Solutions (M&A Research Solutions LLC)
REM
REM  Run this once a day, after dropping the fresh SurveyCTO exports
REM  into this folder (keep the same file names). It rebuilds the
REM  dashboard and publishes it to the live site.
REM
REM  Just double-click this file.
REM ====================================================================
setlocal
cd /d "%~dp0"
color 0F
echo.
echo  ============================================================
echo    POST-WORKSHOP HBW SURVEY  -  DAILY DASHBOARD UPDATE
echo  ============================================================
echo.

REM ---- 1. Find Python -------------------------------------------------
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if not defined PY (
  echo   [X] Python was not found on this computer.
  echo       Install Python 3 from https://www.python.org/downloads/
  echo       and tick "Add python.exe to PATH" during setup.
  goto :fail
)
echo   [1/5] Python found: %PY%

REM ---- 2. Check the data files are present ----------------------------
if not exist "Post-workshop HBW Survey - Wife.dta" (
  if not exist "Post-workshop HBW Survey - Wife_WIDE.csv" (
    echo   [X] No wife survey export found in this folder.
    echo       Expected: "Post-workshop HBW Survey - Wife.dta"
    echo             or: "Post-workshop HBW Survey - Wife_WIDE.csv"
    goto :fail
  )
)
if not exist "Post-workshop HBW Survey - Husband.dta" (
  if not exist "Post-workshop HBW Survey - Husband_WIDE.csv" (
    echo   [X] No husband survey export found in this folder.
    goto :fail
  )
)
echo   [2/5] Survey exports found

REM ---- 3. Make sure the Python packages are installed ------------------
%PY% -c "import pandas, numpy, openpyxl, cryptography" >nul 2>&1
if errorlevel 1 (
  echo   [3/5] Installing the required Python packages, please wait...
  %PY% -m pip install --quiet --upgrade pandas numpy openpyxl cryptography
  if errorlevel 1 (
    echo   [X] Could not install the Python packages. Check your internet connection.
    goto :fail
  )
) else (
  echo   [3/5] Python packages OK
)

REM ---- 4. Rebuild the dashboard ---------------------------------------
echo   [4/5] Rebuilding the dashboard...
echo.
%PY% assemble_template.py
if errorlevel 1 goto :buildfail
%PY% build_dashboard.py
if errorlevel 1 goto :buildfail

REM ---- 5. Publish to the live site ------------------------------------
where git >nul 2>&1
if errorlevel 1 (
  echo   [5/5] Git is not installed - the dashboard was rebuilt locally only.
  echo         Open index.html to view it. Install Git to publish automatically.
  goto :done
)
if not exist ".git" (
  echo   [5/5] This folder is not connected to GitHub yet - rebuilt locally only.
  echo         See README.md for the one-time setup steps.
  goto :done
)

echo   [5/5] Publishing to the live site...
git add -A
git diff --cached --quiet
if not errorlevel 1 (
  echo         Nothing changed since the last update - the live site is already current.
  goto :done
)
for /f "tokens=* usebackq" %%d in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"`) do set "STAMP=%%d"
git commit -m "Daily data update - %STAMP%" >nul
if errorlevel 1 goto :gitfail
git push
if errorlevel 1 goto :gitfail
echo.
echo         Published. The live site updates in about a minute:
echo         https://postworkshop-hbw.rs.org.pk

:done
echo.
echo  ============================================================
echo    DONE.  Local file:  %~dp0index.html
echo  ============================================================
echo.
pause
exit /b 0

:buildfail
echo.
echo   [X] The dashboard build failed - see the message above.
echo       Most often this means a data file is open in Stata or Excel.
echo       Close it and run this again.
goto :fail

:gitfail
echo.
echo   [X] Could not publish to GitHub.
echo       The dashboard WAS rebuilt locally - open index.html to view it.
echo       Check your internet connection and GitHub sign-in, then run again.
goto :fail

:fail
echo.
pause
exit /b 1
