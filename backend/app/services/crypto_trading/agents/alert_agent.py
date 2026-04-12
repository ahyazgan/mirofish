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
            # === YENİ AJAN OLAYLARI ===
            elif event_type == 'news_impact_classified':
                self.logger.info(
                    f"HABER ETKI | {msg.get('coin', '?')} "
                    f"seviye={msg.get('impact_level', 'N/A')} "
                    f"beklenen=%{msg.get('expected_move', 0)}"
                )
            elif event_type == 'news_verified':
                self.logger.info(
                    f"HABER DOGRULAMA | {msg.get('coin', '?')} "
                    f"skor={msg.get('verification_score', 0)} "
                    f"durum={msg.get('status', 'N/A')}"
                )
            elif event_type == 'news_rejected':
                self.logger.warning(
                    f"HABER RED | {msg.get('coin', '?')} "
                    f"skor={msg.get('verification_score', 0)} "
                    f"sebep={msg.get('reason', '')}"
                )
            elif event_type == 'flash_crash_detected':
                self.logger.warning(
                    f"FLASH CRASH | {msg.get('coin', '?')} "
                    f"dusus=%{msg.get('drop_pct', 0):.1f} "
                    f"seviye={msg.get('severity', 'N/A')}"
                )
            elif event_type == 'onchain_update':
                self.logger.info(
                    f"ONCHAIN | {msg.get('count', 0)} sinyal"
                )
            elif event_type == 'event_calendar_alert':
                self.logger.info(
                    f"TAKVIM | {msg.get('event_name', '?')} "
                    f"kalan={msg.get('hours_until', 0):.0f}h "
                    f"etki={msg.get('impact', 'N/A')}"
                )
            elif event_type == 'regulation_update':
                self.logger.info(
                    f"REGULASYON | {msg.get('count', 0)} haber "
                    f"etki={msg.get('impact', 'N/A')}"
                )
            elif event_type == 'listing_detected':
                self.logger.info(
                    f"LISTELEME | {msg.get('coin', '?')} "
                    f"tip={msg.get('listing_type', 'N/A')} "
                    f"borsa={msg.get('exchange', 'N/A')}"
                )
            elif event_type == 'kill_switch_activated':
                self.logger.warning(
                    f"KILL SWITCH | AKTIF! "
                    f"sebep={msg.get('reason', '?')} "
                    f"seviye={msg.get('severity', 'N/A')}"
                )
            elif event_type == 'kill_switch_deactivated':
                self.logger.info(
                    f"KILL SWITCH | Deaktif - {msg.get('message', '')}"
                )
            elif event_type == 'api_health_critical':
                self.logger.warning(
                    f"API SAGLIK | {msg.get('endpoint', '?')} "
                    f"hatalar={msg.get('failures', 0)} "
                    f"hata={msg.get('error', '')[:80]}"
                )
            elif event_type in ('balance_critical', 'balance_warning'):
                self.logger.warning(
                    f"BAKIYE | beklenen=${msg.get('expected', 0)} "
                    f"gercek=${msg.get('actual', 0)} "
                    f"fark=%{msg.get('diff_pct', 0)}"
                )
            elif event_type in ('drawdown_critical', 'drawdown_warning'):
                self.logger.warning(
                    f"DRAWDOWN | seviye={msg.get('level', '?')} "
                    f"drawdown=%{msg.get('drawdown_pct', 0)}"
                )
            elif event_type == 'losing_streak':
                self.logger.warning(
                    f"KAYIP SERISI | {msg.get('streak', 0)} ust uste zarar"
                )
            elif event_type == 'slippage_warning':
                self.logger.info(
                    f"SLIPPAGE | {msg.get('coin', '?')} "
                    f"tahmini=%{msg.get('estimated_pct', 0)}"
                )
            elif event_type == 'funding_cost_warning':
                self.logger.info(
                    f"FONLAMA MALIYET | gunluk=${msg.get('daily_cost', 0)} "
                    f"(%{msg.get('cost_pct', 0)})"
                )
            elif event_type == 'partial_close':
                self.logger.info(
                    f"KISMI KAPATMA | {msg.get('coin', '?')} "
                    f"seviye={msg.get('tp_level', '?')} "
                    f"miktar=%{msg.get('close_pct', 0)}"
                )
            elif event_type == 'daily_report':
                report = msg.get('report', {})
                self.logger.info(
                    f"GUNLUK RAPOR | {report.get('date', '?')} "
                    f"PnL=${report.get('daily_pnl', 0)} "
                    f"WinRate=%{report.get('win_rate', 0)}"
                )

            # Önemli olayları Telegram'a forward et
            important_types = {
                'signal_generated', 'trade_executed', 'position_closing',
                'risk_locked', 'whale_alert', 'portfolio_report', 'risk_reject',
                'kill_switch_activated', 'flash_crash_detected',
                'drawdown_critical', 'balance_critical', 'daily_report',
                'api_health_critical', 'listing_detected',
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
