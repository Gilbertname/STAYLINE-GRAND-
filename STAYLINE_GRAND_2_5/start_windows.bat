@echo off
chcp 65001 >nul
title STAYLINE GRAND - Local Hotel Management
cd /d "%~dp0"
echo =================================================
echo   STAYLINE GRAND - 全方位飯店管理系統
echo   管理員/員工: http://127.0.0.1:8100/
echo   顧客訂房網站: http://127.0.0.1:8100/guest
echo   注意：運作期間請保持這個黑色視窗開啟。
echo =================================================
where py >nul 2>nul
if %errorlevel% equ 0 (
    py server.py --port 8100
) else (
    python server.py --port 8100
)
echo.
echo 伺服器已停止；如果上面出現錯誤，請截圖訊息。
pause
