"""
Telegram MTProto interaktif authorize scripti.

İlk çalıştırmada telefon numarası + SMS kodu + (varsa) 2FA şifresi sorar.
Session dosyası oluştuktan sonra ikinci ve sonraki çalıştırmalarda
otomatik login sağlar.

Çalıştırma:
    cd backend
    python scripts/telegram_auth.py

SMS kodu "Telegram" adlı resmi Telegram hesabından gelir (uygulamadan
göreceksin). Test çağrısı olmadığı için numaraya SMS gelmeyebilir.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
ENV_PATH = ROOT_DIR / '.env'

load_dotenv(ENV_PATH)

API_ID = os.environ.get('TELEGRAM_API_ID', '').strip()
API_HASH = os.environ.get('TELEGRAM_API_HASH', '').strip()
SESSION_NAME = os.environ.get('TELEGRAM_SESSION_NAME', 'mirofish_listener').strip()
CHANNELS = [
    c.strip() for c in os.environ.get(
        'TELEGRAM_CHANNELS',
        'tree_of_alpha,WhaleAlertFeed,BWEnews,binance_announcements'
    ).split(',') if c.strip()
]


def mask(value: str, keep_head: int = 4, keep_tail: int = 2) -> str:
    if not value:
        return '(bos)'
    if len(value) <= keep_head + keep_tail:
        return '*' * len(value)
    return f"{value[:keep_head]}...{value[-keep_tail:]}"


async def main():
    if not API_ID or not API_HASH:
        print(f'HATA: TELEGRAM_API_ID / TELEGRAM_API_HASH .env dosyasinda yok ({ENV_PATH})')
        sys.exit(1)
    try:
        api_id_int = int(API_ID)
    except ValueError:
        print(f'HATA: TELEGRAM_API_ID sayi olmali, bulunan: {mask(API_ID)}')
        sys.exit(1)

    print(f'API_ID: {mask(API_ID)}')
    print(f'API_HASH: {mask(API_HASH, 6, 4)}')
    print(f'Session: {SESSION_NAME} -> {BACKEND_DIR / (SESSION_NAME + ".session")}')
    print(f'Kanallar: {CHANNELS}')
    print()

    from telethon import TelegramClient, events
    from telethon.errors import (
        PhoneNumberInvalidError,
        PhoneCodeInvalidError,
        SessionPasswordNeededError,
        FloodWaitError,
    )

    session_path = str(BACKEND_DIR / SESSION_NAME)
    client = TelegramClient(session_path, api_id_int, API_HASH)

    try:
        await client.connect()
    except Exception as e:
        print(f'HATA: Telegram sunucusuna baglanilamadi: {e}')
        sys.exit(2)

    if not await client.is_user_authorized():
        print('Bu session henuz authorize edilmemis. Interaktif giris basliyor.')
        print('Numarayi uluslararasi formatta gir: +905XXXXXXXXX')
        try:
            phone = input('Telefon: ').strip()
            await client.send_code_request(phone)
            code = input('SMS kodu (Telegram uygulamasinda "Telegram" hesabindan gelir): ').strip()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                import getpass
                pw = getpass.getpass('2FA sifresi: ')
                await client.sign_in(password=pw)
        except PhoneNumberInvalidError:
            print('HATA: Telefon formati yanlis. +905XXXXXXXXX seklinde olmali.')
            await client.disconnect()
            sys.exit(3)
        except PhoneCodeInvalidError:
            print('HATA: SMS kodu yanlis.')
            await client.disconnect()
            sys.exit(3)
        except FloodWaitError as e:
            print(f'HATA: Cok sik deneme, {e.seconds} saniye bekle.')
            await client.disconnect()
            sys.exit(3)

    me = await client.get_me()
    print(f'\nGiris basarili: {me.first_name} (@{me.username or "?"}) id={me.id}')
    print(f'Session dosyasi kaydedildi: {session_path}.session')

    # 30 saniye boyunca kanallardan push mesaji dinle
    msg_count = 0

    @client.on(events.NewMessage(chats=CHANNELS))
    async def on_new(event):
        nonlocal msg_count
        msg_count += 1
        chat = await event.get_chat()
        name = getattr(chat, 'username', None) or getattr(chat, 'title', 'unknown')
        preview = (event.message.message or '').split('\n', 1)[0][:100]
        print(f'  [{name}] {preview}')

    print('\n30 saniye dinleniyor (kanallardan mesaj gelirse goreceksin)...')
    try:
        await asyncio.wait_for(client.run_until_disconnected(), timeout=30)
    except asyncio.TimeoutError:
        pass
    finally:
        await client.disconnect()

    print(f'\nDinleme bitti. Gelen mesaj sayisi: {msg_count}')
    print('\nKurulum tamam. Artik run_trading.py Telegram listener ile acilabilir.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\nIptal edildi.')
