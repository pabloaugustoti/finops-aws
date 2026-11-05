# 10: README de portfólio e versão 1.0

**Data:** 2026-11-04

## Objetivo

Fazer o repositório se explicar em 30 segundos para quem chega nele: o que faz, como fica na tela, como rodar e quais decisões técnicas mostram maturidade.

## O que foi feito

- **README reescrito como vitrine**, nesta ordem:
  1. o que é, em duas frases;
  2. uma captura grande da interface;
  3. o que faz (custos, anomalias, economia, várias contas, relatório);
  4. capturas no tema escuro e no celular;
  5. início rápido em 3 comandos, sem precisar de conta AWS;
  6. **destaques técnicos**: cada decisão com o motivo e o link para o código;
  7. arquitetura, comandos, uso com contas reais, segurança e qualidade;
  8. tabela "como o projeto foi construído", ligando cada versão ao diário.
- **Capturas de tela** geradas pelo Microsoft Edge em modo *headless* contra a interface local, com os dados de exemplo: custos no tema claro, recomendações no escuro e a visão de celular.
- **Parâmetros de URL na interface** (`?aba=recomendacoes&tema=escuro&dias=90&fonte=exemplo`), para gerar as capturas de forma reproduzível e compartilhar links que já abrem na visão certa.
- **README em inglês** (`README.en.md`), para vagas internacionais.
- **Licença MIT**, **CHANGELOG** no formato *Keep a Changelog* e versão **1.0.0** no `pyproject.toml`.
- **Tags e releases** v0.1.0 a v1.0.0 no GitHub, cada uma apontando para o merge da etapa.

## Problemas encontrados

| Problema | Solução |
|---|---|
| A captura de "celular" com 390 px saiu cortada à direita | O Edge headless tem largura mínima de janela: a página era desenhada mais larga e depois recortada. Usei 500 px, que ainda mostra o layout de uma coluna |
| Sobra em branco no fim da captura longa | Ajustei a altura da janela ao conteúdo |
| `license = "MIT"` no `pyproject.toml` exige setuptools recente | Versão mínima do setuptools subiu para 77 (PEP 639) |

## O que aprendi

- Um README de portfólio é **produto**: o leitor decide em segundos se continua. Imagem primeiro, detalhes depois.
- "Destaques técnicos" com **o porquê** de cada decisão valem mais do que uma lista de tecnologias.
- Gerar as capturas por comando (e não à mão) deixa fácil atualizá-las quando a interface mudar.
