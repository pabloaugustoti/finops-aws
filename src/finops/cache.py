"""Cache em disco das respostas da AWS.

Por que existe: cada requisição à API do Cost Explorer custa US$ 0,01.
Um dashboard que consulta a API a cada atualização gera custo à toa.

Regra de validade:
- respostas com valores *estimados* (período ainda aberto) expiram após o TTL;
- respostas *definitivas* (período fechado) são guardadas para sempre.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class JsonCache:
    def __init__(
        self,
        directory: Path,
        ttl: timedelta = timedelta(hours=6),
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.directory = Path(directory)
        self.ttl = ttl
        self._now = now

    @staticmethod
    def make_key(operation: str, params: dict[str, Any]) -> str:
        payload = json.dumps({"operation": operation, "params": params}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Any | None:
        try:
            entry = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if not entry.get("permanent"):
            saved_at = datetime.fromisoformat(entry["saved_at"])
            if self._now() - saved_at > self.ttl:
                return None
        return entry["response"]

    def set(self, key: str, response: Any, *, permanent: bool) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = {"saved_at": self._now().isoformat(), "permanent": permanent, "response": response}
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, default=str), encoding="utf-8")
        tmp.replace(path)

    def clear(self) -> int:
        if not self.directory.exists():
            return 0
        removed = 0
        for path in self.directory.glob("*.json"):
            path.unlink()
            removed += 1
        return removed
