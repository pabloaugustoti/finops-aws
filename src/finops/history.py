"""Histórico de custos em SQLite (biblioteca padrão).

O Cost Explorer cobra por consulta e o cache guarda respostas, não um histórico
consultável. Aqui cada coleta real é gravada linha a linha (dia, conta, serviço);
com o tempo o banco acumula meses de dados para ver tendências sem pagar a API
de novo. O arquivo fica em data/, fora do Git.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import TracebackType

from finops.models import CostRecord

DEFAULT_HISTORY_FILE = Path("data/historico.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS custos (
    dia            TEXT    NOT NULL,  -- AAAA-MM-DD (UTC, como o faturamento da AWS)
    conta          TEXT    NOT NULL,
    servico        TEXT    NOT NULL,
    custo          REAL    NOT NULL,  -- USD
    estimado       INTEGER NOT NULL,  -- 1 enquanto a fatura do mês não fecha
    atualizado_em  TEXT    NOT NULL,
    PRIMARY KEY (dia, conta, servico)
);
CREATE INDEX IF NOT EXISTS idx_custos_dia ON custos (dia);
"""


@dataclass(frozen=True)
class MonthTotal:
    month: str  # AAAA-MM
    amount: Decimal
    estimated: bool


@dataclass(frozen=True)
class Coverage:
    first_day: str | None
    last_day: str | None
    rows: int


class HistoryStore:
    def __init__(self, path: Path | str = DEFAULT_HISTORY_FILE) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(str(path))
        self._db.executescript(SCHEMA)

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def save(self, records: Iterable[CostRecord], now: datetime | None = None) -> int:
        """Grava (ou atualiza) as linhas; o dado mais recente da AWS sempre vence."""
        stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        rows = [(r.day.isoformat(), r.account, r.service, float(r.amount), int(r.estimated), stamp) for r in records]
        with self._db:
            self._db.executemany(
                """INSERT INTO custos (dia, conta, servico, custo, estimado, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (dia, conta, servico) DO UPDATE SET
                       custo = excluded.custo, estimado = excluded.estimado, atualizado_em = excluded.atualizado_em""",
                rows,
            )
        return len(rows)

    def monthly(self, accounts: list[str] | None = None) -> list[MonthTotal]:
        """Total por mês (das contas pedidas, ou de todas), do mais antigo para o mais recente."""
        where, params = "", []
        if accounts:
            where = f"WHERE conta IN ({', '.join('?' for _ in accounts)})"
            params = list(accounts)
        query = f"""SELECT substr(dia, 1, 7) AS mes, ROUND(SUM(custo), 2), MAX(estimado)
                    FROM custos {where} GROUP BY mes ORDER BY mes"""  # noqa: S608 - só placeholders "?"
        return [
            MonthTotal(month, Decimal(str(total)), bool(estimated))
            for month, total, estimated in self._db.execute(query, params)
        ]

    def coverage(self) -> Coverage:
        first, last, rows = self._db.execute("SELECT MIN(dia), MAX(dia), COUNT(*) FROM custos").fetchone()
        return Coverage(first, last, rows)
