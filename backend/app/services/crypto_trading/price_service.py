"""
Kripto Fiyat Servisi
Binance ve CoinGecko'dan gerçek zamanlı fiyat verisi çeker.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import CryptoTradingConfig

logger = logging.getLogger('crypto_trading.price')


@dataclass
class PriceData:
    """Coin fiyat verisi"""
    symbol: str
    price: float
    change_1h: float       # % değişim (1 saat)
    change_24h: float      # % değişim (24 saat)
    volume_24h: float      # 24 saat işlem hacmi (USD)
    high_24h: float
    low_24h: float
    market_cap: float
    updated_at: datetime

    def to_dict(self):
        return {
            'symbol': self.symbol,
            'price': self.price,
            'change_1h': self.change_1h,
            'change_24h': self.change_24h,
            'volume_24h': self.volume_24h,
            'high_24h': self.high_24h,
            'low_24h': self.low_24h,
            'market_cap': self.market_cap,
            'updated_at': self.updated_at.isoformat(),
        }


# CoinGecko coin ID mapping
COINGECKO_IDS = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'BNB': 'binancecoin',
    'SOL': 'solana',
    'XRP': 'ripple',
    'ADA': 'cardano',
    'DOGE': 'dogecoin',
    'AVAX': 'avalanche-2',
    'DOT': 'polkadot',
    'MATIC': 'matic-network',
}


class PriceService:
    """Kripto fiyat verisi servisi"""

    BINANCE_TICKER_URL = 'https://api.binance.com/api/v3/ticker/24hr'
    BINANCE_PRICE_URL = 'https://api.binance.com/api/v3/ticker/price'
    COINGECKO_URL = 'https://api.coingecko.com/api/v3/coins/markets'

    def __init__(self):
        self._price_cache: dict[str, PriceData] = {}
        self._last_update: float = 0

    async def get_prices(self, symbols: Optional[list[str]] = None, force: bool = False) -> dict[str, PriceData]:
        """Tüm takip edilen coinlerin fiyatlarını getir"""
        now = time.time()
        if not force and (now - self._last_update) < CryptoTradingConfig.PRICE_UPDATE_INTERVAL:
            if symbols:
                return {s: self._price_cache[s] for s in symbols if s in self._price_cache}
            return self._price_cache

        target_symbols = symbols or CryptoTradingConfig.TRACKED_COINS

        # Önce Binance'den dene, başarısız olursa CoinGecko
        try:
            prices = await self._fetch_binance(target_symbols)
            if prices:
                self._price_cache.update(prices)
                self._last_update = now
                return prices
        except Exception as e:
            logger.warning(f"Binance fiyat hatası, CoinGecko'ya geçiliyor: {e}")

        try:
            prices = await self._fetch_coingecko(target_symbols)
            if prices:
                self._price_cache.update(prices)
                self._last_update = now
                return prices
        except Exception as e:
            logger.error(f"CoinGecko fiyat hatası: {e}")

        return self._price_cache

    async def get_price(self, symbol: str) -> Optional[PriceData]:
        """Tek bir coin'in fiyatını getir"""
        prices = await self.get_prices([symbol])
        return prices.get(symbol.upper())

    async def _fetch_binance(self, symbols: list[str]) -> dict[str, PriceData]:
        """Binance API'den fiyat verisi çek"""
        prices = {}
        async with httpx.AsyncClient() as client:
            # 24hr ticker ile hem fiyat hem değişim alabiliyoruz
            pairs = [f"{s.upper()}USDT" for s in symbols]

            for pair in pairs:
                try:
                    resp = await client.get(
                        self.BINANCE_TICKER_URL,
                        params={'symbol': pair},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    symbol = pair.replace('USDT', '')
                    price = float(data['lastPrice'])
                    open_price = float(data['openPrice'])

                    # 1h change hesapla (Binance 24hr veriyor, yaklaşık hesap)
                    change_24h = float(data['priceChangePercent'])

                    prices[symbol] = PriceData(
                        symbol=symbol,
                        price=price,
                        change_1h=0,  # Binance ticker'da 1h yok, klines'dan alınabilir
                        change_24h=change_24h,
                        volume_24h=float(data['quoteVolume']),
                        high_24h=float(data['highPrice']),
                        low_24h=float(data['lowPrice']),
                        market_cap=0,  # Binance market cap vermiyor
                        updated_at=datetime.now(timezone.utc),
                    )
                except Exception as e:
                    logger.warning(f"Binance {pair} hatası: {e}")

            # 1h klines ile 1 saatlik değişimi hesapla
            for symbol in prices:
                try:
                    resp = await client.get(
                        'https://api.binance.com/api/v3/klines',
                        params={'symbol': f'{symbol}USDT', 'interval': '1h', 'limit': 2},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    klines = resp.json()
                    if len(klines) >= 2:
                        prev_close = float(klines[0][4])
                        curr_price = prices[symbol].price
                        if prev_close > 0:
                            prices[symbol].change_1h = round(((curr_price - prev_close) / prev_close) * 100, 2)
                except Exception:
                    pass

        logger.info(f"Binance: {len(prices)} coin fiyatı alındı")
        return prices

    async def _fetch_coingecko(self, symbols: list[str]) -> dict[str, PriceData]:
        """CoinGecko API'den fiyat verisi çek"""
        prices = {}

        # Symbol -> CoinGecko ID mapping
        ids = [COINGECKO_IDS.get(s.upper(), s.lower()) for s in symbols]
        ids_str = ','.join(ids)

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    self.COINGECKO_URL,
                    params={
                        'vs_currency': 'usd',
                        'ids': ids_str,
                        'order': 'market_cap_desc',
                        'sparkline': 'false',
                        'price_change_percentage': '1h,24h',
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                # Reverse mapping: coingecko id -> symbol
                id_to_symbol = {v: k for k, v in COINGECKO_IDS.items()}

                for coin in data:
                    symbol = id_to_symbol.get(coin['id'], coin['symbol'].upper())
                    prices[symbol] = PriceData(
                        symbol=symbol,
                        price=float(coin.get('current_price', 0)),
                        change_1h=float(coin.get('price_change_percentage_1h_in_currency', 0) or 0),
                        change_24h=float(coin.get('price_change_percentage_24h', 0) or 0),
                        volume_24h=float(coin.get('total_volume', 0) or 0),
                        high_24h=float(coin.get('high_24h', 0) or 0),
                        low_24h=float(coin.get('low_24h', 0) or 0),
                        market_cap=float(coin.get('market_cap', 0) or 0),
                        updated_at=datetime.now(timezone.utc),
                    )

                logger.info(f"CoinGecko: {len(prices)} coin fiyatı alındı")
            except Exception as e:
                logger.error(f"CoinGecko API hatası: {e}")

        return prices

    async def get_price_summary(self) -> list[dict]:
        """Tüm takip edilen coinlerin özet fiyat bilgisi"""
        prices = await self.get_prices()
        return [p.to_dict() for p in prices.values()]
