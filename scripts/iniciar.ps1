# Sobe o banco, roda a atualização e abre o app (SPEC §10). Chamado pela tarefa de logon.
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
New-Item -ItemType Directory -Force "logs" | Out-Null
$log = "logs/atualizar-$(Get-Date -Format yyyy-MM-dd).log"

# 1. Espera o Docker Desktop (até 120 s) e sobe o Postgres.
$limite = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $limite) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 5
}
# Via cmd: no PowerShell 5.1, redirecionar o stderr de um executável grava cada linha no log
# como erro (NativeCommandError), mesmo quando o comando dá certo.
function Registrar([string]$comando) {
    Add-Content $log "[$(Get-Date -Format HH:mm:ss)] $comando"
    cmd /c "$comando >> `"$log`" 2>&1"
    Add-Content $log "[$(Get-Date -Format HH:mm:ss)] codigo de saida: $LASTEXITCODE"
}

Registrar "docker compose up -d --wait db"

# 2. Atualização. O app sobe mesmo que este passo falhe.
Registrar "uv run python -m recomendador atualizar"

# 3. App só em localhost.
Start-Process -WindowStyle Hidden -FilePath "uv" -ArgumentList @(
    "run", "streamlit", "run", "app/main.py",
    "--server.address", "127.0.0.1", "--server.headless", "true"
)
