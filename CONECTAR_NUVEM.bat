@echo off
setlocal
title ProfitWave - Assistente de Login Cloud

echo Verificando instalacao do Python...

:: Tenta o caminho absoluto detectado
set "PYTHON_PATH=C:\Users\Trader Academic\AppData\Local\Python\bin\python.exe"

if exist "%PYTHON_PATH%" (
    echo Usando Python: %PYTHON_PATH%
    "%PYTHON_PATH%" CONECTAR_NUVEM.py
) else (
    :: Tenta o comando 'py' como alternativa
    py --version >nul 2>&1
    if %errorlevel% == 0 (
        echo Usando comando 'py'...
        py CONECTAR_NUVEM.py
    ) else (
        echo ERRO: Python nao encontrado no sistema.
        echo Por favor, instale o Python em python.org
        pause
    )
)

echo.
echo Processo finalizado.
pause
