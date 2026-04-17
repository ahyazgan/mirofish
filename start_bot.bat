@echo off
REM MiroFish Crypto Trading Bot - Windows baslatma
REM Paper trading modu (.env icinde SIMULATION_MODE=true olmali)

cd /d "%~dp0backend"

echo ================================================================
echo   MiroFish Trading Bot baslatiliyor (paper trading modu)
echo   Durdurmak icin Ctrl+C
echo ================================================================
echo.

python run_trading.py

REM Crash olursa terminal acik kalsin ki hatayi gorebilesin
if errorlevel 1 (
    echo.
    echo Bot hata ile sonlandi. Yukaridaki loglari kontrol et.
    pause
)
