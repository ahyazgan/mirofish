"""
Binance Trade Executor
Sinyalleri gerçek (veya testnet) Binance emirlerine dönüştürür.
"""

import asyncio
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import CryptoTradingConfig
from .signal_engine import SignalAction, TradingSignal

logger = logging.getLogger('crypto_trading.executor')


class _RateLimiter:
    """Basit token-bucket rate limiter (Binance 1200 req/min limit için)."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) >= self.max_requests:
                # En eski istek penceresinden çıkana kadar bekle
                wait = self._timestamps[0] + self.window - now
                if wait > 0:
                    await asyncio.sleep(wait)
                    now = time.monotonic()
                    cutoff = now - self.window
                    self._timestamps = [t for t in self._timestamps if t > cutoff]
            self._timestamps.append(now)


@dataclass
class TradeOrder:
    """Gerçekleşen veya gönderilen emir"""
    order_id: str
    signal_id: str
    coin: str
    side: str               # 'BUY' veya 'SELL'
    order_type: str         # 'MARKET', 'LIMIT'
    quantity: float
    price: float
    status: str             # 'PENDING', 'FILLED', 'CANCELLED', 'FAILED'
    stop_loss_order_id: Optional[str] = None
    take_profit_order_id: Optional[str] = None
    pnl: float = 0.0
    created_at: datetime = None
    filled_at: Optional[datetime] = None
    error: Optional[str] = None
    raw_response: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'signal_id': self.signal_id,
            'coin': self.coin,
            'side': self.side,
            'order_type': self.order_type,
            'quantity': self.quantity,
            'price': self.price,
            'status': self.status,
            'stop_loss_order_id': self.stop_loss_order_id,
            'take_profit_order_id': self.take_profit_order_id,
            'pnl': self.pnl,
            'created_at': self.created_at.isoformat(),
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'error': self.error,
        }


class TradeExecutor:
    """
    Binance üzerinden emir yönetimi.
    Testnet ve gerçek hesap desteği.
    """

    MAINNET_URL = 'https://api.binance.com'
    TESTNET_URL = 'https://testnet.binance.vision'

    def __init__(self):
        self.api_key = CryptoTradingConfig.BINANCE_API_KEY
        self.api_secret = CryptoTradingConfig.BINANCE_API_SECRET
        self.use_testnet = CryptoTradingConfig.BINANCE_TESTNET

        self.base_url = self.TESTNET_URL if self.use_testnet else self.MAINNET_URL
        self._order_history: list[TradeOrder] = []
        self._active_positions: dict[str, TradeOrder] = {}
        self._http_client: httpx.AsyncClient | None = None
        self._lot_sizes: dict[str, int] = {}
        self._lot_sizes_loaded = False
        # Binance: 1200 ağırlıklı istek/dakika — güvenlik için 1000 ile sınırla
        self._rate_limiter = _RateLimiter(max_requests=1000, window_seconds=60.0)

        if self.use_testnet:
            logger.info("Binance TESTNET modu aktif")
        else:
            logger.warning("Binance MAINNET modu aktif - GERÇEK PARA İLE İŞLEM YAPILACAK!")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def _get_client(self) -> httpx.AsyncClient:
        """Tekil httpx client döndür (lazy init)"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10)
        return self._http_client

    async def close(self):
        """HTTP client'ı kapat"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def _sign(self, params: dict) -> dict:
        """Binance API imzalama"""
        params['timestamp'] = int(time.time() * 1000)
        query_string = '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        params['signature'] = signature
        return params

    def _headers(self) -> dict:
        return {'X-MBX-APIKEY': self.api_key}

    async def execute_signal(self, signal: TradingSignal) -> Optional[TradeOrder]:
        """Sinyali Binance emrine dönüştür ve gönder"""
        # İlk çağrıda lot size'ları yükle
        if not self._lot_sizes_loaded:
            await self._load_lot_sizes()

        if not self.is_configured or CryptoTradingConfig.SIMULATION_MODE:
            logger.info("Simülasyon modu - demo trade")
            return self._simulate_order(signal)

        # GERÇEK EMİR YOLU: aynı coin için açık pozisyon varsa yeni emir açma
        if signal.coin in self._active_positions:
            logger.info(
                f"Emir atlandı: {signal.coin} için açık pozisyon var"
            )
            return None

        symbol = f"{signal.coin}USDT"
        side = 'BUY' if signal.action == SignalAction.BUY else 'SELL'

        # Miktar hesapla (USDT -> coin miktarı)
        quantity = signal.position_size_usdt / signal.entry_price
        quantity = self._round_quantity(quantity, signal.coin)

        try:
            # Ana market emri
            order = await self._place_order(
                symbol=symbol,
                side=side,
                order_type='MARKET',
                quantity=quantity,
            )

            if not order:
                return None

            trade_order = TradeOrder(
                order_id=str(order.get('orderId', '')),
                signal_id=signal.id,
                coin=signal.coin,
                side=side,
                order_type='MARKET',
                quantity=quantity,
                price=float(order.get('fills', [{}])[0].get('price', signal.entry_price)),
                status='FILLED' if order.get('status') == 'FILLED' else 'PENDING',
                raw_response=order,
            )

            if order.get('status') == 'FILLED':
                trade_order.filled_at = datetime.now(timezone.utc)
                opposite_side = 'SELL' if side == 'BUY' else 'BUY'

                # Stop-loss emri gönder — KRİTİK
                sl_order = await self._place_stop_loss(
                    symbol=symbol,
                    side=opposite_side,
                    quantity=quantity,
                    stop_price=signal.stop_loss,
                )
                if sl_order:
                    trade_order.stop_loss_order_id = str(sl_order.get('orderId', ''))
                else:
                    # SL başarısız → pozisyon korumasız, ACİL market kapat
                    logger.error(
                        f"SL EMRİ BAŞARISIZ: {symbol} qty={quantity} — "
                        f"pozisyon korumasız! Market-close deneniyor."
                    )
                    try:
                        close_order = await self._place_order(
                            symbol=symbol,
                            side=opposite_side,
                            order_type='MARKET',
                            quantity=quantity,
                        )
                        trade_order.status = 'FAILED'
                        trade_order.error = f'SL başarısız, pozisyon market-close edildi: {close_order.get("orderId") if close_order else "?"}'
                    except Exception as close_err:
                        logger.critical(
                            f"SL BAŞARISIZ + MARKET-CLOSE DA BAŞARISIZ: {symbol} — "
                            f"MANUEL MÜDAHALE GEREKLİ! Hata: {close_err}"
                        )
                        trade_order.status = 'FAILED'
                        trade_order.error = f'SL ve market-close başarısız: {close_err}'
                    self._order_history.append(trade_order)
                    return trade_order

                # Take-profit emri gönder — SL varsa TP opsiyonel
                tp_order = await self._place_take_profit(
                    symbol=symbol,
                    side=opposite_side,
                    quantity=quantity,
                    price=signal.take_profit,
                )
                if tp_order:
                    trade_order.take_profit_order_id = str(tp_order.get('orderId', ''))
                else:
                    # TP başarısız ama SL var → loglayıp devam et
                    logger.warning(
                        f"TP emri başarısız: {symbol} — SL aktif, manuel TP takibi gerekebilir"
                    )

            self._order_history.append(trade_order)
            self._active_positions[signal.coin] = trade_order
            signal.executed = True

            logger.info(f"Emir gerçekleştirildi: {symbol} {side} qty={quantity} "
                       f"price={trade_order.price} status={trade_order.status}")

            return trade_order

        except Exception as e:
            logger.error(f"Emir hatası: {e}")
            error_order = TradeOrder(
                order_id='ERROR',
                signal_id=signal.id,
                coin=signal.coin,
                side=side,
                order_type='MARKET',
                quantity=quantity,
                price=signal.entry_price,
                status='FAILED',
                error=str(e),
            )
            self._order_history.append(error_order)
            return error_order

    async def _place_order(self, symbol: str, side: str, order_type: str, quantity: float) -> Optional[dict]:
        """Binance'e emir gönder (rate-limit + 429 backoff ile)"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': f"{quantity:.8f}".rstrip('0').rstrip('.'),
        }

        if order_type == 'MARKET':
            params.pop('price', None)

        signed = self._sign(params)

        client = await self._get_client()
        # Rate limit ve 429 backoff ile POST
        for attempt in range(3):
            await self._rate_limiter.acquire()
            resp = await client.post(
                f"{self.base_url}/api/v3/order",
                params=signed,
                headers=self._headers(),
            )
            # 429 (rate limit) / 418 (IP ban) → Retry-After'a uyarak bekle
            if resp.status_code in (429, 418):
                retry_after = float(resp.headers.get('Retry-After', 2 ** attempt))
                logger.warning(
                    f"Binance rate limit ({resp.status_code}) → {retry_after:.1f}s bekleme"
                )
                await asyncio.sleep(min(retry_after, 60))
                continue
            resp.raise_for_status()
            return resp.json()
        # 3 denemeden sonra da başarısızsa son hatayı fırlat
        resp.raise_for_status()
        return None

    async def _place_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float) -> Optional[dict]:
        """Stop-loss emri gönder"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': 'STOP_LOSS_LIMIT',
            'quantity': f"{quantity:.8f}".rstrip('0').rstrip('.'),
            'stopPrice': f"{stop_price:.8f}".rstrip('0').rstrip('.'),
            'price': f"{stop_price:.8f}".rstrip('0').rstrip('.'),
            'timeInForce': 'GTC',
        }
        signed = self._sign(params)

        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.base_url}/api/v3/order",
                params=signed,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Stop-loss emri hatası: {e}")
            return None

    async def _place_take_profit(self, symbol: str, side: str, quantity: float, price: float) -> Optional[dict]:
        """Take-profit emri gönder"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': 'TAKE_PROFIT_LIMIT',
            'quantity': f"{quantity:.8f}".rstrip('0').rstrip('.'),
            'stopPrice': f"{price:.8f}".rstrip('0').rstrip('.'),
            'price': f"{price:.8f}".rstrip('0').rstrip('.'),
            'timeInForce': 'GTC',
        }
        signed = self._sign(params)

        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self.base_url}/api/v3/order",
                params=signed,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Take-profit emri hatası: {e}")
            return None

    async def get_account_balance(self) -> dict:
        """Hesap bakiyesini getir"""
        if not self.is_configured:
            return {'error': 'API anahtarları yapılandırılmamış', 'balances': []}

        params = self._sign({})
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{self.base_url}/api/v3/account",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # Sadece bakiyesi olan varlıkları göster
            balances = [
                {
                    'asset': b['asset'],
                    'free': float(b['free']),
                    'locked': float(b['locked']),
                }
                for b in data.get('balances', [])
                if float(b['free']) > 0 or float(b['locked']) > 0
            ]
            return {'balances': balances}
        except Exception as e:
            logger.error(f"Hesap bakiyesi hatası: {e}")
            return {'error': str(e), 'balances': []}

    def _simulate_order(self, signal: TradingSignal) -> Optional[TradeOrder]:
        """API anahtarı yokken simülasyon emri oluştur.

        Aynı coin için açık pozisyon varsa yeni emir açma — sadece mevcut
        pozisyonu döndür (duplicate trade'leri engeller).
        """
        if signal.coin in self._active_positions:
            existing = self._active_positions[signal.coin]
            logger.info(
                f"Simülasyon atlandı: {signal.coin} için açık pozisyon var "
                f"(order={existing.order_id} entry={existing.price})"
            )
            return None

        quantity = signal.position_size_usdt / signal.entry_price

        # Use unique order_id so DB tracking sees each as distinct
        order_id = f"SIM-{signal.id}-{int(time.time() * 1000)}"

        order = TradeOrder(
            order_id=order_id,
            signal_id=signal.id,
            coin=signal.coin,
            side='BUY' if signal.action == SignalAction.BUY else 'SELL',
            order_type='MARKET (SIM)',
            quantity=round(quantity, 8),
            price=signal.entry_price,
            status='SIMULATED',
            filled_at=datetime.now(timezone.utc),
        )
        # SL/TP değerlerini simülasyon tarafında tutabilmek için raw_response'a yaz
        order.raw_response = {
            'stop_loss': signal.stop_loss,
            'take_profit': signal.take_profit,
            'size_usdt': signal.position_size_usdt,
        }

        self._order_history.append(order)
        self._active_positions[signal.coin] = order
        signal.executed = True

        logger.info(
            f"Simülasyon emri: {signal.coin} {order.side} qty={order.quantity} "
            f"price={order.price} SL={signal.stop_loss} TP={signal.take_profit}"
        )
        return order

    def evaluate_simulated_positions(self, current_prices: dict) -> list[dict]:
        """Simülasyon pozisyonlarını mevcut fiyatlara göre değerlendir, SL/TP'ye
        değenleri kapat ve kapatma kayıtlarını döndür.

        current_prices: dict[coin] -> PriceData veya float
        Döndürdüğü liste: {'order': TradeOrder, 'close_price': float, 'pnl': float,
                          'pnl_pct': float, 'reason': 'stop_loss'|'take_profit'}
        """
        closed = []
        for coin in list(self._active_positions.keys()):
            position = self._active_positions[coin]
            if position.status not in ('SIMULATED', 'FILLED'):
                continue

            price_data = current_prices.get(coin)
            if price_data is None:
                continue
            current_price = getattr(price_data, 'price', price_data)
            if not isinstance(current_price, (int, float)) or current_price <= 0:
                continue

            sl = position.raw_response.get('stop_loss', 0)
            tp = position.raw_response.get('take_profit', 0)
            size_usdt = position.raw_response.get('size_usdt', 0)

            close_reason = None
            if position.side == 'BUY':
                if sl and current_price <= sl:
                    close_reason = 'stop_loss'
                elif tp and current_price >= tp:
                    close_reason = 'take_profit'
            else:  # SELL
                if sl and current_price >= sl:
                    close_reason = 'stop_loss'
                elif tp and current_price <= tp:
                    close_reason = 'take_profit'

            if not close_reason:
                continue

            # PnL
            if position.side == 'BUY':
                pnl_pct = (current_price - position.price) / position.price * 100
            else:
                pnl_pct = (position.price - current_price) / position.price * 100
            pnl = size_usdt * pnl_pct / 100 if size_usdt else 0.0

            position.status = 'CLOSED'
            position.pnl = pnl
            position.filled_at = position.filled_at or datetime.now(timezone.utc)

            closed.append({
                'order': position,
                'close_price': current_price,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'reason': close_reason,
            })

            del self._active_positions[coin]
            logger.info(
                f"SIM KAPANDI | {coin} {position.side} entry={position.price} "
                f"exit={current_price} pnl={pnl:+.2f} ({pnl_pct:+.2f}%) sebep={close_reason}"
            )

        return closed

    async def _load_lot_sizes(self):
        """Binance exchangeInfo'dan lot size'ları dinamik yükle"""
        if self._lot_sizes_loaded:
            return

        # Fallback statik değerler
        self._lot_sizes = {
            'BTC': 5, 'ETH': 4, 'BNB': 3, 'SOL': 2,
            'XRP': 1, 'ADA': 1, 'DOGE': 0, 'AVAX': 2,
            'DOT': 2, 'MATIC': 1,
        }

        try:
            client = await self._get_client()
            resp = await client.get(f"{self.base_url}/api/v3/exchangeInfo")
            if resp.status_code == 200:
                data = resp.json()
                for symbol_info in data.get('symbols', []):
                    symbol = symbol_info.get('symbol', '')
                    if not symbol.endswith('USDT'):
                        continue
                    coin = symbol.replace('USDT', '')

                    for f in symbol_info.get('filters', []):
                        if f.get('filterType') == 'LOT_SIZE':
                            step_size = f.get('stepSize', '0.01')
                            # stepSize'dan decimal sayısını hesapla
                            if '.' in step_size:
                                stripped = step_size.rstrip('0').rstrip('.')
                                if '.' in stripped:
                                    decimals = len(stripped.split('.')[1])
                                else:
                                    decimals = 0
                            else:
                                decimals = 0
                            self._lot_sizes[coin] = decimals
                            break

                self._lot_sizes_loaded = True
                logger.info(f"Lot size'lar yüklendi: {len(self._lot_sizes)} sembol")
        except Exception as e:
            logger.warning(f"Lot size yükleme hatası (fallback kullanılıyor): {e}")
            self._lot_sizes_loaded = True  # Fallback ile devam et

    def _round_quantity(self, quantity: float, coin: str) -> float:
        """Coin'e göre miktar yuvarla (Binance lot size kuralları)"""
        decimals = self._lot_sizes.get(coin.upper(), 2)
        return round(quantity, decimals)

    def get_order_history(self, limit: int | None = 50) -> list[dict]:
        """Son `limit` emri dict olarak döndür. limit=None → tüm geçmiş."""
        if limit is None:
            return [o.to_dict() for o in self._order_history]
        return [o.to_dict() for o in self._order_history[-limit:]]

    def get_active_positions(self) -> dict[str, dict]:
        return {k: v.to_dict() for k, v in self._active_positions.items()}

    async def cancel_all_orders(self, symbol: str) -> bool:
        """Bir sembol için tüm açık emirleri iptal et"""
        if not self.is_configured:
            return False

        params = self._sign({'symbol': symbol})
        try:
            client = await self._get_client()
            resp = await client.delete(
                f"{self.base_url}/api/v3/openOrders",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info(f"Tüm emirler iptal edildi: {symbol}")
            return True
        except Exception as e:
            logger.error(f"Emir iptal hatası: {e}")
            return False
