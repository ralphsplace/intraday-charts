@echo off
REM Runs the collector on the Windows PC that runs TWS, writing straight into the chart's data folder.
REM 1. Install Python 3.11+ from python.org (tick "Add python.exe to PATH").
REM 2. Edit DATA_DIR below to point at the chart's data folder on the NAS share.
REM 3. Double-click this file. Leave the window open; it reconnects by itself if TWS restarts.

set DATA_DIR=\\NAS\docker\intraday-chart\data
set SYMBOLS=QQQ SPY
REM market indexes fetched with every request (add TICK-NDX if you have Nasdaq index data)
set COMPANIONS=TICK-NYSE TRIN-NYSE

py -m pip install --quiet -r "%~dp0..\requirements.txt"
py "%~dp0fetch_ibkr.py" --symbols %SYMBOLS% --days 30 --live --host 127.0.0.1 --port 7496 --data-dir "%DATA_DIR%"
pause
