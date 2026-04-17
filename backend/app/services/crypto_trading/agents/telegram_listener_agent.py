"""
Telegram Listener Agent - Breaking news push listener (MTProto)
Tree of Alpha, Whale Alert, BWE News, Binance Announcements gibi kanallardan
real-time push mesajlarını dinler ve News Dedup'a besler.

Polling değil, push: bir mesaj atıldığı anda tetiklenir (gecikmesiz).
telethon kütüphanesi ile kullanıcı hesabı üzerinden MTProto bağlantısı kurar.

Gerekli ENV:
- TELEGRAM_API_ID        (my.telegram.org'dan alınır)
- TELEGRAM_API_HASH
- TELEGRAM_SESSION_NAME  (varsayılan: mirofish_session)
- TELEGRAM_CHANNELS      (virgülle ayrılmış kullanıcı adları,
                          varsayılan: tree_of_alpha,WhaleAlertFeed,BWEnews,binance_announcements)
"""

import asyncio
import os
from datetime import datetime, timezone

from .base_agent import BaseAgent
from ..news_fetcher import NewsItem, _detect_coins, _generate_id, _load_binance_symbols


class TelegramListenerAgent(BaseAgent):
    """
    Görev: MTProto üzerinden kripto haber kanallarını push modda dinle
    Çıktı: Yeni mesaj → NewsItem → News Dedup'a
    """

    DEFAULT_CHANNELS = [
        'tree_of_alpha',
        'WhaleAlertFeed',
        'BWEnews',
        'binance_announcements',
    ]

    def __init__(self, interval: float = 30.0):
        super().__init__('Telegram Dinleyici', interval=interval)
        self._client = None
        self._enabled = False
        self._listener_task: asyncio.Task | None = None
        self._msg_count = 0
        self._pending_items: list[NewsItem] = []

        self._api_id = os.environ.get('TELEGRAM_API_ID', '')
        self._api_hash = os.environ.get('TELEGRAM_API_HASH', '')
        self._session_name = os.environ.get('TELEGRAM_SESSION_NAME', 'mirofish_session')
        channels_env = os.environ.get('TELEGRAM_CHANNELS', '')
        self._channels = [c.strip() for c in channels_env.split(',') if c.strip()] or self.DEFAULT_CHANNELS

    async def start(self):
        """MTProto client'ı başlat ve arkaplanda dinlemeye al"""
        if not self._api_id or not self._api_hash:
            self.logger.warning(
                "TELEGRAM_API_ID / TELEGRAM_API_HASH eksik — Telegram Dinleyici pasif mod"
            )
            self._enabled = False
            await super().start()
            return

        try:
            from telethon import TelegramClient, events
        except ImportError:
            self.logger.warning("telethon kurulu değil — `pip install telethon` gerekli")
            self._enabled = False
            await super().start()
            return

        try:
            await _load_binance_symbols()

            self._client = TelegramClient(self._session_name, int(self._api_id), self._api_hash)
            await self._client.connect()

            if not await self._client.is_user_authorized():
                self.logger.warning(
                    "Telegram oturumu yok — `mirofish_session` authorize edilmeli. Pasif mod."
                )
                await self._client.disconnect()
                self._client = None
                self._enabled = False
                await super().start()
                return

            @self._client.on(events.NewMessage(chats=self._channels))
            async def _on_new_message(event):
                try:
                    await self._handle_message(event)
                except Exception as e:
                    self.logger.error(f"Mesaj işleme hatası: {e}")

            self._enabled = True
            self.logger.info(
                f"Telegram Dinleyici aktif: {len(self._channels)} kanal "
                f"({', '.join(self._channels)})"
            )

            self._listener_task = asyncio.create_task(self._run_forever())
        except Exception as e:
            self.logger.error(f"Telegram bağlantı hatası: {e}")
            self._enabled = False

        await super().start()

    async def _run_forever(self):
        """Client disconnect olana kadar mesajları dinle"""
        try:
            await self._client.run_until_disconnected()
        except Exception as e:
            self.logger.error(f"Telegram listener crash: {e}")

    async def _handle_message(self, event):
        """Kanaldan gelen mesajı NewsItem'a çevir"""
        msg = event.message
        text = (msg.message or '').strip()
        if not text:
            return

        chat = await event.get_chat()
        channel_name = getattr(chat, 'username', None) or getattr(chat, 'title', 'telegram')

        title_line = text.split('\n', 1)[0][:300]
        coins = _detect_coins(text)

        text_lower = text.lower()
        if any(w in text_lower for w in ('listing', 'launch', 'airdrop', 'partnership')):
            hint = 'positive'
        elif any(w in text_lower for w in ('delist', 'hack', 'exploit', 'ban', 'lawsuit')):
            hint = 'negative'
        else:
            hint = None

        importance = 'high' if coins else 'medium'
        pub_dt = msg.date.astimezone(timezone.utc) if msg.date else datetime.now(timezone.utc)

        item = NewsItem(
            id=_generate_id(f'tg_{channel_name}', f"{msg.id}:{title_line}"),
            title=f"[TG/{channel_name}] {title_line}",
            body=text[:500],
            source=f'Telegram/{channel_name}',
            url=f"https://t.me/{channel_name}/{msg.id}" if isinstance(channel_name, str) else '',
            published_at=pub_dt,
            coins=coins,
            sentiment_hint=hint,
            importance=importance,
        )

        self._pending_items.append(item)
        self._msg_count += 1
        self.logger.info(f"TG push: [{channel_name}] coins={coins} | {title_line[:80]}")

    async def run_cycle(self):
        """Biriken mesajları News Dedup'a gönder"""
        if not self._pending_items:
            return

        batch = self._pending_items
        self._pending_items = []

        await self.send('news_dedup', {
            'type': 'new_news',
            'news': [n.to_dict() for n in batch],
            'news_objects': batch,
        })
        await self.send('alert', {
            'type': 'news_found',
            'count': len(batch),
            'coins': list({c for n in batch for c in n.coins}),
            'source': 'telegram_push',
        })
        self.logger.info(f"TG → News Dedup: {len(batch)} mesaj iletildi")

    async def stop(self):
        """Client'ı kapat"""
        if self._listener_task:
            self._listener_task.cancel()
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                self.logger.debug(f"Telegram disconnect hatası (önemsiz): {e}")
        await super().stop()

    @property
    def listener_stats(self) -> dict:
        return {
            'enabled': self._enabled,
            'channels': self._channels,
            'messages_received': self._msg_count,
            'pending': len(self._pending_items),
        }
