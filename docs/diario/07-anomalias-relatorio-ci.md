# 07: Anomalias, relatório semanal e CI

**Data:** 2026-11-04

## Objetivo

Fechar o ciclo de FinOps: além de mostrar custos e oportunidades, **avisar quando algo foge do padrão** e **comunicar** isso de forma recorrente. E garantir a qualidade do código com testes automáticos a cada push.

## Escopo: o que entrou e o que ficou para depois

| Item | Status | Motivo |
|---|---|---|
| Detecção de anomalias | ✅ | Funciona com qualquer fonte, sem custo extra |
| Relatório semanal | ✅ | Markdown serve para e-mail, Slack, issue ou wiki |
| CI (GitHub Actions) | ✅ | Testes em todo push e PR |
| CUR 2.0 + Athena | ⏭️ adiado | Cria infraestrutura paga (S3, Athena), o export roda em `us-east-1` (bloqueada pela SCP desta conta) e a conta ainda tem custo zero |

## Detecção de anomalias

**Método**: para cada série diária (conta + serviço), compara o dia com os 14 dias anteriores usando **mediana** e **MAD** (desvio absoluto mediano):

```
z robusto = (custo do dia − mediana) / (MAD × 1,4826)
```

O dia é anômalo se atender **às três** condições:
1. `z ≥ 3,5`: estatisticamente fora do padrão;
2. impacto `≥ US$ 1`: ignora centavos (0,01 → 0,05 é 5x, mas não importa);
3. aumento `≥ 30%`: ignora oscilações pequenas de séries grandes.

Dias anômalos seguidos viram **um evento**, com o custo extra total.

**Por que mediana e MAD, e não média e desvio padrão?** O próprio pico infla a média e o desvio padrão e "esconde" a anomalia nos dias seguintes. Mediana e MAD quase não se mexem com valores extremos.

**Resultado nos dados de exemplo**: encontrou **exatamente** o pico de EC2 plantado (24 a 26/10, US$ 68,07 de custo extra, z = 25,3) e **nenhum falso positivo** nas outras 23 séries, mesmo com ruído de ±8%, efeito de fim de semana e crescimento diário do S3.

**No dashboard**: um marcador ⚠ sobre as barras dos dias anômalos (ícone + rótulo, não só cor) e um cartão por evento.

## Relatório semanal

`python -m finops relatorio --saida relatorio.md` gera um Markdown com:
- custo da semana × semana anterior, mês até ontem e previsão;
- os maiores serviços da semana, com a variação;
- as anomalias dos últimos 30 dias;
- as maiores oportunidades de economia e os recursos sem tags.

## CI no GitHub Actions

`.github/workflows/testes.yml` roda em todo push na `main` e em todo PR:
- `pytest` em **Python 3.12 e 3.14**;
- teste de fumaça de todos os comandos da CLI com dados de exemplo;
- publica o relatório semanal de exemplo como artefato.

A CI **não tem credenciais da AWS** (`permissions: contents: read`): tudo roda com os dados de exemplo e o Stubber.

## Problemas encontrados

| Problema | Solução |
|---|---|
| No dashboard, "US$ 68,07 ... US$ 45,79" virou fórmula matemática | O Markdown do Streamlit trata pares de `$` como LaTeX. Escapei o `$` (`\$`) |
| Aviso de obsoleto do Streamlit: `use_container_width` | Trocado por `width="stretch"` |

## O que aprendi

- **Estatística robusta** (mediana/MAD) é simples e funciona muito bem para séries de custo, que têm picos e sazonalidade semanal.
- **Alertar exige filtros de relevância**: só o critério estatístico geraria alarmes por centavos.
- **Saber dizer "agora não"**: o CUR é o padrão enterprise, mas montar infraestrutura paga numa conta sem custo e com região bloqueada seria complexidade sem retorno. Ficou documentado como próximo passo.

## Próximos passos

- CUR 2.0 + Athena, quando houver uma conta com custo real e acesso a `us-east-1`;
- envio automático do relatório (SNS ou GitHub Actions com OIDC, sem chaves);
- comparar o detector com o AWS Cost Anomaly Detection.
