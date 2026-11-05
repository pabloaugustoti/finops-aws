<#
.SYNOPSIS
    Gera o relatório semanal de FinOps da conta real e salva em data/exports/relatorios/.

.DESCRIPTION
    Pensado para o Agendador de Tarefas do Windows (ver scripts/agendar-relatorio.ps1).
    Usa o login do AWS CLI (aws login) e a role somente leitura FinOpsReadOnly via accounts.local.toml.
    Nenhuma chave de acesso é usada ou guardada.

    Se o login tiver expirado (renovação a cada ~90 dias), grava um aviso em
    ULTIMO-ERRO.txt na mesma pasta: rode "aws login --profile finops-lab" e pronto.
#>
param(
    [ValidateSet("contas", "aws", "exemplo")]
    [string]$Fonte = "contas",
    [string]$Regioes = "us-east-2"
)

$ErrorActionPreference = "Stop"
$projeto = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projeto ".venv\Scripts\python.exe"
$pasta = Join-Path $projeto "data\exports\relatorios"
$data = Get-Date -Format "yyyy-MM-dd"
$saida = Join-Path $pasta "relatorio-$data.md"
$log = Join-Path $pasta "execucoes.log"
$erro = Join-Path $pasta "ULTIMO-ERRO.txt"

New-Item -ItemType Directory -Force $pasta | Out-Null
Set-Location $projeto

$argumentos = @("-m", "finops", "relatorio", "--fonte", $Fonte, "--saida", $saida)
if ($Regioes) { $argumentos += @("--regioes", $Regioes) }

$inicio = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$resultado = & $python @argumentos 2>&1 | Out-String
$codigo = $LASTEXITCODE

if ($codigo -eq 0 -and (Test-Path $saida)) {
    Add-Content -Path $log -Encoding utf8 -Value "$inicio  OK    $saida"
    if (Test-Path $erro) { Remove-Item $erro -Force }
    exit 0
}

$mensagem = @"
Falha ao gerar o relatório semanal em $inicio (código $codigo).

Causa mais comum: o login do AWS CLI expirou. Rode no terminal:
    aws login --profile finops-lab

Saída do comando:
$resultado
"@
Set-Content -Path $erro -Encoding utf8 -Value $mensagem
Add-Content -Path $log -Encoding utf8 -Value "$inicio  ERRO  código $codigo (detalhes em ULTIMO-ERRO.txt)"
exit $codigo
