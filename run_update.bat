@echo off
REM MeliPro Dashboard - Atualizacao automatica diaria

set PYTHONIOENCODING=utf-8
set GOOGLE_CLOUD_PROJECT=meli-bi-data

cd /d %~dp0

REM Log com timestamp para evitar conflito de arquivo
set LOGFILE=logs\update_%date:~6,4%%date:~3,2%%date:~0,2%.log
python generate_dashboard.py >> %LOGFILE% 2>&1
