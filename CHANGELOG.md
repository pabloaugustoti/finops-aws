# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [1.1.0] - 2026-11-04

### Adicionado
- Template CloudFormation do provedor OIDC do GitHub + role `FinOpsGitHubReport` (somente leitura, restrita a este repositório e à branch `main`).
- Workflow "relatório semanal" (segundas, 08:00 BRT) com credenciais via OIDC; fica inativo até existir a variável `AWS_ROLE_ARN`.
- Perfil especial `ambiente`: usa as credenciais do ambiente (`AWS_*`), como as da CI.
- Scripts para o Agendador do Windows: `scripts/relatorio-semanal.ps1` e `scripts/agendar-relatorio.ps1`.

## [1.0.0] - 2026-11-04

### Adicionado
- README de portfólio: capturas de tela (claro, escuro e celular), destaques técnicos, início rápido e histórico do projeto.
- Versão do README em inglês (`README.en.md`).
- Licença MIT e este changelog.
- Parâmetros de URL na interface (`?aba=recomendacoes&tema=escuro&dias=90&fonte=exemplo`) para abrir direto numa visão.

## [0.8.0] - 2026-11-04

### Adicionado
- ruff (lint + formatação), mypy, cobertura mínima de 90% e pre-commit.
- Job "lint, formatação e tipos" na CI e tabela de cobertura no resumo de cada execução.

### Alterado
- Ambiente de desenvolvimento fixado no Python 3.14.

## [0.7.0] - 2026-11-04

### Adicionado
- Interface web feita à mão (HTML, CSS e JavaScript puros, gráficos em SVG) servida por `http.server` em `127.0.0.1`.
- API JSON: `/api/custos`, `/api/recomendacoes`, `/api/relatorio`.

### Removido
- Dashboard em Streamlit (e as dependências Streamlit, pandas e Altair).

## [0.6.0] - 2026-11-04

### Adicionado
- Detecção de anomalias por mediana + MAD (`finops anomalias`).
- Relatório semanal em Markdown (`finops relatorio`).
- CI no GitHub Actions (Python 3.12 e 3.14).

## [0.5.0] - 2026-11-04

### Adicionado
- Inventário multi-região (EC2, EBS, snapshots, IPs elásticos, CPU do CloudWatch).
- 7 regras de recomendação com economia mensal estimada (`finops recomendacoes`).

### Corrigido
- Contagem dupla entre gp2→gp3 e instância parada; estimativa de snapshots incrementais.
- `NoRegionError` na renovação das credenciais do `aws login`.
- Regiões negadas por SCP agora aparecem como "bloqueadas", não como erro.

## [0.4.0] - 2026-11-04

### Adicionado
- Primeiro dashboard, em Streamlit.

## [0.3.0] - 2026-11-04

### Adicionado
- Role `FinOpsReadOnly` em CloudFormation e coleta de várias contas via `sts:AssumeRole`.
- `accounts.local.toml` e o comando `finops verificar-contas`.

## [0.2.0] - 2026-11-04

### Adicionado
- Coletor do Cost Explorer com paginação, cache em disco e dados de exemplo (`finops resumo`).

## [0.1.0] - 2026-11-04

### Adicionado
- Estrutura do projeto, conta AWS, budget, Cost Explorer e acesso pelo CLI com `aws login`.

[1.1.0]: https://github.com/pabloaugustoti/finops-aws/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.8.0...v1.0.0
[0.8.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/pabloaugustoti/finops-aws/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/pabloaugustoti/finops-aws/releases/tag/v0.1.0
