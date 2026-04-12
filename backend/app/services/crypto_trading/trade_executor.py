"""
Binance Trade Executor
Sinyalleri gerçek (veya testnet) Binance emirlerine dönüştürür.
"""

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

        if self.use_testnet:
            logger.info("Binance TESTNET modu aktif")
        else:
            logger.warning("Binance MAINNET modu aktif - GERÇEK PARA İLE İŞLEM YAPILACAK!")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

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
        if not self.is_configured:
            logger.warning("Binance API anahtarları yapılandırılmamış - simülasyon modu")
            return self._simulate_order(signal)

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

                # Stop-loss emri gönder
                sl_order = await self._place_stop_loss(
                    symbol=symbol,
                    side='SELL' if side == 'BUY' else 'BUY',
                    quantity=quantity,
                    stop_price=signal.stop_loss,
                )
                if sl_order:
                    trade_order.stop_loss_order_id = str(sl_order.get('orderId', ''))

                # Take-profit emri gönder
                tp_order = await self._place_take_profit(
                    symbol=symbol,
                    side='SELL' if side == 'BUY' else 'BUY',
                    quantity=quantity,
                    price=signal.take_profit,
                )
                if tp_order:
                    trade_order.take_profit_order_id = str(tp_order.get('orderId', ''))

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
        """Binance'e emir gönder"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': f"{quantity:.8f}".rstrip('0').rstrip('.'),
        }

        if order_type == 'MARKET':
            params.pop('price', None)

        signed = self._sign(params)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/api/v3/order",
                params=signed,
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

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
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/api/v3/order",
                    params=signed,
                    headers=self._headers(),
                    timeout=10,
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
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/api/v3/order",
                    params=signed,
                    headers=self._headers(),
                    timeout=10,
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
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/api/v3/account",
                    params=params,
                    headers=self._headers(),
                    timeout=10,
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

    def _simulate_order(self, signal: TradingSignal) -> TradeOrder:
        """API anahtarı yokken simülasyon emri oluştur"""
        quantity = signal.position_size_usdt / signal.entry_price

        order = TradeOrder(
            order_id=f"SIM-{int(time.time())}",
            signal_id=signal.id,
            coin=signal.coin,
            side='BUY' if signal.action == SignalAction.BUY else 'SELL',
            order_type='MARKET (SIM)',
            quantity=round(quantity, 8),
            price=signal.entry_price,
            status='SIMULATED',
            filled_at=datetime.now(timezone.utc),
        )

        self._order_history.append(order)
        signal.executed = True

        logger.info(f"Simülasyon emri: {signal.coin} {order.side} qty={order.quantity} price={order.price}")
        return order

    def _round_quantity(self, quantity: float, coin: str) -> float:
        """Coin'e göre miktar yuvarla (Binance lot size kuralları)"""
        # Yaygın coin lot size'ları
        lot_sizes = {
            'BTC': 5, 'ETH': 4, 'BNB': 3, 'SOL': 2,
            'XRP': 1, 'ADA': 1, 'DOGE': 0, 'AVAX': 2,
            'DOT': 2, 'MATIC': 1,
        }
        decimals = lot_sizes.get(coin.upper(), 2)
        return round(quantity, decimals)

    def get_order_history(self, limit: int = 50) -> list[dict]:
        return [o.to_dict() for o in self._order_history[-limit:]]

    def get_active_positions(self) -> dict[str, dict]:
        return {k: v.to_dict() for k, v in self._active_positions.items()}

    async def cancel_all_orders(self, symbol: str) -> bool:
        """Bir sembol için tüm açık emirleri iptal et"""
        if not self.is_configured:
            return False

        params = self._sign({'symbol': symbol})
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"{self.base_url}/api/v3/openOrders",
                    params=params,
                    headers=self._headers(),
                    timeout=10,
                )
                resp.raise_for_status()
                logger.info(f"Tüm emirler iptal edildi: {symbol}")
                return True
        except Exception as e:
            logger.error(f"Emir iptal hatası: {e}")
            return False
