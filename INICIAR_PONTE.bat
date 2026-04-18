@echo off
setlocal
title ProfitWave Bridge System

:: Definir encoding UTF-8
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo.
echo ==========================================
echo       ProfitWave - Reiniciando Sistema
echo ==========================================
echo.

:: Matar processos fantasmas que podem estar travando as portas
echo [1/3] Limpando processos antigos...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM node.exe /T 2>nul

:: Aguardar um segundo para as portas liberarem
timeout /t 2 /nobreak >nul

:: Limpar portas especificamente caso o taskkill não tenha pego
echo [2/3] Liberando portas 3000 e 5001...
powershell -Command "Stop-Process -Id (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue" 2>nul
powershell -Command "Stop-Process -Id (Get-NetTCPConnection -LocalPort 5001 -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue" 2>nul

echo [3/3] Iniciando o Painel e a Ponte...
echo.

:: Iniciar Frontend em uma nova janela
start "ProfitWave - Painel" cmd /k "npm run dev"

:: Iniciar Backend na janela atual
echo 📡 Iniciando Ponte de Sinais...
python quotex_bridge.py

pause
