# PowerShell launcher for OnlineAnnotator
$ErrorActionPreference = "Stop"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Starting OnlineAnnotator on Office Intranet                     " -ForegroundColor Green
Write-Host " Integrated with ml_server & HydrideSegmentation workflows      " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

$env:ONLINE_ANNOTATOR_PORT = "5070"
$env:ONLINE_ANNOTATOR_HOST = "0.0.0.0"

python run.py
