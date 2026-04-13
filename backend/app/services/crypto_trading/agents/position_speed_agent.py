"""
Pozisyon Hız Yöneticisi - Pozisyona girme/çıkma stratejisini belirler.
Haberin önemine göre anında mı yoksa kademeli mi gireceğini kontrol eder.
Tamamen yerel hesaplama - ek maliyet yok.
"""

from .base_agent import BaseAgent


class PositionSpeedAgent(BaseAgent):
    """
    Görev: Sinyal türüne ve haber önemine göre giriş stratejisi belirle
    Girdi: Strategist'ten sinyaller, Impact Classifier'dan haber etki sınıfı
    Çıktı: Giriş stratejisi → Executor

    Stratejiler:
    - INSTANT: Market emir, anında giriş (CRITICAL haber)
    - FAST: Limit emir, 30sn timeout (HIGH haber)
    - GRADUAL: 3 parçada kademeli giriş (MEDIUM haber)
    - CAREFUL: 5 parçada kademeli, her parça arası kontrol (düşük güven)
    """

    def __init__(self, interval: float = 2.0):
        super().__init__('Pozisyon Hiz Yoneticisi', interval=interval)
        self._active_entries: dict[str, dict] = {}  # coin → entry plan
        self._speed_stats = {'instant': 0, 'fast': 0, 'gradual': 0, 'careful': 0}

    @property
    def speed_stats(self) -> dict:
        return {
            **self._speed_stats,
            'active_entries': len(self._active_entries),
        }

    async def run_cycle(self):
        messages = await self.receive_all()

        for msg in messages:
            if msg.get('type') == 'new_signal':
                signal = msg.get('signal', {})
                impact_class = msg.get('impact_class', 'MEDIUM')
                confidence = msg.get('confidence', 0.5)

                strategy = self._determine_strategy(signal, impact_class, confidence)

                # Executor'a strateji ile birlikte sinyal gönder
                await self.send('executor', {
                    'type': 'execute_with_strategy',
                    'signal': signal,
                    'signal_object': msg.get('signal_object'),
                    'entry_strategy': strategy,
                })

                self._speed_stats[strategy['type']] += 1

                self.logger.info(
                    f"GIRIS STRATEJISI | {signal.get('coin', '?')} "
                    f"{strategy['type'].upper()} "
                    f"parcalar={strategy['chunks']} "
                    f"emir_tipi={strategy['order_type']}"
                )

    def _determine_strategy(self, signal: dict, impact_class: str, confidence: float) -> dict:
        """Giriş stratejisini belirle"""
        strength = signal.get('strength', 'MODERATE')
        position_size = signal.get('position_size_usdt', 100)

        # CRITICAL haber + güçlü sinyal = anında gir
        if impact_class == 'CRITICAL' and strength in ('STRONG', 'MODERATE'):
            return {
                'type': 'instant',
                'order_type': 'MARKET',
                'chunks': 1,
                'chunk_sizes': [1.0],  # %100 tek seferde
                'chunk_delay_seconds': 0,
                'timeout_seconds': 5,
                'reason': 'CRITICAL haber - anında giriş',
            }

        # HIGH haber = hızlı giriş
        if impact_class == 'HIGH':
            return {
                'type': 'fast',
                'order_type': 'LIMIT',
                'chunks': 2,
                'chunk_sizes': [0.6, 0.4],  # %60 + %40
                'chunk_delay_seconds': 10,
                'timeout_seconds': 30,
                'reason': 'HIGH haber - hızlı limit emir',
            }

        # Düşük güven = çok dikkatli
        if confidence < 0.4:
            return {
                'type': 'careful',
                'order_type': 'LIMIT',
                'chunks': 5,
                'chunk_sizes': [0.15, 0.15, 0.2, 0.25, 0.25],
                'chunk_delay_seconds': 60,
                'timeout_seconds': 300,
                'reason': 'Düşük güven - kademeli dikkatli giriş',
            }

        # MEDIUM ve normal = kademeli giriş
        return {
            'type': 'gradual',
            'order_type': 'LIMIT',
            'chunks': 3,
            'chunk_sizes': [0.4, 0.3, 0.3],  # %40 + %30 + %30
            'chunk_delay_seconds': 30,
            'timeout_seconds': 120,
            'reason': 'Normal sinyal - kademeli giriş',
        }
