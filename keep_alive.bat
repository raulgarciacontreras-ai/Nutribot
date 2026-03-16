@echo off
title Nutribot - Asistente de Nathalie
color 0A
echo.
echo  ================================
echo   NUTRIBOT - Asistente Nathalie
echo  ================================
echo.
echo  Bot iniciando...
echo  Presiona Ctrl+C para detener
echo.
:loop
call venv\Scripts\python main.py
echo.
echo  Nutribot se detuvo. Reiniciando en 10 segundos...
timeout /t 10 /nobreak
goto loop
