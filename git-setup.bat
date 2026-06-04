@echo off
REM ---- Configurazione iniziale del repo (una volta sola) ----
REM Uso:  git-setup.bat https://github.com/TUO-UTENTE/ace-viewer.git
setlocal
if "%~1"=="" (
  echo.
  echo Uso: git-setup.bat ^<URL-del-repo-GitHub^>
  echo Esempio: git-setup.bat https://github.com/Ernesto/ace-viewer.git
  echo.
  pause
  exit /b 1
)
git init
git add -A
git commit -m "ACE Viewer - primo commit"
git branch -M main
git remote add origin %~1
git push -u origin main
echo.
echo ============================================
echo Repo collegato e caricato su GitHub.
echo Ora su Railway: New Project - Deploy from GitHub repo.
echo ============================================
pause
