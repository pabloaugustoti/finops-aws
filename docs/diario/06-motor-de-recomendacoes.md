# 06: Motor de recomendações

**Data:** 2026-11-04

## Objetivo

Sair de "quanto gastamos" para **"onde dá para economizar"**: encontrar desperdício nos recursos das contas e estimar quanto cada ação economiza por mês.

## O que foi feito

- **Inventário via API** (`inventory.py`): volumes EBS, snapshots, IPs elásticos e instâncias EC2, com a CPU dos últimos 14 dias vinda do CloudWatch.
  - varre **todas as regiões habilitadas em paralelo** (ou só as passadas em `--regioes`);
  - usa a mesma role `FinOpsReadOnly`; as chamadas `Describe*` do EC2 são gratuitas.
- **Tabela de preços de referência** (`pricing.py`, us-east-1 sob demanda).
- **7 regras** (`recommendations.py`), cada uma uma função pura e testável:

| Regra | Quando dispara | Economia estimada |
|---|---|---|
| Instância ociosa | CPU média < 5% e pico < 10% em 14 dias | ~50% do preço (reduzir um tamanho) |
| Volume EBS sem uso | volume `available` (sem instância) | custo total do volume |
| IP elástico sem uso | IP alocado e não associado | US$ 3,65/mês (IPv4 público) |
| Instância parada | parada há 7 dias ou mais | custo dos discos que continuam cobrados |
| gp2 → gp3 | volume gp2 em uso | diferença de preço, incluindo IOPS extras quando o gp2 é grande |
| Snapshot antigo | mais de 90 dias (órfão = volume de origem excluído) | tamanho × US$ 0,05, ajustado por serem incrementais |
| Sem tags | falta `Project` ou `Environment` | governança, sem economia direta |

- **CLI**: `python -m finops recomendacoes`, com o resumo por tipo, as maiores economias e o **comando exato** para agir. Também exporta CSV.
- **Dashboard**: nova aba **💡 Recomendações**, com indicadores (economia/mês e /ano), gráfico por tipo e tabela filtrável.
- **Dados de exemplo com desperdício proposital** nas 3 contas fictícias. As 7 regras disparam.
- **62 testes** (17 novos), incluindo a coleta via API simulada com o `Stubber`.

## Resultado

Dados de exemplo: **US$ 297,38/mês** (US$ 3.568,56/ano) em 16 oportunidades, mais 9 recursos sem tags.

Conta real: inventário vazio, sem desperdício, e uma descoberta (abaixo).

## Descoberta: a conta vive dentro de uma organização com SCP

Ao varrer todas as regiões, 16 de 17 voltaram com:

> `explicit deny in a service control policy: arn:aws:organizations::<outra-conta>:policy/...`

A conta da "nova experiência" da AWS fica dentro de um **AWS Organization gerenciado pela própria AWS**, com uma **SCP** que só permite usar `us-east-2`. Uma SCP é um limite que vale **acima** do IAM: nem a role de leitura consegue olhar as outras regiões.

**Ajuste no código:** regiões negadas por SCP aparecem como "bloqueadas (ignoradas)" numa linha só, separadas de erros reais.

## Problemas encontrados

| Problema | Solução |
|---|---|
| Economia contada duas vezes: o volume de uma instância parada também aparecia como "migrar para gp3" | A regra gp2→gp3 ignora volumes de instâncias que já vão ser encerradas |
| Snapshots superestimados: 3 snapshots do mesmo volume de 1.500 GB somavam US$ 225 | Snapshots são incrementais: quando há vários do mesmo volume, cada um é estimado em 20% do tamanho. A economia caiu de US$ 484 para US$ 297, um número mais honesto |
| `You must specify a region` depois de cerca de 1 h de uso | A renovação automática das credenciais do `aws login` precisa de região, e o perfil não tinha uma. A sessão agora usa us-east-1 quando o perfil não define região |
| 16 regiões com `UnauthorizedOperation` | É uma SCP da organização, não falta de permissão. Agora aparecem como "bloqueadas por SCP" |

## O que aprendi

- **Estimar economia exige cuidado com contagem dupla e com como o serviço cobra** (snapshots incrementais, IOPS do gp3). Um número inflado tira a credibilidade de um relatório de FinOps.
- **Toda recomendação precisa de uma ação concreta**: o comando ou o passo, não só "isso está caro".
- **SCP × IAM**: a permissão efetiva é a interseção dos dois. Uma role com `ec2:Describe*` ainda é negada se a SCP bloquear a região.
- **Bugs que só aparecem com o tempo**, como o token que expira depois de 1 h, só se descobrem rodando contra a conta real, e não nos testes.

## Próximo passo

Fase 6 (avançado): Cost and Usage Report (CUR 2.0) com Athena para custo por recurso, detecção de anomalias (o pico de EC2 dos dados de exemplo) e alertas.
