# 01: Preparação do ambiente

**Data:** 2026-11-04

## Objetivo

Deixar o computador pronto para desenvolver e definir o escopo do projeto.

## O que foi feito

- Instalados a partir dos sites oficiais, com a assinatura digital de cada instalador conferida:
  - Git 2.56.0
  - Python 3.14.10. Escolhi o 3.14 em vez do 3.15, que é novo demais: algumas bibliotecas ainda podem não ter suporte a ele.
  - AWS CLI 2.39.4
- Criado o repositório com um `.gitignore` focado em não vazar credenciais nem dados de custo.
- Definidos a arquitetura e o roteiro em fases (ver [README](../../README.md)).

## O que aprendi

- **Conta gratuita da AWS:** contas novas podem escolher o *Free plan*, com até US$ 200 em créditos válidos por 6 meses. Alguns serviços são limitados nesse plano.
- **A Cost Explorer API é paga:** cada requisição custa US$ 0,01. Um coletor mal feito, que consulta a API a cada atualização do dashboard, gera custo. Por isso o projeto terá **cache**.
- **Padrão multi-conta:** em vez de guardar chaves de cada conta, cada conta expõe uma *role* somente leitura e o coletor usa `sts:AssumeRole`.

## Próximo passo

Criar a conta AWS seguindo o [checklist](../checklist-conta-aws.md).
