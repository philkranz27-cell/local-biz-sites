' Startet start-dashboard.bat unsichtbar (ohne schwarzes Konsolenfenster).
' Diese Datei liegt zusaetzlich im Windows-Autostart-Ordner.
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\Users\phili\claude code lokale sessions\local-biz-sites\start-dashboard.bat""", 0, False
