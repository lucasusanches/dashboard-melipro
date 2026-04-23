@echo off
REM MeliPro Dashboard - Atualizacao automatica diaria
REM Agendado via Windows Task Scheduler para rodar as 08:00

set PYTHONIOENCODING=utf-8
set GOOGLE_CLOUD_PROJECT=meli-bi-data

cd /d %~dp0
python generate_dashboard.py >> logs\update.log 2>&1
