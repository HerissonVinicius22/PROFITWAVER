@echo off
title ProfitWave - Limpador de Sistema
chcp 65001 >nul

echo ==========================================
echo    Limpando processos do ProfitWave...
echo ==========================================

:: Forçar encerramento por nome de processo
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM node.exe /T 2>nul

:: Encontrar e matar qualquer coisa nas portas 3000 e 5001 usando PowerShell (mais garantido)
echo Liberando portas...
powershell -Command "Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
powershell -Command "Get-NetTCPConnection -LocalPort 5001 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

:: Fechar outros CMDs (exceto este)
taskkill /F /IM cmd.exe /FI "WINDOWTITLE ne ProfitWave - Limpador de Sistema" /T 2>nul

echo.
echo ✅ Sistema limpo com sucesso! 
echo Agora voce pode abrir o INICIAR_PONTE.bat
echo.
pause
