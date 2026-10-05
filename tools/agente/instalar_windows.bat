@echo off
rem Instala el agente de Retail IA como tarea programada de Windows: arranca al iniciar la PC y sigue corriendo.
rem Ejecutar con doble clic desde la carpeta donde están agente_sync.exe y agente.ini.
set CARPETA=%~dp0
if not exist "%CARPETA%agente.ini" (
  echo Falta agente.ini: copia agente.ini.ejemplo como agente.ini y completalo.
  pause
  exit /b 1
)
schtasks /Create /F /TN "Retail IA - Agente de sincronizacion" /SC ONSTART /DELAY 0001:00 /RL LIMITED /TR "\"%CARPETA%agente_sync.exe\""
schtasks /Run /TN "Retail IA - Agente de sincronizacion"
echo Listo. El agente queda corriendo y arranca solo con la PC. El registro esta en agente.log.
pause
