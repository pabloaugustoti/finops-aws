# 02: Conta AWS e primeiro acesso pela API

**Data:** 2026-11-04

## Objetivo

Criar a conta AWS, ativar as ferramentas básicas de custo e fazer a primeira consulta de custos pela linha de comando.

## O que foi feito

1. **Conta criada pela "nova experiência" da AWS**, com login pelo GitHub e Free plan (US$ 100 em créditos, 182 dias).
2. **Budget mensal** `finops-lab-mensal` de US$ 5, com alertas em 85% e 100% do gasto real e em 100% do gasto previsto.
3. **Cost Explorer** ativado.
4. **Acesso pelo CLI** com `aws login --profile finops-lab`, que gera credenciais temporárias pelo navegador, sem nenhuma *access key* salva.
5. **Primeiras chamadas de API:**

```powershell
# Quem sou eu?
aws sts get-caller-identity --profile finops-lab

# Custos do mês por serviço (Cost Explorer: US$ 0,01 por chamada)
aws ce get-cost-and-usage --profile finops-lab --region us-east-1 `
  --time-period Start=2026-11-01,End=2026-11-05 `
  --granularity MONTHLY --metrics UnblendedCost `
  --group-by Type=DIMENSION,Key=SERVICE

# Budgets da conta
aws budgets describe-budgets --profile finops-lab --region us-east-1 --account-id <ID_DA_CONTA>
```

Resultado: custo de **US$ 0** (`"Estimated": true`, porque o mês ainda não fechou) e o budget aparecendo com gasto 0 e limite 5.

## Decisões

| Decisão | Motivo |
|---|---|
| **Não usar o "Kit de Ferramentas do Agente"** oferecido no cadastro | Ele dá a um agente de IA acesso de escrita à conta. Num projeto de FinOps, o padrão é **somente leitura**. |
| **Não ativar o IAM Identity Center / Organizations** | Criar um Organization numa conta do Free plan muda a conta para o plano pago e cancela os créditos. |
| Usar `aws login` em vez de *access keys* | As credenciais são temporárias e renovadas sozinhas, e nada sensível fica no disco do projeto. |

## O que aprendi

- **Na nova experiência não há "root com senha"**: o login é a conta do GitHub, então o 2FA que importa é o do GitHub.
- **O login do CLI assume a role `AccountFullAccessRole`**, que tem acesso total. Para a aplicação final vamos criar uma role **só de leitura de custos** (princípio do menor privilégio).
- **APIs de billing são globais**: Cost Explorer e Budgets respondem em `us-east-1`, mesmo com a conta usando `us-east-2`.
- **Os campos do console são parâmetros da API**: intervalo de datas = `TimePeriod`, granularidade = `Granularity`, agrupar por = `GroupBy`, filtros = `Filter`.
- **`"Estimated": true`** indica que o valor do período ainda pode mudar. Só vira definitivo depois do fechamento da fatura.

## Próximo passo

Fase 2: coletor em Python (boto3) que faz essas consultas, guarda o resultado em cache e tem um modo de dados de exemplo enquanto a conta não tem custos.
