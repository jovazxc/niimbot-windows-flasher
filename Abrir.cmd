@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto deps
py -3 -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
  goto checkvenv
)
python -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if errorlevel 1 goto nopython
python -m venv .venv
:checkvenv
if not exist ".venv\Scripts\python.exe" goto failed
:deps
.venv\Scripts\python.exe -c "import importlib.metadata; assert importlib.metadata.version('bleak') == '3.0.2'" >nul 2>&1
if not errorlevel 1 goto run
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
:run
.venv\Scripts\python.exe app.py
if errorlevel 1 goto failed
exit /b 0
:nopython
echo Instala Python 3.10 o posterior para Windows desde https://www.python.org/downloads/windows/
echo Incluye Tcl/Tk y el lanzador py. Luego vuelve a abrir este archivo.
pause
exit /b 1
:failed
echo No se pudo abrir el programa. Revisa el error anterior.
pause
exit /b 1
