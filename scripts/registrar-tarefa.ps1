# Registra a tarefa "Recomendador de Livros" no Agendador do Windows (logon do usuário).
$script = Join-Path $PSScriptRoot "iniciar.ps1"
$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -TaskName "Recomendador de Livros" -Action $acao -Trigger $gatilho `
    -Description "Sobe o banco, atualiza Vizinhos pendentes e abre o app em 127.0.0.1:8501" -Force
