# 09: Qualidade de código

**Data:** 2026-11-04

## Objetivo

Garantir a qualidade **automaticamente**, sem depender de lembrar: padrão de estilo, checagem de tipos, cobertura de testes mínima e checagens antes de cada commit, tanto na máquina quanto na CI.

## O que foi feito

| Ferramenta | Configuração | Resultado |
|---|---|---|
| **ruff** (lint) | regras E, W, F, I, B, UP, SIM, C4, RET, PT, **S (segurança)** e N | 29 apontamentos → 0 |
| **ruff format** | linha de 120 caracteres | 16 arquivos padronizados |
| **mypy** | `check_untyped_defs`, `disallow_incomplete_defs`, `warn_return_any` | 10 erros → 0 |
| **coverage** | cobertura de linhas e ramos, `fail_under = 90` | **92%** |
| **pre-commit** | ruff, mypy, espaços sobrando, fim de arquivo, YAML/TOML, chave privada, credencial AWS, arquivo grande | todas passando |
| **.gitattributes** | `eol=lf` | fim dos avisos "LF will be replaced by CRLF" |

**Na CI**, um job novo de *lint, formatação e tipos* roda antes dos testes, e a cobertura aparece como tabela no resumo de cada execução do GitHub Actions.

## O que as ferramentas encontraram

Nenhum bug, mas pontos que valiam a pena:

- **`datetime.timezone.utc` → `datetime.UTC`**: a forma moderna (Python 3.11+), em 11 lugares.
- **Asserções compostas nos testes** (`assert a and b`): divididas, para o erro apontar exatamente o que falhou.
- **`pytest.raises(ValueError)` genérico**: passou a conferir a mensagem (`match=`). Antes, um `ValueError` qualquer faria o teste passar por engano.
- **`try/except` com `assert` dentro do teste**: trocado por `pytest.raises`, porque o padrão antigo passa silenciosamente se a exceção não acontecer.
- **Nome de exceção** `BadRequest` → `BadRequestError` (convenção PEP 8).
- **`random` sinalizado como inseguro** (regra S311): aqui é ruído para dados **fictícios**, não criptografia. Ficou com `# noqa: S311` e um comentário explicando o motivo.
- **Tipos**: funções sem tipo de retorno, um `Decimal | None` passado onde se esperava `Decimal` (no relatório semanal) e retornos `Any` vindos do cache.

## Problema encontrado: Python 3.15 no ambiente virtual

Ao instalar o pre-commit, o pip tentou **compilar** o PyYAML e falhou ("Microsoft Visual C++ 14.0 is required"). O ambiente `.venv` tinha sido criado com o **Python 3.15**, que também está instalado na máquina, e o PyYAML ainda não publica pacote pronto para ele.

**Solução**: recriei o `.venv` explicitamente com o Python 3.14, a versão escolhida no [diário 01](01-preparacao-ambiente.md) exatamente para evitar isso, e a mesma da CI.

**Lição**: criar o ambiente com o caminho do interpretador (`& 'C:\Program Files\Python314\python.exe' -m venv .venv`) em vez de confiar em qual `python` aparece primeiro no PATH.

## Observação honesta: uma falha que não se repetiu

Logo depois da formatação, uma execução da suíte teve **1 falha em 80**. Em seguida, **9 execuções seguidas passaram** e não consegui reproduzir. Pode ter sido algo do momento, como o arquivo sendo reescrito enquanto era importado. Fica registrado: se voltar a acontecer, a CI mostra qual teste foi.

## O que aprendi

- Ferramentas de qualidade **acham problemas de clareza e de testes frágeis** mais do que bugs, e isso também importa.
- `# noqa` sem explicação é dívida técnica; com o motivo ao lado, é uma decisão documentada.
- Fixar a versão do Python do projeto evita surpresas com versões novas demais para o ecossistema.
