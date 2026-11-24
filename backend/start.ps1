$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot ".uv-cache"
$env:TEMP = Join-Path $PSScriptRoot ".tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR, $env:TEMP | Out-Null
uv run --with-requirements requirements.txt python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
