"""
Telegram Notification Agent - Telegram üzerinden bildirim
Önemli olayları Telegram'a gönderir.
"""

import httpx

from .base_agent import BaseAgent
from ..config import CryptoTradingConfig


class TelegramAgent(BaseAgent):
    """
    Görev: Önemli trading olaylarını Telegram'a gönder
    Girdi: Alert Agent'tan önemli olaylar
    Çıktı: Telegram mesajları

    Kurulum:
    1. @BotFather'dan bot oluştur → token al
    2. Bot'a mesaj gönder, chat_id al
    3. .env'ye TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID ekle
    """

    TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'

    def __init__(self, interval: float = 5.0):
        super().__init__('Telegram Bildirici', interval=interval)
        self._token = getattr(CryptoTradingConfig, 'TELEGRAM_BOT_TOKEN', '')
        self._chat_id = getattr(CryptoTradingConfig, 'TELEGRAM_CHAT_ID', '')
        self._enabled = bool(self._token and self._chat_id)
        self._message_queue: list[str] = []
        self._sent_count = 0

        if not self._enabled:
            self.logger.info("Telegram devre dışı (TELEGRAM_BOT_TOKEN/CHAT_ID eksik)")

    @property
    def telegram_stats(self) -> dict:
        return {
            'enabled': self._enabled,
            'sent_count': self._sent_count,
            'pending': len(self._message_queue),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            event_type = msg.get('type', '')

            # Sadece önemli olayları gönder
            if event_type == 'signal_generated':
                strength = msg.get('strength', '')
                if strength in ('STRONG', 'MODERATE'):
                    text = (
                        f"📊 *SİNYAL*\n"
                        f"Coin: `{msg.get('coin')}`\n"
                        f"Yön: *{msg.get('action')}*\n"
                        f"Güç: {strength}\n"
                        f"Skor: {msg.get('score')}\n"
                        f"Fiyat: ${msg.get('entry_price')}\n"
                        f"Kaynaklar: {msg.get('sources', 'N/A')}"
                    )
                    self._message_queue.append(text)

            elif event_type == 'trade_executed':
                text = (
                    f"💰 *TRADE*\n"
                    f"Coin: `{msg.get('coin')}`\n"
                    f"Yön: {msg.get('side')}\n"
                    f"Miktar: {msg.get('quantity')}\n"
                    f"Fiyat: ${msg.get('price')}\n"
                    f"Durum: {msg.get('status')}"
                )
                self._message_queue.append(text)

            elif event_type == 'position_closing':
                pnl = msg.get('pnl', 0)
                emoji = "🟢" if pnl > 0 else "🔴"
                text = (
                    f"{emoji} *POZİSYON KAPANDI*\n"
                    f"Coin: `{msg.get('coin')}`\n"
                    f"PnL: {pnl}%\n"
                    f"Sebep: {msg.get('reason')}"
                )
                self._message_queue.append(text)

            elif event_type == 'risk_locked':
                text = (
                    f"🚨 *RİSK KİLİDİ AKTİF*\n"
                    f"Günlük kayıp: ${msg.get('daily_loss')}\n"
                    f"Limit: ${msg.get('limit')}\n"
                    f"Yeni pozisyon açılmayacak!"
                )
                self._message_queue.append(text)

            elif event_type == 'whale_alert':
                events = msg.get('events', [])
                for event in events[:2]:  # Max 2 whale alert
                    if event.get('value_usd', 0) > 500_000:
                        text = (
                            f"🐋 *BALİNA*\n"
                            f"Coin: `{event.get('coin')}`\n"
                            f"Yön: {event.get('direction')}\n"
                            f"Değer: ${event.get('value_usd'):,.0f}"
                        )
                        self._message_queue.append(text)

            elif event_type == 'portfolio_report':
                text = (
                    f"📈 *PORTFÖY RAPORU*\n"
                    f"Toplam trade: {msg.get('total_trades')}\n"
                    f"Toplam PnL: ${msg.get('total_pnl')}\n"
                    f"Win Rate: %{msg.get('win_rate')}"
                )
                self._message_queue.append(text)

        # Kuyruktaki mesajları gönder
        if self._message_queue:
            await self._send_messages()

    async def _send_messages(self):
        """Kuyruktaki mesajları Telegram'a gönder"""
        if not self._enabled:
            # Demo modda sadece logla
            for text in self._message_queue:
                clean = text.replace('*', '').replace('`', '')
                self.logger.info(f"[TELEGRAM-DEMO] {clean[:100]}")
            self._sent_count += len(self._message_queue)
            self._message_queue.clear()
            return

        url = self.TELEGRAM_API.format(token=self._token)

        # Mesajları birleştir (rate limit için)
        while self._message_queue:
            text = self._message_queue.pop(0)
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json={
                        'chat_id': self._chat_id,
                        'text': text,
                        'parse_mode': 'Markdown',
                        'disable_web_page_preview': True,
                    })
                    if resp.status_code == 200:
                        self._sent_count += 1
                    elif resp.status_code == 429:
                        # Rate limited
                        self._message_queue.insert(0, text)
                        self.logger.warning("Telegram rate limit, sonraki döngüde deneyecek")
                        break
            except Exception as e:
                self.logger.error(f"Telegram gönderim hatası: {e}")
