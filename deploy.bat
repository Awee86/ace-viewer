@echo off
REM ---- Deploy: invia le modifiche a GitHub; Railway redeploya da solo ----
REM Uso:  deploy.bat "messaggio del commit"   (il messaggio e' opzionale)
setlocal
set MSG=%~1
if "%MSG%"=="" set MSG=update
echo Invio modifiche a GitHub (commit: "%MSG%")...
git add -A
git commit -m "%MSG%"
if errorlevel 1 (
  echo.
  echo Niente da committare ^(nessuna modifica^) oppure errore git. Vedi sopra.
  pause
  exit /b 1
)
git push
echo.
echo ============================================
echo Push completato. Railway sta ricostruendo.
echo Controlla i log su Railway; a deploy finito la
echo dashboard mostrera' la nuova versione nel footer.
echo ============================================
pause
