@echo off
rem vector-studio launcher — starts the server if it isn't running, opens the browser.
rem Works from anywhere (desktop shortcut friendly): paths are relative to this file.
netstat -ano | findstr ":8103" | findstr "LISTENING" >nul
if errorlevel 1 (
  start "vector-studio server" /min python "%~dp0serve.py"
  timeout /t 1 /nobreak >nul
)
start "" http://127.0.0.1:8103/
