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
docker compose up -d --wait db *>> $log

# 2. Atualização. O app sobe mesmo que este passo falhe.
uv run python -m recomendador atualizar *>> $log

# 3. App só em localhost.
Start-Process -WindowStyle Hidden -FilePath "uv" -ArgumentList @(
    "run", "streamlit", "run", "app/main.py",
    "--server.address", "127.0.0.1", "--server.headless", "true"
)
