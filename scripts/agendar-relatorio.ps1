<#
.SYNOPSIS
    Cria (ou remove) a tarefa do Agendador do Windows que gera o relatório toda segunda às 08:00.

.EXAMPLE
    .\scripts\agendar-relatorio.ps1            # cria ou atualiza a tarefa
    .\scripts\agendar-relatorio.ps1 -Remover   # remove a tarefa

.NOTES
    A tarefa roda como o seu usuário, só quando você está logado (é o seu "aws login"
    que dá acesso à AWS). Se o PC estiver desligado na hora, ela roda assim que possível.
#>
param([switch]$Remover)

$nome = "FinOps AWS - relatorio semanal"

if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false
    Write-Output "Tarefa removida: $nome"
    exit 0
}

$script = Join-Path $PSScriptRoot "relatorio-semanal.ps1"
$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$gatilho = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 8am
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config `
    -Description "Gera o relatório semanal de FinOps em data\exports\relatorios (projeto finops-aws)." -Force | Out-Null
Write-Output "Tarefa criada: $nome (toda segunda às 08:00)"
