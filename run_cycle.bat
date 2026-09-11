@echo off
REM ===================================================================
REM  One-click research cycle.
REM
REM  Usage:   run_cycle.bat 2
REM           run_cycle.bat 2 H1
REM
REM  Pulls my latest changes, runs the cycle's pre-registered hypotheses
REM  on the RESEARCH portion of your data, and pushes the report back.
REM  The lockbox is never touched.
REM ===================================================================
setlocal

if "%~1"=="" (
    echo Usage: run_cycle.bat CYCLE_NUMBER [TIMEFRAME]
    echo   e.g. run_cycle.bat 2
    echo        run_cycle.bat 2 H1
    exit /b 1
)

set CYCLE=%~1
set TF=%~2
if "%TF%"=="" set TF=D1

cd /d "%~dp0"

echo.
echo [1/4] fetching latest strategy changes...
git pull --rebase --autostash
if errorlevel 1 (
    echo    git pull failed. Resolve manually, then re-run.
    exit /b 1
)

echo.
echo [2/4] verifying the engine still passes its tests...
python -m pytest tests/ -q
if errorlevel 1 (
    echo    TESTS FAILED. Not running the backtest on a broken engine.
    exit /b 1
)

echo.
echo [3/4] running research cycle %CYCLE% on %TF%...
python scripts\auto_backtest.py --cycle %CYCLE% --timeframe %TF% --csv data\XAUUSD_%TF%.csv --push
if errorlevel 1 (
    echo    cycle failed
    exit /b 1
)

echo.
echo [4/4] done. Report pushed.
echo.
echo Tell me the cycle finished and I will pull the report and analyse it.
endlocal
