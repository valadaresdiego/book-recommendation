# Abre o Recomendador (SPEC §10): sobe o banco, roda a atualização e abre o app no navegador.
# Roda só quando o Leitor abre o app (scripts/abrir.cmd). Fechar esta janela encerra o app.
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
New-Item -ItemType Directory -Force "logs" | Out-Null
$log = "logs/atualizar-$(Get-Date -Format yyyy-MM-dd).log"
$endereco = "http://127.0.0.1:8501"
$env:PYTHONIOENCODING = "utf-8"  # o log é UTF-8; sem isto, o Python grava na página do console

function AppNoAr {
    try {
        (Invoke-WebRequest -UseBasicParsing "$endereco/_stcore/health" -TimeoutSec 2).StatusCode -eq 200
    } catch { $false }
}

# Via cmd: no PowerShell 5.1, redirecionar o stderr de um executável grava cada linha no log
# como erro (NativeCommandError), mesmo quando o comando dá certo.
function Registrar([string]$comando) {
    Add-Content $log "[$(Get-Date -Format HH:mm:ss)] $comando"
    cmd /c "$comando >> `"$log`" 2>&1"
    $codigo = $LASTEXITCODE
    Add-Content $log "[$(Get-Date -Format HH:mm:ss)] codigo de saida: $codigo"
    return $codigo
}

# Já aberto (outra janela): só mostra no navegador.
if (AppNoAr) {
    Start-Process $endereco
    exit 0
}

# 1. Docker Desktop: abre se estiver fechado e espera responder (até 120 s).
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Abrindo o Docker Desktop..."
    $bin = Split-Path -Parent (Get-Command docker -ErrorAction SilentlyContinue).Source
    $desktop = @(
        (Join-Path $bin "..\..\Docker Desktop.exe"),
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($desktop) { Start-Process $desktop }
    $limite = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep -Seconds 3
        docker info *> $null
    } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $limite)
}

Write-Host "Subindo o banco..."
if ((Registrar "docker compose up -d --wait db") -ne 0) {
    Write-Host "O banco não subiu. Veja $log" -ForegroundColor Red
    Read-Host "Enter para fechar"
    exit 1
}

# 2. Atualização. O app abre mesmo que este passo falhe.
Write-Host "Atualizando..."
if ((Registrar "uv run python -m recomendador atualizar") -ne 0) {
    Write-Host "A atualização falhou (o app abre assim mesmo). Veja $log" -ForegroundColor Yellow
}

# 3. App só em localhost, nesta janela; o navegador abre quando ele responder.
Write-Host "Abrindo o app em $endereco (feche esta janela para encerrar)."
$app = Start-Process -NoNewWindow -PassThru -FilePath "uv" -ArgumentList @(
    "run", "streamlit", "run", "app/main.py",
    "--server.address", "127.0.0.1", "--server.port", "8501", "--server.headless", "true"
)
$limite = (Get-Date).AddSeconds(60)
while (-not (AppNoAr) -and -not $app.HasExited -and (Get-Date) -lt $limite) {
    Start-Sleep -Seconds 1
}
if (AppNoAr) { Start-Process $endereco }
$app.WaitForExit()
