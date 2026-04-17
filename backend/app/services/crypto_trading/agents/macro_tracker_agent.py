"""
Macro Tracker Agent - Makroekonomik gösterge takibi
DXY (Dolar Endeksi), Altın, S&P500 ve kripto korelasyonu.
Ücretsiz API'ler - ek maliyet yok.
"""

import httpx
from datetime import datetime, timezone

from .base_agent import BaseAgent


class MacroTrackerAgent(BaseAgent):
    """
    Görev: Makroekonomik göstergeleri izle, kripto etkisini değerlendir
    Girdi: Ücretsiz finans API'leri
    Çıktı: Makro sinyaller → Strategist, Alert

    Mantık:
    - DXY yükseliyor → USD güçleniyor → Kripto düşer (ters korelasyon)
    - DXY düşüyor → USD zayıflıyor → Kripto yükselir
    - Altın yükseliyor → Risk-off → Kripto da yükselir (son yıllarda)
    - S&P500 düşüyor → Risk-off → Kripto düşer
    - Tahvil faizi yükseliyor → Riskli varlıklardan çıkış → Kripto düşer
    """

    # Yahoo Finance ücretsiz endpoint (chartları çekebiliriz)
    # Alternatif: Binance'deki USDT perpetual index'ler
    BINANCE_MACRO_SYMBOLS = {
        'DXY': None,  # DXY Binance'de yok, alternatif kullanacağız
        'GOLD': 'PAXGUSDT',   # PAX Gold ≈ altın fiyatı
        'SP500': 'SPYUSDT',   # SPY token (Binance futures)
    }

    def __init__(self, interval: float = 300.0):  # 5 dakikada bir
        super().__init__('Makro Izleyici', interval=interval)
        self._macro_history: dict[str, list[dict]] = {}
        self._btc_correlation: dict[str, float] = {}

    @property
    def macro_stats(self) -> dict:
        return {
            'indicators': {k: v[-1] if v else {} for k, v in self._macro_history.items()},
            'btc_correlation': self._btc_correlation,
        }

    async def run_cycle(self):
        await self.receive_all()

        signals = []

        # 1. Altın fiyatı (PAXG = tokenized gold)
        gold_signal = await self._check_gold()
        if gold_signal:
            signals.append(gold_signal)

        # 2. DXY proxy - EURUSDT ters çevirme ile tahmin
        dxy_signal = await self._check_dxy_proxy()
        if dxy_signal:
            signals.append(dxy_signal)

        # 3. Geleneksel piyasa (Binance'deki stock tokenları)
        stock_signals = await self._check_stock_market()
        signals.extend(stock_signals)

        # 4. US Treasury proxy - stablecoin yield karşılaştırma
        # (DeFi yield vs Treasury yield → sermaye akışı yönü)

        if signals:
            await self.send('strategist', {
                'type': 'macro_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'macro_update',
                'count': len(signals),
                'indicators': {s.get('indicator', ''): s.get('reason', '') for s in signals},
            })

            for s in signals[:3]:
                self.logger.info(f"MAKRO | {s.get('indicator', '')} score={s['signal_score']} - {s['reason']}")

    async def _check_gold(self) -> dict | None:
        """Altın fiyatını PAXG ile takip et"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    'https://api.binance.com/api/v3/klines',
                    params={'symbol': 'PAXGUSDT', 'interval': '1h', 'limit': 24}
                )
                if resp.status_code != 200:
                    return None

                klines = resp.json()
                if len(klines) < 2:
                    return None

                current = float(klines[-1][4])  # Close
                open_24h = float(klines[0][1])   # Open 24h ago

                if open_24h <= 0:
                    return None

                change_24h = ((current - open_24h) / open_24h) * 100

                self._save_history('GOLD', current, change_24h)

                if abs(change_24h) > 1:
                    # Altın ve kripto genelde aynı yönde (risk-on/risk-off)
                    score = 0.1 if change_24h > 0 else -0.1
                    return {
                        'indicator': 'GOLD',
                        'value': current,
                        'change_24h': round(change_24h, 2),
                        'signal_score': score,
                        'applies_to': 'all',
                        'reason': f'Altın {change_24h:+.1f}% (${current:.0f})',
                        'source': 'macro',
                    }
        except Exception as e:
            self.logger.debug(f"Macro fetch hatası: {e}")
        return None

    async def _check_dxy_proxy(self) -> dict | None:
        """DXY proxy: EUR/USDT üzerinden dolar gücü tahmini"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # EUR/USDT Binance'de var mı kontrol et, yoksa alternatif
                resp = await client.get(
                    'https://api.binance.com/api/v3/klines',
                    params={'symbol': 'EURUSDT', 'interval': '1h', 'limit': 24}
                )
                if resp.status_code != 200:
                    return None

                klines = resp.json()
                if len(klines) < 2:
                    return None

                current = float(klines[-1][4])
                open_24h = float(klines[0][1])

                if open_24h <= 0:
                    return None

                eur_change = ((current - open_24h) / open_24h) * 100
                # EUR düşüyor = USD güçleniyor = DXY yükseliyor
                dxy_proxy_change = -eur_change

                self._save_history('DXY', dxy_proxy_change, dxy_proxy_change)

                if abs(dxy_proxy_change) > 0.3:
                    # DXY yükselişi kripto için bearish
                    score = -0.15 if dxy_proxy_change > 0 else 0.15
                    direction = "güçleniyor" if dxy_proxy_change > 0 else "zayıflıyor"
                    return {
                        'indicator': 'DXY',
                        'value': dxy_proxy_change,
                        'change_24h': round(dxy_proxy_change, 2),
                        'signal_score': score,
                        'applies_to': 'all',
                        'reason': f'USD {direction} (DXY proxy {dxy_proxy_change:+.1f}%)',
                        'source': 'macro',
                    }
        except Exception as e:
            self.logger.debug(f"Macro fetch hatası: {e}")
        return None

    async def _check_stock_market(self) -> list[dict]:
        """Hisse senedi piyasası (Binance stock tokens)"""
        signals = []
        stock_symbols = {
            'AAPL': 'AAPLUSDT',
            'TSLA': 'TSLAUSDT',
            'NVDA': 'NVDAUSDT',
        }

        for name, symbol in stock_symbols.items():
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        'https://fapi.binance.com/fapi/v1/premiumIndex',
                        params={'symbol': symbol}
                    )
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    price = float(data.get('markPrice', 0))

                    if price <= 0:
                        continue

                    self._save_history(name, price, 0)

                    history = self._macro_history.get(name, [])
                    if len(history) >= 2:
                        prev = history[-2].get('value', price)
                        if prev > 0:
                            change = ((price - prev) / prev) * 100
                            if abs(change) > 1:
                                score = 0.05 if change > 0 else -0.05
                                signals.append({
                                    'indicator': name,
                                    'value': price,
                                    'change': round(change, 2),
                                    'signal_score': score,
                                    'applies_to': 'all',
                                    'reason': f'{name} {change:+.1f}% (${price:.2f})',
                                    'source': 'macro',
                                })
            except Exception as e:
                self.logger.debug(f"Stock fetch hatası ({name}): {e}")

        return signals

    def _save_history(self, indicator: str, value: float, change: float):
        """Gösterge geçmişi kaydet"""
        if indicator not in self._macro_history:
            self._macro_history[indicator] = []
        self._macro_history[indicator].append({
            'value': value,
            'change': change,
            'time': datetime.now(timezone.utc).isoformat(),
        })
        if len(self._macro_history[indicator]) > 100:
            self._macro_history[indicator] = self._macro_history[indicator][-100:]
