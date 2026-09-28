@echo off
title NBA Manager - Initialisation de la base 2KRatings
cd /d "%~dp0"
echo.
echo ========================================
echo NBA MANAGER - IMPORT INITIAL
echo ========================================
echo.
python setup_database.py
echo.
pause
