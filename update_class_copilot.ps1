$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$env:GIT_SSL_CAINFO = "C:\D\study\lean4TBL\Git\mingw64\etc\ssl\certs\ca-bundle.crt"
& "C:\D\study\lean4TBL\Git\cmd\git.exe" pull

& (Join-Path $projectRoot ".venv\Scripts\python.exe") -m pip install -e .

Push-Location (Join-Path $projectRoot "frontend")
npm install
npm run build
Pop-Location
