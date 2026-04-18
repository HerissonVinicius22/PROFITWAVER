@echo off
title PROFITWAVER — Tunnel Ngrok
color 0A
echo.
echo  ================================================
echo   PROFITWAVER — Abrindo tunel publico (ngrok)
echo  ================================================
echo.
echo  Execute este script JUNTO com a INICIAR_PONTE.bat
echo  para que o painel no Vercel consiga se conectar.
echo.
py INICIAR_NGROK.py
pause
