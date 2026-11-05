# Política de segurança

## Como reportar uma vulnerabilidade

Não abra uma issue pública. Use **Security → Report a vulnerability** neste repositório (aviso privado) e descreva o problema e como reproduzi-lo.

## Princípios do projeto

- **Somente leitura na AWS.** As roles (`FinOpsReadOnly` e `FinOpsGitHubReport`) não têm permissão de escrita, e a interface só aceita GET.
- **Nenhuma chave de acesso.** Credenciais temporárias via `aws login`, `sts:AssumeRole` ou OIDC.
- **Interface só local.** O servidor escuta em `127.0.0.1` por padrão, com Content-Security-Policy `default-src 'self'`.
- **Nada sensível no Git.** IDs de conta, cache e exportações ficam em arquivos ignorados; o pre-commit bloqueia chaves privadas e credenciais AWS.
- **Dependências vigiadas.** O Dependabot propõe atualizações semanais, e o CodeQL analisa o código quando o repositório é público.
