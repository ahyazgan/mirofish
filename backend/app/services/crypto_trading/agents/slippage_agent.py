"""
Slippage Hesaplayıcı - Beklenen vs gerçekleşen fiyat farkını hesaplar.
Emir öncesi tahmini slippage kontrolü. Tamamen yerel - ek maliyet yok.
"""

from collections import defaultdict
from datetime import datetime, timezone

from .base_agent import BaseAgent


class SlippageAgent(BaseAgent):
    """
    Görev: Slippage'i tahmin et ve kontrol et
    Girdi: Order Book Agent'tan derinlik, Executor'dan emir sonuçları
    Çıktı: Slippage uyarıları → Executor, Alert

    Mantık:
    - Emir öncesi: Orderbook derinliğine göre tahmini slippage
    - Emir sonrası: Gerçek slippage ölçümü
    - Slippage >%0.5 → Uyar, limit emre çevir önerisi
    - Slippage >%1.0 → Emir engelle
    """

    WARN_SLIPPAGE_PCT = 0.5    # %0.5 üstü uyarı
    BLOCK_SLIPPAGE_PCT = 1.0   # %1.0 üstü engelle
    MAX_SPREAD_PCT = 0.3       # %0.3 üstü spread → dikkat

    def __init__(self, interval: float = 5.0):
        super().__init__('Slippage Hesaplayici', interval=interval)
        self._orderbook_data: dict[str, dict] = {}  # coin → bid/ask data
        self._slippage_history: list[dict] = []
        self._slip_stats = {'estimated': 0, 'warned': 0, 'blocked': 0}

    @property
    def slippage_stats(self) -> dict:
        avg_slippage = 0.0
        if self._slippage_history:
            avg_slippage = sum(s['slippage_pct'] for s in self._slippage_history[-50:]) / min(len(self._slippage_history), 50)
        return {
            **self._slip_stats,
            'avg_slippage_pct': round(avg_slippage, 4),
            'history_count': len(self._slippage_history),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            msg_type = msg.get('type', '')

            if msg_type == 'orderbook_snapshot':
                coin = msg.get('coin', '')
                self._orderbook_data[coin] = {
                    'best_bid': msg.get('best_bid', 0),
                    'best_ask': msg.get('best_ask', 0),
                    'bid_depth': msg.get('total_bid_usdt', 0),
                    'ask_depth': msg.get('total_ask_usdt', 0),
                    'spread_pct': msg.get('spread_pct', 0),
                }

            elif msg_type == 'estimate_slippage':
                # Emir öncesi slippage tahmini isteği
                coin = msg.get('coin', '')
                order_size_usdt = msg.get('size_usdt', 0)
                side = msg.get('side', 'BUY')

                estimate = self._estimate_slippage(coin, order_size_usdt, side)
                self._slip_stats['estimated'] += 1

                # Sonucu gönder
                await self.send('executor', {
                    'type': 'slippage_estimate',
                    'coin': coin,
                    'estimated_slippage_pct': estimate['slippage_pct'],
                    'spread_pct': estimate['spread_pct'],
                    'recommendation': estimate['recommendation'],
                    'should_proceed': estimate['should_proceed'],
                })

                if not estimate['should_proceed']:
                    self._slip_stats['blocked'] += 1
                    self.logger.warning(
                        f"SLIPPAGE ENGEL | {coin} tahmini={estimate['slippage_pct']:.2f}% "
                        f"eşik={self.BLOCK_SLIPPAGE_PCT}%"
                    )
                elif estimate['slippage_pct'] > self.WARN_SLIPPAGE_PCT:
                    self._slip_stats['warned'] += 1
                    self.logger.info(
                        f"SLIPPAGE UYARI | {coin} tahmini={estimate['slippage_pct']:.2f}% "
                        f"→ {estimate['recommendation']}"
                    )

            elif msg_type == 'order_filled':
                # Emir sonrası gerçek slippage ölçümü
                coin = msg.get('coin', '')
                expected_price = msg.get('expected_price', 0)
                fill_price = msg.get('fill_price', 0)

                if expected_price > 0 and fill_price > 0:
                    actual_slippage = abs(fill_price - expected_price) / expected_price * 100

                    self._slippage_history.append({
                        'coin': coin,
                        'expected': expected_price,
                        'filled': fill_price,
                        'slippage_pct': round(actual_slippage, 4),
                        'time': datetime.now(timezone.utc).isoformat(),
                    })

                    if len(self._slippage_history) > 500:
                        self._slippage_history = self._slippage_history[-500:]

                    if actual_slippage > self.WARN_SLIPPAGE_PCT:
                        self.logger.warning(
                            f"GERCEK SLIPPAGE | {coin} {actual_slippage:.3f}% "
                            f"(${expected_price:.4f} → ${fill_price:.4f})"
                        )

    def _estimate_slippage(self, coin: str, size_usdt: float, side: str) -> dict:
        """Tahmini slippage hesapla"""
        ob = self._orderbook_data.get(coin, {})

        best_bid = ob.get('best_bid', 0)
        best_ask = ob.get('best_ask', 0)
        bid_depth = ob.get('bid_depth', 0)
        ask_depth = ob.get('ask_depth', 0)

        # Spread hesapla
        spread_pct = 0.0
        if best_bid > 0 and best_ask > 0:
            spread_pct = ((best_ask - best_bid) / best_bid) * 100

        # Slippage tahmini: emir büyüklüğü / mevcut derinlik
        if side == 'BUY':
            depth = ask_depth
        else:
            depth = bid_depth

        if depth > 0:
            # Basit model: emir büyüklüğünün derinliğe oranı
            depth_ratio = size_usdt / depth
            estimated_slippage = spread_pct + (depth_ratio * 100 * 0.5)
        else:
            estimated_slippage = spread_pct + 0.5  # Veri yoksa %0.5 varsay

        estimated_slippage = round(estimated_slippage, 4)

        # Karar
        should_proceed = estimated_slippage < self.BLOCK_SLIPPAGE_PCT

        if estimated_slippage > self.BLOCK_SLIPPAGE_PCT:
            recommendation = 'BLOCK - çok yüksek slippage, emir iptal'
        elif estimated_slippage > self.WARN_SLIPPAGE_PCT:
            recommendation = 'LIMIT - market yerine limit emir kullan'
        else:
            recommendation = 'OK - market emir güvenli'

        return {
            'slippage_pct': estimated_slippage,
            'spread_pct': round(spread_pct, 4),
            'depth_usdt': depth,
            'recommendation': recommendation,
            'should_proceed': should_proceed,
        }
