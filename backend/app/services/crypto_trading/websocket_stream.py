"""
Binance WebSocket Stream - Gerçek zamanlı fiyat akışı
REST API polling yerine WebSocket ile milisaniye düzeyinde güncelleme.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import websockets

from .config import CryptoTradingConfig
from .price_service import PriceData

logger = logging.getLogger('crypto_trading.websocket')


class BinanceWebSocket:
    """
    Binance WebSocket stream manager.
    Birden fazla coin'i tek bağlantıda dinler.
    Testnet ve Mainnet otomatik URL seçimi.
    """

    MAINNET_URL = 'wss://stream.binance.com:9443/ws'
    MAINNET_COMBINED = 'wss://stream.binance.com:9443/stream?streams='
    TESTNET_URL = 'wss://testnet.binance.vision/ws'
    TESTNET_COMBINED = 'wss://testnet.binance.vision/stream?streams='

    def __init__(self):
        use_testnet = CryptoTradingConfig.BINANCE_TESTNET
        self.BASE_URL = self.TESTNET_URL if use_testnet else self.MAINNET_URL
        self.COMBINED_URL = self.TESTNET_COMBINED if use_testnet else self.MAINNET_COMBINED
        self._running = False
        self._ws = None
        self._prices: dict[str, PriceData] = {}
        self._callbacks: list = []
        self._subscribed_symbols: set[str] = set()
        self._reconnect_delay = 1
        # Stale veri tespiti için — son mesaj zamanı
        self._last_message_at: datetime | None = None

    def is_stale(self, max_age_seconds: float = 30.0) -> bool:
        """Son mesajdan `max_age_seconds` geçti mi? True → WS bağlantısı/stream dondu demek."""
        if self._last_message_at is None:
            return True  # Hiç mesaj gelmedi
        age = (datetime.now(timezone.utc) - self._last_message_at).total_seconds()
        return age > max_age_seconds

    @property
    def last_message_age_seconds(self) -> float:
        if self._last_message_at is None:
            return float('inf')
        return (datetime.now(timezone.utc) - self._last_message_at).total_seconds()

    @property
    def prices(self) -> dict[str, PriceData]:
        return self._prices.copy()

    def on_price_update(self, callback):
        """Fiyat güncellemesi callback'i kaydet"""
        self._callbacks.append(callback)

    async def start(self, symbols: list[str] = None):
        """WebSocket stream'i başlat"""
        if symbols is None:
            symbols = [
                'btc', 'eth', 'sol', 'xrp', 'bnb', 'ada', 'doge',
                'avax', 'dot', 'link', 'matic', 'uni', 'ltc', 'near',
                'sui', 'inj', 'fet', 'ton', 'trx', 'fil',
            ]

        self._subscribed_symbols = set(s.lower() for s in symbols)
        self._running = True

        while self._running:
            try:
                await self._connect_and_listen(symbols)
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"WebSocket bağlantı hatası: {e}, {self._reconnect_delay}s sonra tekrar deneniyor")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    async def _connect_and_listen(self, symbols: list[str]):
        """WebSocket'e bağlan ve dinle"""
        streams = [f"{s.lower()}usdt@miniTicker" for s in symbols]
        use_testnet = self.BASE_URL == self.TESTNET_URL

        if use_testnet:
            # Testnet combined stream desteklemiyor, tek bağlantı + SUBSCRIBE kullan
            url = self.BASE_URL
        else:
            url = self.COMBINED_URL + '/'.join(streams)

        logger.info(f"WebSocket bağlanıyor: {len(symbols)} sembol (testnet={use_testnet})")

        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            self._ws = ws
            self._reconnect_delay = 1
            logger.info("WebSocket bağlandı!")

            if use_testnet:
                # Testnet: SUBSCRIBE mesajı ile abone ol
                subscribe_msg = {
                    "method": "SUBSCRIBE",
                    "params": streams,
                    "id": 1,
                }
                await ws.send(json.dumps(subscribe_msg))
                logger.info(f"WebSocket SUBSCRIBE gönderildi: {len(streams)} stream")

            async for message in ws:
                if not self._running:
                    break

                try:
                    data = json.loads(message)
                    # Combined stream: data is nested under 'data' key
                    # Single stream / SUBSCRIBE: data is directly the event
                    stream_data = data.get('data', data)
                    if stream_data.get('e'):
                        await self._process_ticker(stream_data)
                except json.JSONDecodeError as e:
                    logger.debug(f"WS: bozuk JSON frame atlandı ({e})")
                except Exception as e:
                    logger.warning(f"WS mesaj işleme hatası: {e}")

    async def _process_ticker(self, data: dict):
        """Mini ticker verisini işle"""
        event_type = data.get('e', '')
        if event_type != '24hrMiniTicker':
            return

        symbol = data.get('s', '')  # BTCUSDT
        if not symbol.endswith('USDT'):
            return

        coin = symbol.replace('USDT', '')
        current_price = float(data.get('c', 0))  # Close price
        open_price = float(data.get('o', 0))  # Open price (24h)
        high = float(data.get('h', 0))
        low = float(data.get('l', 0))
        volume = float(data.get('v', 0))  # Base asset volume

        # 24h değişim
        change_24h = 0
        if open_price > 0:
            change_24h = ((current_price - open_price) / open_price) * 100

        # 1h değişim tahmini (önceki fiyattan)
        change_1h = 0
        prev = self._prices.get(coin)
        if prev and prev.price > 0:
            change_1h = ((current_price - prev.price) / prev.price) * 100

        price_data = PriceData(
            symbol=coin,
            price=current_price,
            change_1h=round(change_1h, 4),
            change_24h=round(change_24h, 4),
            volume_24h=volume,
            high_24h=high,
            low_24h=low,
            market_cap=0,
            updated_at=datetime.now(timezone.utc),
        )

        self._prices[coin] = price_data
        self._last_message_at = datetime.now(timezone.utc)

        # Callback'leri çağır
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(coin, price_data)
                else:
                    callback(coin, price_data)
            except Exception as e:
                logger.error(f"WS callback hatası ({coin}): {e}")

    async def stop(self):
        """WebSocket'i kapat"""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("WebSocket kapatıldı")

    async def subscribe(self, symbols: list[str]):
        """Yeni sembollere abone ol"""
        if not self._ws:
            return

        new_symbols = [s.lower() for s in symbols if s.lower() not in self._subscribed_symbols]
        if not new_symbols:
            return

        params = [f"{s}usdt@miniTicker" for s in new_symbols]
        msg = {
            "method": "SUBSCRIBE",
            "params": params,
            "id": 1,
        }

        try:
            await self._ws.send(json.dumps(msg))
            self._subscribed_symbols.update(new_symbols)
            logger.info(f"Yeni abonelik: {new_symbols}")
        except Exception as e:
            logger.error(f"Abonelik hatası: {e}")
