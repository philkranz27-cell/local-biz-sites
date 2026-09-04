@echo off
REM Startet den local-biz-sites Server dauerhaft im Hintergrund.
REM Bei einem Absturz wartet das Skript 15 Sekunden und startet neu.
cd /d "C:\Users\phili\claude code lokale sessions\local-biz-sites"

:loop
echo [%date% %time%] Server wird gestartet... >> "data\server.log"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8123 >> "data\server.log" 2>&1
echo [%date% %time%] Server beendet - Neustart in 15 Sekunden. >> "data\server.log"
timeout /t 15 /nobreak > nul
goto loop
