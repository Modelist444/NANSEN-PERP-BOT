@echo off
echo =======================================================
echo        NANSEN PERP BOT - ONE CLICK START
echo =======================================================

echo 1. Starting the Trading Bot...
start "Nansen Bot Simulation" python main.py

echo 2. Starting the Public Link Tunnel...
start "Public Link (Ngrok)" cmd /k "ngrok http 8000"

echo.
echo =======================================================
echo HOW TO GET YOUR LINK:
echo 1. Look at the new black window titled "Public Link (Ngrok)"
echo 2. Find the line that says "Forwarding".
echo 3. It will look like: https://xxxx-xxxx.ngrok-free.app -> http://localhost:8000
echo 4. Copy that https://... link. That is your new link!
echo =======================================================
echo.
pause
