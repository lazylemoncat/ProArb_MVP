from __future__ import annotations

from typing import Optional
from .worker import TelegramWorker
from .config import TelegramSettings

_worker: Optional[TelegramWorker] = None


def get_worker(settings: Optional[TelegramSettings] = None) -> TelegramWorker:
    global _worker
    if _worker is None:
        _worker = TelegramWorker(settings=settings)
        _worker.start()
    return _worker
