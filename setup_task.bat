@echo off
:: ============================================
:: Ejecutar como Administrador (click derecho > Ejecutar como admin)
:: ============================================
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Necesitas ejecutar este script como Administrador.
    echo Click derecho en setup_task.bat y selecciona "Ejecutar como administrador"
    pause
    exit /b 1
)

echo Creando tarea programada "Nutribot"...
schtasks /create /tn "Nutribot" /tr "C:\Users\rgcre\Documents\nathalie-nutrition-bot\keep_alive.bat" /sc onlogon /ru "%USERNAME%" /f

if %errorlevel% equ 0 (
    echo.
    echo === Tarea creada exitosamente ===
    echo Nutribot arrancara automaticamente cuando inicies sesion.
    echo.
    schtasks /query /tn "Nutribot"
) else (
    echo.
    echo ERROR: No se pudo crear la tarea.
)
pause
