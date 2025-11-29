@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo Running search-mode demo (http_html_search) ...
python monitor_main.py --config config.search.sample.json --output drafts_output.json
pause
