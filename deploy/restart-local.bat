@echo off
cd /d "%~dp0.."
echo Restarting Poster (local)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8010" ^| findstr "LISTENING"') do taskkill /F /PID %%a 2>nul
start "Poster" /min python server.py
timeout /t 2 /nobreak >nul
curl -s -o NUL -w "HTTP %%{http_code}\n" http://127.0.0.1:8010/
echo Open http://127.0.0.1:8010/
pause
