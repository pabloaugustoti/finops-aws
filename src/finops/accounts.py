"""Configuração das contas monitoradas (arquivo TOML).

O arquivo real (`accounts.local.toml`) fica fora do Git porque contém IDs de
conta. O `accounts.example.toml` versionado mostra o formato.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_ACCOUNT_ID = re.compile(r"^\d{12}$")


class ConfigError(ValueError):
    """Erro no arquivo de configuração das contas."""


@dataclass(frozen=True)
class Account:
    name: str
    account_id: str
    role_name: str = "FinOpsReadOnly"
    external_id: str | None = None

    @property
    def role_arn(self) -> str:
        return f"arn:aws:iam::{self.account_id}:role/{self.role_name}"


@dataclass(frozen=True)
class AccountsConfig:
    hub_profile: str
    accounts: list[Account]


def load_accounts(path: Path) -> AccountsConfig:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"arquivo de contas não encontrado: {path}") from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"TOML inválido em {path}: {error}") from None

    hub_profile = data.get("hub", {}).get("profile")
    if not hub_profile:
        raise ConfigError("defina [hub] profile = \"...\" com o perfil do AWS CLI da conta hub")

    raw_accounts = data.get("accounts", [])
    if not raw_accounts:
        raise ConfigError("nenhuma conta em [[accounts]]")

    accounts: list[Account] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_accounts, start=1):
        name = str(raw.get("name", "")).strip()
        account_id = str(raw.get("account_id", "")).strip()
        if not name:
            raise ConfigError(f"conta #{index}: 'name' é obrigatório")
        if not _ACCOUNT_ID.match(account_id):
            raise ConfigError(f"conta '{name}': 'account_id' precisa ter 12 dígitos")
        if name in seen:
            raise ConfigError(f"conta '{name}' aparece mais de uma vez")
        seen.add(name)
        accounts.append(
            Account(
                name=name,
                account_id=account_id,
                role_name=raw.get("role_name", "FinOpsReadOnly"),
                external_id=raw.get("external_id") or None,
            )
        )
    return AccountsConfig(hub_profile=hub_profile, accounts=accounts)
