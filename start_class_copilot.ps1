$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$env:CC_DATA_DIR = Join-Path $projectRoot "data"
& (Join-Path $projectRoot ".venv\Scripts\python.exe") -m class_copilot
