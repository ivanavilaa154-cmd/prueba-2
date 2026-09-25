@echo off
rem Doble clic para abrir la plataforma en http://localhost:8000 (Windows).
title Plataforma IA para ERP
cd /d "%~dp0backend"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || goto sinpython

if not exist .venv (
  echo Preparando la plataforma por primera vez, tarda un par de minutos...
  %PY% -m venv .venv || goto error
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt || goto error
if not exist .env copy .env.example .env >nul
if not exist demo_erp.db python -m app.erp.demo

echo.
echo Plataforma lista en http://localhost:8000  (para cerrarla, cerra esta ventana)
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8000"
python -m uvicorn app.main:app
goto fin

:sinpython
echo No encontre Python. Instalalo desde https://www.python.org/downloads/
echo (en el instalador marca "Add python.exe to PATH") y volve a abrir este archivo.
pause
goto fin

:error
echo Algo fallo al preparar la plataforma. Copia el mensaje de arriba y mandamelo.
pause

:fin
