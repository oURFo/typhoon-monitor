@echo off
cd /d "%~dp0"
echo 安裝相依套件...
py -3 -m pip install -r requirements.txt -q

echo 關閉舊的 8000 埠服務（若有）...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%a >nul 2>&1
)

echo 啟動服務 http://127.0.0.1:8000
py -3 -m uvicorn server.main:app --reload --host 127.0.0.1 --port 8000
