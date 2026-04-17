"""
DeFi Monitor Agent - DeFi protokol ve on-chain izleme
DefiLlama API ile TVL, DEX hacmi ve protokol değişimlerini takip eder.
Ücretsiz API - ek maliyet yok.
"""

import httpx
from datetime import datetime, timezone

from .base_agent import BaseAgent


class DefiMonitorAgent(BaseAgent):
    """
    Görev: DeFi ekosistemini izle, TVL ve DEX hacim değişimlerini tespit et
    Girdi: DefiLlama API (ücretsiz, auth gerekmez)
    Çıktı: DeFi sinyalleri → Strategist, Alert

    Mantık:
    - TVL artışı → Protokol token'ına güven artıyor, bullish
    - TVL düşüşü → Protokol token'ından çıkış, bearish
    - DEX hacim patlaması → Volatilite artacak
    - Stablecoin dominans artışı → Risk-off, bearish
    """

    DEFILLAMA_TVL_URL = 'https://api.llama.fi/protocols'
    DEFILLAMA_CHAINS_URL = 'https://api.llama.fi/v2/chains'
    DEFILLAMA_VOLUMES_URL = 'https://api.llama.fi/overview/dexs'
    DEFILLAMA_STABLES_URL = 'https://stablecoins.llama.fi/stablecoins?includePrices=true'

    # Protokol → Token mapping
    PROTOCOL_TOKEN_MAP = {
        'lido': 'LDO', 'aave': 'AAVE', 'makerdao': 'MKR',
        'uniswap': 'UNI', 'curve-dex': 'CRV', 'compound': 'COMP',
        'pancakeswap': 'CAKE', 'sushiswap': 'SUSHI', 'balancer': 'BAL',
        'synthetix': 'SNX', 'yearn-finance': 'YFI', '1inch-network': '1INCH',
        'gmx': 'GMX', 'dydx': 'DYDX', 'convex-finance': 'CVX',
        'frax': 'FXS', 'rocket-pool': 'RPL', 'pendle': 'PENDLE',
        'radiant': 'RDNT', 'jupiter': 'JUP', 'raydium': 'RAY',
        'orca': 'ORCA', 'marinade-finance': 'MNDE',
        'injective': 'INJ', 'sui': 'SUI', 'aptos': 'APT',
    }

    def __init__(self, interval: float = 600.0):  # 10 dakikada bir
        super().__init__('DeFi Izleyici', interval=interval)
        self._prev_tvl: dict[str, float] = {}
        self._prev_chain_tvl: dict[str, float] = {}
        self._stablecoin_history: list[float] = []

    async def run_cycle(self):
        await self.receive_all()

        signals = []

        # 1. Protokol TVL değişimleri
        tvl_signals = await self._check_protocol_tvl()
        signals.extend(tvl_signals)

        # 2. Chain TVL (Ethereum, Solana, vb.)
        chain_signals = await self._check_chain_tvl()
        signals.extend(chain_signals)

        # 3. Stablecoin dominans
        stable_signals = await self._check_stablecoin_dominance()
        signals.extend(stable_signals)

        if signals:
            await self.send('strategist', {
                'type': 'defi_signals',
                'signals': signals,
            })
            await self.send('alert', {
                'type': 'defi_update',
                'count': len(signals),
                'signals': [{'coin': s.get('coin', ''), 'reason': s.get('reason', '')} for s in signals[:5]],
            })
            for s in signals[:3]:
                self.logger.info(f"DEFI | {s.get('coin', 'GENEL')} score={s['signal_score']} - {s['reason']}")

    async def _check_protocol_tvl(self) -> list[dict]:
        """Protokol TVL değişimlerini kontrol et"""
        signals = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.DEFILLAMA_TVL_URL)
                if resp.status_code != 200:
                    return signals

                protocols = resp.json()

                for protocol in protocols[:100]:
                    slug = protocol.get('slug', '')
                    name = protocol.get('name', '')
                    tvl = protocol.get('tvl', 0) or 0
                    change_1d = protocol.get('change_1d', 0) or 0

                    token = self.PROTOCOL_TOKEN_MAP.get(slug)
                    if not token:
                        continue

                    # TVL kaydet
                    self._prev_tvl[slug] = tvl

                    # Önemli TVL değişimi
                    if abs(change_1d) > 5:  # %5+ günlük değişim
                        score = 0.15 if change_1d > 0 else -0.15
                        if abs(change_1d) > 15:
                            score *= 2

                        signals.append({
                            'coin': token,
                            'protocol': name,
                            'tvl': tvl,
                            'tvl_change_1d': round(change_1d, 2),
                            'signal_score': round(score, 3),
                            'reason': f'{name} TVL {change_1d:+.1f}% (${tvl/1e6:.0f}M)',
                            'source': 'defi_monitor',
                        })
        except Exception as e:
            self.logger.debug(f"DeFi fetch hatası: {e}")

        return signals[:10]

    async def _check_chain_tvl(self) -> list[dict]:
        """Zincir bazlı TVL değişimleri"""
        signals = []
        chain_token_map = {
            'Ethereum': 'ETH', 'Solana': 'SOL', 'BSC': 'BNB',
            'Avalanche': 'AVAX', 'Polygon': 'MATIC', 'Arbitrum': 'ARB',
            'Optimism': 'OP', 'Base': 'ETH', 'Sui': 'SUI',
            'Aptos': 'APT', 'Near': 'NEAR', 'Tron': 'TRX',
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.DEFILLAMA_CHAINS_URL)
                if resp.status_code != 200:
                    return signals

                chains = resp.json()
                for chain in chains:
                    name = chain.get('name', '')
                    tvl = chain.get('tvl', 0) or 0
                    token = chain_token_map.get(name)
                    if not token:
                        continue

                    prev = self._prev_chain_tvl.get(name, tvl)
                    self._prev_chain_tvl[name] = tvl

                    if prev > 0:
                        change_pct = ((tvl - prev) / prev) * 100
                        if abs(change_pct) > 3:
                            score = 0.1 if change_pct > 0 else -0.1
                            signals.append({
                                'coin': token,
                                'chain': name,
                                'tvl': tvl,
                                'tvl_change': round(change_pct, 2),
                                'signal_score': round(score, 3),
                                'reason': f'{name} chain TVL {change_pct:+.1f}%',
                                'source': 'defi_monitor',
                            })
        except Exception as e:
            self.logger.debug(f"DeFi fetch hatası: {e}")

        return signals

    async def _check_stablecoin_dominance(self) -> list[dict]:
        """Stablecoin piyasa payı - risk-off göstergesi"""
        signals = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.DEFILLAMA_STABLES_URL)
                if resp.status_code != 200:
                    return signals

                data = resp.json()
                stables = data.get('peggedAssets', [])
                total_mcap = sum(
                    s.get('circulating', {}).get('peggedUSD', 0) or 0
                    for s in stables
                )

                self._stablecoin_history.append(total_mcap)
                if len(self._stablecoin_history) > 50:
                    self._stablecoin_history = self._stablecoin_history[-50:]

                if len(self._stablecoin_history) >= 2:
                    prev = self._stablecoin_history[-2]
                    if prev > 0:
                        change = ((total_mcap - prev) / prev) * 100
                        # Stablecoin mcap hızlı artış → risk-off, paralar stabil'e gidiyor
                        if change > 1:
                            signals.append({
                                'coin': 'MARKET',
                                'stablecoin_mcap': total_mcap,
                                'change': round(change, 2),
                                'signal_score': -0.1,
                                'applies_to': 'all',
                                'reason': f'Stablecoin mcap {change:+.1f}% artış (risk-off sinyali)',
                                'source': 'defi_monitor',
                            })
        except Exception as e:
            self.logger.debug(f"DeFi fetch hatası: {e}")

        return signals
