@echo off
REM Startet den local-biz-sites Server dauerhaft im Hintergrund.
REM Bei einem Absturz wartet das Skript 15 Sekunden und startet neu.
REM Wird beim Anmelden automatisch ausgefuehrt: Autostart-Ordner -> local-biz-sites.vbs
cd /d "C:\Users\phili\claude code lokale sessions\local-biz-sites"

:loop
REM Laeuft schon einer? Dann nicht daneben starten. Windows laesst 0.0.0.0:8123 und
REM 127.0.0.1:8123 gleichzeitig binden - dann liefen zwei Server auf derselben
REM Datenbank, beide mit eigener Pipeline, und verbrauchten das Groq-Kontingent doppelt.
curl.exe -s -o NUL --max-time 3 http://127.0.0.1:8123/
if not errorlevel 1 (
  timeout /t 60 /nobreak > nul
  goto loop
)

echo [%date% %time%] Server wird gestartet... >> "data\server.log"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8123 >> "data\server.log" 2>&1
echo [%date% %time%] Server beendet - Neustart in 15 Sekunden. >> "data\server.log"
timeout /t 15 /nobreak > nul
goto loop
