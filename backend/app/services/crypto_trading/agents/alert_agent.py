"""
Alert/Logger Agent - Merkezi loglama ve bildirim
Tüm ajanlardan gelen olayları loglar ve raporlar.
"""

import json
import os
from datetime import datetime, timezone

from .base_agent import BaseAgent


class AlertAgent(BaseAgent):
    """
    Görev: Tüm olayları logla, önemli olayları raporla
    Girdi: Tüm ajanlardan bildirimler
    """

    def __init__(self, interval: float = 3.0, log_dir: str = None):
        super().__init__('Alarm Merkezi', interval=interval)
        self._events: list[dict] = []
        self._log_dir = log_dir or os.path.join(
            os.path.dirname(__file__), '../../../../logs/crypto_trading'
        )
        os.makedirs(self._log_dir, exist_ok=True)
        self._log_file = os.path.join(self._log_dir, 'events.jsonl')

    @property
    def events(self) -> list[dict]:
        return self._events[-100:]

    async def run_cycle(self):
        messages = await self.receive_all()
        if not messages:
            return

        for msg in messages:
            event_type = msg.get('type', 'unknown')
            timestamp = datetime.now(timezone.utc).isoformat()

            event = {
                'time': timestamp,
                'from': msg.get('from', 'unknown'),
                'type': event_type,
                **{k: v for k, v in msg.items()
                   if k not in ('from', 'timestamp', 'type', 'news_objects',
                                'result_objects', 'price_objects', 'signal_object')},
            }
            self._events.append(event)

            # Konsola önemli olayları yazdır
            if event_type == 'signal_generated':
                self.logger.info(
                    f"SINYAL | {msg.get('coin')} {msg.get('action')} "
                    f"({msg.get('strength')}) score={msg.get('score')} "
                    f"entry=${msg.get('entry_price')}"
                )
            elif event_type == 'trade_executed':
                self.logger.info(
                    f"TRADE | {msg.get('coin')} {msg.get('side')} "
                    f"qty={msg.get('quantity')} price=${msg.get('price')} "
                    f"status={msg.get('status')}"
                )
            elif event_type == 'position_closing':
                self.logger.warning(
                    f"KAPAT | {msg.get('coin')} PnL={msg.get('pnl')}% "
                    f"sebep={msg.get('reason')}"
                )
            elif event_type == 'price_alert':
                for a in msg.get('alerts', []):
                    self.logger.warning(
                        f"FIYAT | {a['coin']} %{a['change_pct']} "
                        f"(${a.get('prev_price',0):.2f} → ${a['price']:.2f})"
                    )
            elif event_type == 'portfolio_report':
                self.logger.info(
                    f"PORTFOY | Trades={msg.get('total_trades')} "
                    f"PnL=${msg.get('total_pnl')} "
                    f"WinRate={msg.get('win_rate')}%"
                )
            elif event_type == 'news_found':
                coins = msg.get('coins', [])
                self.logger.info(
                    f"HABER | {msg.get('count')} yeni haber "
                    f"coins={','.join(coins[:10])}"
                )
            elif event_type == 'whale_alert':
                self.logger.info(
                    f"BALINA | {msg.get('count')} balina hareketi tespit edildi"
                )
            elif event_type == 'funding_rate_alert':
                self.logger.info(
                    f"FUNDING | {msg.get('count')} aşırı fonlama oranı"
                )
            elif event_type == 'technical_analysis':
                self.logger.info(
                    f"TEKNİK | {msg.get('count')} teknik sinyal "
                    f"coins={','.join(msg.get('coins', [])[:5])}"
                )
            elif event_type == 'orderbook_analysis':
                self.logger.info(
                    f"ORDERBOOK | {msg.get('count')} emir defteri sinyali"
                )
            elif event_type == 'social_media_update':
                self.logger.info(
                    f"REDDIT | {msg.get('count')} sosyal sinyal "
                    f"({msg.get('total_posts', 0)} post)"
                )
            elif event_type == 'liquidation_alert':
                stats = msg.get('stats', {})
                self.logger.info(
                    f"LIKIDASYON | {stats.get('total_liquidations', 0)} likidasyon "
                    f"(L=${stats.get('total_long_value', 0):,.0f} / S=${stats.get('total_short_value', 0):,.0f})"
                )
            elif event_type == 'correlation_update':
                self.logger.info(
                    f"KORELASYON | BTC dom={msg.get('btc_dominance', 'N/A')}% "
                    f"F&G={msg.get('fear_greed', 'N/A')}"
                )
            elif event_type == 'backtest_report':
                self.logger.info(
                    f"BACKTEST | Doğruluk: %{msg.get('accuracy', 0)} "
                    f"({msg.get('correct', 0)}/{msg.get('total_verified', 0)})"
                )
            elif event_type == 'defi_update':
                sigs = msg.get('signals', [])
                summary = '; '.join(s.get('reason', '') for s in sigs[:2])
                self.logger.info(
                    f"DEFI | {msg.get('count', 0)} sinyal - {summary}"
                )
            elif event_type == 'volatility_update':
                coins = msg.get('coins', [])
                self.logger.info(
                    f"VOLATILITE | {msg.get('count', 0)} sinyal "
                    f"coins={','.join(coins[:5])}"
                )
            elif event_type == 'regime_update':
                self.logger.info(
                    f"REJIM | Genel={msg.get('overall', 'N/A')} "
                    f"BTC={msg.get('btc_regime', 'N/A')} "
                    f"({msg.get('count', 0)} coin)"
                )
            elif event_type == 'macro_update':
                indicators = msg.get('indicators', {})
                summary = '; '.join(f"{k}: {v}" for k, v in list(indicators.items())[:3])
                self.logger.info(
                    f"MAKRO | {msg.get('count', 0)} sinyal - {summary}"
                )

            # Önemli olayları Telegram'a forward et
            important_types = {
                'signal_generated', 'trade_executed', 'position_closing',
                'risk_locked', 'whale_alert', 'portfolio_report', 'risk_reject',
            }
            if event_type in important_types:
                await self.send('telegram', msg)

            # JSONL dosyasına kaydet
            try:
                with open(self._log_file, 'a', encoding='utf-8') as f:
                    safe_event = {k: v for k, v in event.items()
                                 if not isinstance(v, (bytes, type))}
                    f.write(json.dumps(safe_event, ensure_ascii=False, default=str) + '\n')
            except Exception:
                pass
