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

    # Kritik mesaj tipleri — kaybolması sistemi riske sokar, asla düşürülmez
    CRITICAL_MESSAGE_TYPES: frozenset = frozenset({
        'kill_switch_activated',
        'resume_trading',
        'position_closed',
        'flash_crash',
        'emergency_stop',
        'risk_rejected',
    })

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
        # Normal mesajlar — doluysa en eski düşer (OOM koruması)
        self._inbox: asyncio.Queue = asyncio.Queue(maxsize=1000)
        # Kritik mesajlar — doluysa üretici bekler, mesaj düşmez
        self._critical_inbox: asyncio.Queue = asyncio.Queue(maxsize=100)
        # Mesaj geldiğinde tetiklenir — start() loop'u interval beklemeden uyanır
        self._wakeup: asyncio.Event = asyncio.Event()
        # target_name → (normal_queue, critical_queue, target_wakeup_event)
        self._outbox: dict[str, tuple[asyncio.Queue, asyncio.Queue, asyncio.Event]] = {}

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
            'inbox_size': self._inbox.qsize(),
            'critical_inbox_size': self._critical_inbox.qsize(),
        }

    def connect(self, target_name: str, target: 'BaseAgent'):
        """Başka bir ajana bağlan — normal/kritik kuyruk + wakeup event'i kaydet"""
        self._outbox[target_name] = (
            target._inbox,
            target._critical_inbox,
            target._wakeup,
        )

    async def send(self, target: str, message: dict):
        """Başka bir ajana mesaj gönder. type CRITICAL_MESSAGE_TYPES'ta ise kritik kuyruğa.
        Gönderim sonrası hedef ajanın wakeup'ını set ederek event-driven tetikler."""
        if target not in self._outbox:
            return
        normal_q, critical_q, wakeup = self._outbox[target]
        msg_type = message.get('type', '')
        msg = {
            'from': self.name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            **message,
        }
        if msg_type in self.CRITICAL_MESSAGE_TYPES:
            # Kritik → asla düşürme. Doluysa üretici await'te bekler.
            if critical_q.full():
                self.logger.error(
                    f"KRITIK KUYRUK DOLU | {target}.{msg_type} — üretici bloke"
                )
            await critical_q.put(msg)
        else:
            # Normal → doluysa en eskisini at
            if normal_q.full():
                try:
                    normal_q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await normal_q.put(msg)
        # Alıcı ajanı hemen uyandır (interval beklemeden run_cycle)
        wakeup.set()

    async def receive(self, timeout: float = 0.1) -> dict | None:
        """Inbox'tan mesaj al — kritik önce"""
        try:
            return self._critical_inbox.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            return await asyncio.wait_for(self._inbox.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def receive_all(self) -> list[dict]:
        """Inbox'taki tüm mesajları al — kritik mesajlar listenin başında"""
        messages = []
        while not self._critical_inbox.empty():
            try:
                messages.append(self._critical_inbox.get_nowait())
            except asyncio.QueueEmpty:
                break
        while not self._inbox.empty():
            try:
                messages.append(self._inbox.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages

    async def start(self):
        """Ajanı başlat. Event-driven: mesaj gelirse interval beklemeden uyanır."""
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

            # Event-driven bekleme: yeni mesaj gelirse erken uyan.
            # Boş kuyruklarda event'i sıfırla; dolu kuyruk varsa interval
            # beklemeden bir sonraki cycle'a geç.
            if self._inbox.empty() and self._critical_inbox.empty():
                self._wakeup.clear()
                if self._inbox.empty() and self._critical_inbox.empty():
                    try:
                        await asyncio.wait_for(self._wakeup.wait(), timeout=self.interval)
                    except asyncio.TimeoutError:
                        pass  # Interval doldu → periyodik iş zamanı

    async def stop(self):
        """Ajanı durdur"""
        self._running = False
        self.logger.info(f"Ajan durduruldu: {self.name}")

    @abstractmethod
    async def run_cycle(self):
        """Ana çalışma döngüsü - her ajan kendi implementasyonunu yapar"""
        pass
