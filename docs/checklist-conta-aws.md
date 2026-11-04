# Checklist: criação e proteção da conta AWS

Siga na ordem. Marque cada item ao concluir.

## 1. Criar a conta

- [ ] Acessar https://aws.amazon.com/free e criar a conta com um e-mail exclusivo para ela
- [ ] Escolher o **Free plan**, com créditos e sem cobrança durante o período
- [ ] Região padrão sugerida: `us-east-1`. É onde ficam as APIs de billing e costuma ser a mais barata.

## 2. Proteger o usuário root

- [ ] Ativar **MFA** no root: menu da conta > *Security credentials*
- [ ] Não criar *access keys* para o root
- [ ] Guardar a senha do root num gerenciador de senhas

## 3. Criar um acesso de uso diário

- [ ] Ativar o **IAM Identity Center**
- [ ] Criar um usuário para você e dar o *permission set* `AdministratorAccess` na conta
- [ ] Ativar MFA nesse usuário
- [ ] No PC, configurar o CLI: `aws configure sso`. O nome de perfil sugerido é `finops-lab`.
- [ ] Testar: `aws sts get-caller-identity --profile finops-lab`

## 4. Primeiros passos de FinOps

- [ ] **Billing > Budgets:** criar um orçamento mensal de US$ 1 a US$ 5 com alerta por e-mail
- [ ] **Billing > Cost Explorer:** ativar. Os dados aparecem em até 24 h.
- [ ] **Billing > Preferências:** ativar alertas do Free Tier
- [ ] **Billing > Cost allocation tags:** depois que existirem recursos com tags, ativar as tags `Project` e `Environment`

## Nunca fazer

- Commitar arquivos de `~/.aws/` ou qualquer *access key* no Git
- Deixar recursos ligados "para testar depois" sem budget configurado
