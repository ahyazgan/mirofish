"""
Telegram Notification Agent - Telegram üzerinden bildirim ve komut dinleme
Önemli olayları Telegram'a gönderir, komutları dinler.
"""

import httpx

from .base_agent import BaseAgent
from ..config import CryptoTradingConfig


class TelegramAgent(BaseAgent):
    """
    Görev: Önemli trading olaylarını Telegram'a gönder + komut dinle
    Girdi: Alert Agent'tan önemli olaylar
    Çıktı: Telegram mesajları + komut aksiyonları → Kill Switch, Executor

    Komutlar:
    /durum    → Portföy durumunu gönder
    /killswitch → Kill Switch aktifle
    /duraklat → Trading duraklatma
    /devam    → Trading devam ettir
    """

    TELEGRAM_API = 'https://api.telegram.org/bot{token}'

    # Desteklenen komutlar
    COMMANDS = {
        '/durum', '/killswitch', '/duraklat', '/devam', '/help',
    }

    def __init__(self, interval: float = 5.0):
        super().__init__('Telegram Bildirici', interval=interval)
        self._token = getattr(CryptoTradingConfig, 'TELEGRAM_BOT_TOKEN', '')
        self._chat_id = getattr(CryptoTradingConfig, 'TELEGRAM_CHAT_ID', '')
        self._enabled = bool(self._token and self._chat_id)
        self._message_queue: list[str] = []
        self._sent_count = 0
        self._last_update_id = 0

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
                for event in events[:2]:
                    if event.get('value_usd', 0) > 500_000:
                        text = (
                            f"🐋 *BALİNA*\n"
                            f"Coin: `{event.get('coin')}`\n"
                            f"Yön: {event.get('direction')}\n"
                            f"Değer: ${event.get('value_usd'):,.0f}"
                        )
                        self._message_queue.append(text)

            elif event_type == 'portfolio_report':
                text = msg.get('report_text', '')
                if not text:
                    text = (
                        f"📈 *PORTFÖY RAPORU*\n"
                        f"Toplam trade: {msg.get('total_trades')}\n"
                        f"Toplam PnL: ${msg.get('total_pnl')}\n"
                        f"Win Rate: %{msg.get('win_rate')}"
                    )
                self._message_queue.append(text)

            elif event_type == 'kill_switch_activated':
                text = (
                    f"🛑 *KILL SWITCH AKTİF!*\n"
                    f"Sebep: {msg.get('reason')}\n"
                    f"Seviye: {msg.get('severity')}\n"
                    f"Tüm pozisyonlar kapatılıyor!"
                )
                self._message_queue.append(text)

            elif event_type == 'flash_crash_detected':
                text = (
                    f"⚡ *FLASH CRASH!*\n"
                    f"Coin: `{msg.get('coin')}`\n"
                    f"Düşüş: %{msg.get('drop_pct', 0):.1f}\n"
                    f"Seviye: {msg.get('severity')}"
                )
                self._message_queue.append(text)

            elif event_type == 'drawdown_critical':
                text = (
                    f"📉 *DRAWDOWN KRİTİK!*\n"
                    f"Seviye: {msg.get('level')}\n"
                    f"Drawdown: %{msg.get('drawdown_pct', 0)}"
                )
                self._message_queue.append(text)

        # Komutları dinle
        await self._check_commands()

        # Kuyruktaki mesajları gönder
        if self._message_queue:
            await self._send_messages()

    async def _check_commands(self):
        """Telegram'dan gelen komutları dinle"""
        if not self._enabled:
            return

        try:
            url = f"{self.TELEGRAM_API.format(token=self._token)}/getUpdates"
            params = {
                'offset': self._last_update_id + 1,
                'timeout': 1,
                'allowed_updates': '["message"]',
            }
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    return

                data = resp.json()
                if not data.get('ok'):
                    return

                for update in data.get('result', []):
                    update_id = update.get('update_id', 0)
                    if update_id > self._last_update_id:
                        self._last_update_id = update_id

                    message = update.get('message', {})
                    text = message.get('text', '').strip().lower()
                    chat_id = str(message.get('chat', {}).get('id', ''))

                    # Sadece yetkili chat'ten gelen komutları kabul et
                    if chat_id != self._chat_id:
                        continue

                    await self._handle_command(text)

        except Exception as e:
            self.logger.debug(f"Telegram komut dinleme hatası: {e}")

    async def _handle_command(self, command: str):
        """Tek bir komutu i��le"""
        if command == '/killswitch':
            self.logger.warning("TELEGRAM KOMUT | /killswitch → Kill Switch tetikleniyor")
            await self.send('kill_switch', {
                'type': 'manual_kill',
                'user': 'telegram',
            })
            self._message_queue.append("🛑 Kill Switch tetiklendi!")

        elif command == '/duraklat':
            self.logger.info("TELEGRAM KOMUT | /duraklat → Trading duraklat��lıyor")
            await self.send('executor', {
                'type': 'pause_trading',
                'reason': 'Telegram komutu: /duraklat',
                'duration_minutes': 30,
            })
            self._message_queue.append("⏸️ Trading 30dk duraklatıldı")

        elif command == '/devam':
            self.logger.info("TELEGRAM KOMUT | /devam → Trading devam ettiriliyor")
            await self.send('executor', {
                'type': 'resume_trading',
                'reason': 'Telegram komutu: /devam',
            })
            await self.send('kill_switch', {
                'type': 'manual_restart',
            })
            self._message_queue.append("▶️ Trading devam ediyor")

        elif command == '/durum':
            self.logger.info("TELEGRAM KOMUT | /durum → Durum raporu istendi")
            # Durum bilgisi alert agent üzerinden gelecek, basit onay gönder
            self._message_queue.append("📊 Durum raporu hazırlanıyor...")

        elif command == '/help':
            text = (
                "🤖 *MiroFish Komutlar*\n\n"
                "/durum - Portföy durumu\n"
                "/killswitch - Acil durdurma\n"
                "/duraklat - 30dk duraklatma\n"
                "/devam - Devam ettir\n"
                "/help - Bu yardım mesajı"
            )
            self._message_queue.append(text)

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

        url = f"{self.TELEGRAM_API.format(token=self._token)}/sendMessage"

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
                        self._message_queue.insert(0, text)
                        self.logger.warning("Telegram rate limit, sonraki döngüde deneyecek")
                        break
            except Exception as e:
                self.logger.error(f"Telegram gönderim hatası: {e}")
