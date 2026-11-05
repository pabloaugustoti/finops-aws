# 03: Coletor do Cost Explorer com cache

**Data:** 2026-11-04

## Objetivo

Sair dos comandos manuais do AWS CLI e ter um coletor em Python que consulta custos, evita gastar com chamadas repetidas e funciona mesmo sem dados reais.

## O que foi feito

- Pacote Python `finops` (`src/finops/`), instalado em modo editável num `.venv`.
- **`CostExplorer`**: chama `GetCostAndUsage` (custo diário por serviço) e `GetCostForecast` (previsão até o fim do mês), segue a paginação (`NextPageToken`) e converte as respostas em objetos `CostRecord`/`Forecast`.
- **Cache em disco** (`data/cache/`, fora do Git):
  - período **fechado** → resposta guardada para sempre (o valor não muda mais);
  - período com valores **estimados** (mês aberto) → expira em 6 h.
- **Dados de exemplo** (`SampleCostExplorerClient`): imita a API com as mesmas respostas em formato JSON, então o resto do código não sabe se os dados são reais. Inclui padrões de propósito:
  - EC2 mais barato no fim de semana;
  - S3 e Lambda crescendo um pouco a cada dia;
  - **um pico de EC2 entre 10 e 12 dias atrás**, simulando uma instância esquecida ligada. Vai servir de teste para a detecção de anomalias.
- **CLI**: `python -m finops resumo`, com total, média diária, mês até ontem, previsão de fechamento, top serviços e um mini gráfico de custo diário. Também exporta CSV.
- **23 testes automatizados** com `pytest` e o `Stubber` do botocore, que simula as respostas da AWS sem acesso à rede e sem custo.

## Resultado na conta real

```
Total no período ........ US$ 0,00
Previsão de fechamento .. indisponível (histórico insuficiente)
Chamadas pagas à API do Cost Explorer nesta execução: 1 (~US$ 0,01)
```

Na segunda execução: **0 chamadas pagas**, porque tudo veio do cache.

## Problemas encontrados

| Problema | Solução |
|---|---|
| `MissingDependencyException`: credenciais do `aws login` exigem `botocore[crt]` | Dependência trocada para `boto3[crt]` no `pyproject.toml` |
| Previsão numa conta nova devolve `DataUnavailableException` | Tratada como "indisponível" e guardada no cache para não pagar de novo |
| Chamadas que dão erro também são cobradas, mas não entravam na contagem | O contador passou a somar **antes** de chamar a API |

## O que aprendi

- **Custo de observar custo**: o próprio Cost Explorer cobra por requisição. Cache não é otimização prematura, é requisito.
- **Dados "estimados"**: o mês corrente só fica definitivo quando a fatura fecha. Isso define o que pode ou não ser guardado em cache para sempre.
- **Datas em UTC**: o faturamento da AWS usa dias em UTC. À noite no Brasil, "hoje" para a AWS já é amanhã.
- **Fim exclusivo**: na API, `End=2026-11-05` traz dados até 2026-11-04.
- **Injeção de dependência** (passar o cliente da AWS como parâmetro) permite trocar AWS real, dados de exemplo e stubs de teste sem mudar a lógica.

## Próximo passo

Fase 3: várias contas, com um arquivo de configuração e `sts:AssumeRole` em roles **somente leitura**. Isso inclui criar a role de leitura de custos que vai substituir o uso da `AccountFullAccessRole`.
