@echo off
echo Compilazione ACE Agent in eseguibile Windows...
python -m pip install --upgrade pip
pip install pyinstaller requests
pyinstaller --onefile --name ace-agent --console watcher.py
echo.
echo ============================================
echo Eseguibile creato in:  dist\ace-agent.exe
echo Distribuiscilo insieme a config.ini
echo ============================================
pause
