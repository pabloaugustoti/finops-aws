# 05: Dashboard em Streamlit

**Data:** 2026-11-04

## Objetivo

Transformar o resumo de texto num **dashboard interativo** que qualquer pessoa entenda em poucos segundos: quanto gastamos, onde, se está subindo e como o mês vai fechar.

## O que foi feito

- **App Streamlit** (`python -m finops dashboard`, em http://localhost:8501):
  - **barra lateral**: fonte de dados (exemplo, minha conta ou várias contas), período (7 a 90 dias) e botão de recarregar;
  - **filtro de contas** acima dos gráficos;
  - **indicadores**: total do período (com a variação dos últimos 7 dias contra os 7 anteriores), média diária, mês até ontem e previsão de fechamento;
  - **custo diário por serviço** em barras empilhadas, com os 5 maiores serviços e o restante em "Outros";
  - **rankings por conta e por serviço**, com o valor direto na barra;
  - **mês atual**: linha do acumulado real e linha tracejada da previsão até o último dia do mês;
  - **tabela detalhada** com download em CSV.
- **`sources.py`**: a lógica das fontes de dados saiu da CLI e passou a ser compartilhada com o dashboard.
- **`dashboard/data.py`**: preparação dos dados com pandas, **separada do Streamlit**, para poder ser testada.
- **45 testes** (10 novos).

## Decisões de design

| Decisão | Motivo |
|---|---|
| A coleta sempre busca **90 dias**, e o filtro de período só recorta localmente | Mudar o filtro não gera nova chamada paga ao Cost Explorer |
| `st.cache_data` (1 h) + cache em disco | Cada interação no Streamlit reexecuta o script; sem cache, cada clique custaria US$ 0,01 |
| Cor fixa por serviço, calculada **sem** o filtro de conta | A cor segue o serviço, não a posição: filtrar não "repinta" o EC2 de outra cor |
| Paleta categórica validada para daltonismo, com versões clara e escura | Acessibilidade. O modo escuro tem cores próprias, não é uma simples inversão |
| Sem gráfico de dois eixos | Valores de escalas diferentes ficam em gráficos separados |
| Variação semanal com cor invertida (alta = vermelho) | Em custos, aumentar é ruim |
| Eixos e valores no padrão brasileiro (1.234,56) | Leitura natural para o público do projeto |

## Verificação

Testado no navegador:
- modo claro e modo escuro;
- fonte de exemplo (3 contas, com o pico de EC2 visível no dia 26/10);
- conta real (US$ 0, com uma mensagem orientando a usar os dados de exemplo e **0 chamadas pagas**, porque a consulta veio do cache);
- sem erros no console.

## O que aprendi

- **O modelo do Streamlit reexecuta o script inteiro a cada interação.** Isso torna o cache obrigatório quando a fonte de dados é paga.
- **Separar a preparação dos dados da interface** permite testar a lógica sem abrir o navegador.
- **Previsão ≠ histórico**: mostrar a previsão como linha tracejada deixa claro o que é real e o que é estimativa.

## Próximo passo

Fase 5: motor de recomendações. Vai procurar volumes EBS gp2 que podem virar gp3, volumes e IPs elásticos sem uso, snapshots antigos, instâncias ociosas e recursos sem tags, mostrando a economia estimada de cada item.
