# Checklist: criação e proteção da conta AWS

Siga na ordem. Marque cada item ao concluir.

> **Nota (2026-11-04):** a conta foi criada pela **"nova experiência" da AWS**, com login pelo GitHub, Free plan com US$ 100 e 182 dias, região `us-east-2`. Os passos abaixo foram ajustados a ela.

## 1. Criar a conta

- [x] Criar a conta em https://aws.amazon.com/free entrando com o GitHub
- [x] Escolher o **Free plan**, com créditos e sem cobrança durante o período

## 2. Proteger o login

- [ ] O login é a conta do GitHub, então o **2FA do GitHub** precisa estar ativo: *Settings > Password and authentication*
- [ ] Nunca criar *access keys* de longa duração

## 3. Acesso pelo CLI

- [ ] ⚠️ **Não ativar o IAM Identity Center nem o AWS Organizations.** Criar um Organization numa conta do Free plan muda a conta para o plano pago e cancela os créditos.
- [ ] No PC, fazer o login pelo navegador: `aws login --profile finops-lab`
- [ ] Testar: `aws sts get-caller-identity --profile finops-lab`

## 4. Primeiros passos de FinOps

- [ ] **Billing > Budgets:** criar um orçamento mensal de US$ 1 a US$ 5 com alerta por e-mail
- [ ] **Billing > Cost Explorer:** ativar. Os dados aparecem em até 24 h.
- [ ] **Billing > Preferências:** ativar alertas do Free Tier
- [ ] **Billing > Cost allocation tags:** depois que existirem recursos com tags, ativar as tags `Project` e `Environment`

## Nunca fazer

- Commitar arquivos de `~/.aws/` ou qualquer *access key* no Git
- Deixar recursos ligados "para testar depois" sem budget configurado
