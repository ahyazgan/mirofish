"""
Base Agent - Tüm ajanların temel sınıfı
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


class BaseAgent(ABC):
    """Tüm trading ajanlarının base class'ı"""

    def __init__(self, name: str, interval: float = 10.0):
        self.name = name
        self.interval = interval
        self.logger = logging.getLogger(f'crypto_trading.agent.{name}')
        self._running = False
        self._stats = {
            'cycles': 0,
            'errors': 0,
            'last_run': None,
            'started_at': None,
        }
        # Ajanlar arası iletişim kuyruğu
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._outbox: dict[str, asyncio.Queue] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            'name': self.name,
            'running': self._running,
            'interval': self.interval,
            'cycles': self._stats['cycles'],
            'errors': self._stats['errors'],
            'last_run': self._stats['last_run'].isoformat() if self._stats['last_run'] else None,
            'started_at': self._stats['started_at'].isoformat() if self._stats['started_at'] else None,
        }

    def connect(self, target_name: str, queue: asyncio.Queue):
        """Başka bir ajana mesaj kuyruğu bağla"""
        self._outbox[target_name] = queue

    async def send(self, target: str, message: dict):
        """Başka bir ajana mesaj gönder"""
        if target in self._outbox:
            await self._outbox[target].put({
                'from': self.name,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                **message,
            })

    async def receive(self, timeout: float = 0.1) -> dict | None:
        """Inbox'tan mesaj al"""
        try:
            return await asyncio.wait_for(self._inbox.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def receive_all(self) -> list[dict]:
        """Inbox'taki tüm mesajları al"""
        messages = []
        while not self._inbox.empty():
            try:
                messages.append(self._inbox.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages

    async def start(self):
        """Ajanı başlat"""
        if self._running:
            return
        self._running = True
        self._stats['started_at'] = datetime.now(timezone.utc)
        self.logger.info(f"Ajan başlatıldı: {self.name} (interval={self.interval}s)")

        while self._running:
            try:
                self._stats['last_run'] = datetime.now(timezone.utc)
                await self.run_cycle()
                self._stats['cycles'] += 1
            except Exception as e:
                self.logger.error(f"Döngü hatası: {e}")
                self._stats['errors'] += 1
            await asyncio.sleep(self.interval)

    async def stop(self):
        """Ajanı durdur"""
        self._running = False
        self.logger.info(f"Ajan durduruldu: {self.name}")

    @abstractmethod
    async def run_cycle(self):
        """Ana çalışma döngüsü - her ajan kendi implementasyonunu yapar"""
        pass
