# Start a local demo server on Windows for development and trials.
# Data goes to .\dev-data (git-ignored). Open http://127.0.0.1:5070/
param([int]$Port = 5070, [switch]$NoDemo)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $root "src"
$args = @("-m", "online_annotator", "serve", "--port", $Port, "--data-dir", (Join-Path $root "dev-data"))
if (-not $NoDemo) { $args += "--demo" }
python @args
