"""
Liquidation Tracker Agent - Likidasyon izleme
Binance Futures'dan büyük likidasyon olaylarını tespit eder.
Binance public API - ücretsiz, auth gerekmez.
"""

import httpx
from datetime import datetime, timezone

from .base_agent import BaseAgent


class LiquidationAgent(BaseAgent):
    """
    Görev: Büyük likidasyon dalgalarını tespit et
    Girdi: Binance Futures API (force orders)
    Çıktı: Likidasyon sinyalleri → Strategist, Alert

    Mantık:
    - Büyük long likidasyonlar → Daha fazla düşüş beklenir (cascade)
    - Büyük short likidasyonlar → Daha fazla yükseliş beklenir (short squeeze)
    - Likidasyon sonrası toparlanma → Dip fırsatı
    """

    # Binance Futures forceOrders endpoint (public)
    BINANCE_LIQUIDATION_URL = 'https://fapi.binance.com/fapi/v1/allForceOrders'
    # Alternatif: Open Interest
    BINANCE_OI_URL = 'https://fapi.binance.com/fapi/v1/openInterest'

    def __init__(self, interval: float = 60.0):
        super().__init__('Likidasyon Izleyici', interval=interval)
        self._recent_liquidations: list[dict] = []
        self._seen_orders: set[str] = set()
        self._open_interest_history: dict[str, list[dict]] = {}

    @property
    def liquidation_stats(self) -> dict:
        recent = self._recent_liquidations[-50:]
        long_liqs = [l for l in recent if l['side'] == 'SELL']  # Long pozisyon likide → SELL
        short_liqs = [l for l in recent if l['side'] == 'BUY']  # Short pozisyon likide → BUY
        return {
            'total_liquidations': len(recent),
            'long_liquidations': len(long_liqs),
            'short_liquidations': len(short_liqs),
            'total_long_value': sum(l['value_usdt'] for l in long_liqs),
            'total_short_value': sum(l['value_usdt'] for l in short_liqs),
        }

    async def run_cycle(self):
        await self.receive_all()

        signals = []

        # 1. Force orders (likidasyonlar)
        liquidations = await self._fetch_liquidations()
        if liquidations:
            liq_signals = self._analyze_liquidations(liquidations)
            signals.extend(liq_signals)

        # 2. Open Interest değişimleri (top 10 coin)
        oi_signals = await self._check_open_interest()
        signals.extend(oi_signals)

        if signals:
            await self.send('strategist', {
                'type': 'liquidation_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'liquidation_alert',
                'count': len(signals),
                'stats': self.liquidation_stats,
            })

            for s in signals[:3]:
                self.logger.info(
                    f"LIKIDASYON | {s['coin']} {s.get('liq_type', 'OI')} "
                    f"${s.get('value_usdt', 0):,.0f} score={s['signal_score']}"
                )

    async def _fetch_liquidations(self) -> list[dict]:
        """Binance'den son likidasyonları çek"""
        all_liqs = []
        top_coins = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB', 'DOGE', 'ADA', 'AVAX']

        for coin in top_coins:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        self.BINANCE_LIQUIDATION_URL,
                        params={
                            'symbol': f'{coin}USDT',
                            'limit': 20,
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for order in data:
                            order_id = f"{order.get('symbol', '')}_{order.get('time', '')}"
                            if order_id not in self._seen_orders:
                                self._seen_orders.add(order_id)
                                price = float(order.get('price', 0))
                                qty = float(order.get('origQty', 0))
                                value = price * qty
                                liq = {
                                    'coin': coin,
                                    'side': order.get('side', ''),
                                    'price': price,
                                    'quantity': qty,
                                    'value_usdt': round(value, 2),
                                    'time': order.get('time', 0),
                                }
                                all_liqs.append(liq)
                                self._recent_liquidations.append(liq)
            except Exception as e:
                self.logger.debug(f"Liquidation fetch hatası ({coin}): {e}")

        # Cleanup
        if len(self._seen_orders) > 10000:
            self._seen_orders = set(list(self._seen_orders)[-5000:])
        if len(self._recent_liquidations) > 500:
            self._recent_liquidations = self._recent_liquidations[-500:]

        return all_liqs

    def _analyze_liquidations(self, liquidations: list[dict]) -> list[dict]:
        """Likidasyon verilerini analiz et"""
        signals = []

        # Coin bazlı grupla
        coin_liqs: dict[str, dict] = {}
        for liq in liquidations:
            coin = liq['coin']
            if coin not in coin_liqs:
                coin_liqs[coin] = {'long_value': 0, 'short_value': 0, 'count': 0}
            coin_liqs[coin]['count'] += 1
            if liq['side'] == 'SELL':  # Long likidasyonu
                coin_liqs[coin]['long_value'] += liq['value_usdt']
            else:  # Short likidasyonu
                coin_liqs[coin]['short_value'] += liq['value_usdt']

        for coin, data in coin_liqs.items():
            total = data['long_value'] + data['short_value']
            if total < 50_000:  # $50K altı önemsiz
                continue

            # Ağırlıklı long likidasyon → bearish cascade riski
            if data['long_value'] > data['short_value'] * 2:
                signal_score = -0.2
                liq_type = 'long_cascade'
                reason = f"Ağır long likidasyon: ${data['long_value']:,.0f} (cascade riski)"
            # Ağırlıklı short likidasyon → short squeeze
            elif data['short_value'] > data['long_value'] * 2:
                signal_score = 0.2
                liq_type = 'short_squeeze'
                reason = f"Short squeeze: ${data['short_value']:,.0f}"
            else:
                continue

            signals.append({
                'coin': coin,
                'liq_type': liq_type,
                'long_value': round(data['long_value'], 2),
                'short_value': round(data['short_value'], 2),
                'value_usdt': round(total, 2),
                'count': data['count'],
                'signal_score': signal_score,
                'reason': reason,
                'source': 'liquidation',
            })

        return signals

    async def _check_open_interest(self) -> list[dict]:
        """Open Interest değişimlerini kontrol et"""
        signals = []
        top_coins = ['BTC', 'ETH', 'SOL', 'XRP', 'BNB']

        for coin in top_coins:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        self.BINANCE_OI_URL,
                        params={'symbol': f'{coin}USDT'}
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    oi = float(data.get('openInterest', 0))

                    if coin not in self._open_interest_history:
                        self._open_interest_history[coin] = []
                    self._open_interest_history[coin].append({
                        'oi': oi,
                        'time': datetime.now(timezone.utc).isoformat(),
                    })
                    if len(self._open_interest_history[coin]) > 50:
                        self._open_interest_history[coin] = self._open_interest_history[coin][-50:]

                    # OI değişimini kontrol et
                    history = self._open_interest_history[coin]
                    if len(history) >= 2:
                        prev_oi = history[-2]['oi']
                        if prev_oi > 0:
                            oi_change = ((oi - prev_oi) / prev_oi) * 100
                            # %5+ artış → aşırı kaldıraç
                            if oi_change > 5:
                                signals.append({
                                    'coin': coin,
                                    'oi_change': round(oi_change, 2),
                                    'open_interest': oi,
                                    'signal_score': -0.1,  # Aşırı kaldıraç → riskli
                                    'reason': f'OI {oi_change:+.1f}% artış (aşırı kaldıraç riski)',
                                    'source': 'liquidation',
                                })
                            elif oi_change < -5:
                                signals.append({
                                    'coin': coin,
                                    'oi_change': round(oi_change, 2),
                                    'open_interest': oi,
                                    'signal_score': 0.1,  # Kaldıraç azalıyor → sağlıklı
                                    'reason': f'OI {oi_change:+.1f}% düşüş (kaldıraç temizleniyor)',
                                    'source': 'liquidation',
                                })
            except Exception as e:
                self.logger.debug(f"Open interest fetch hatası ({coin}): {e}")

        return signals
