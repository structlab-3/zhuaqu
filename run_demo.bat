@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo Running demo with local sample_forum.html ...
python monitor_main.py --config config.sample.json --output drafts_output.json
pause
