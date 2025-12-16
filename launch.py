#!/usr/bin/env python3
# launch.py - Запуск сервера + бота БЕЗ ОШИБОК (исправленная версия)

import threading
import asyncio
import time
import sys
import os

# Добавляем корень проекта
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from server import run_server
from telegram_bot.telegram_bot import AxiomBot


def run_telegram_bot():
    """Запуск бота с собственным event loop"""
    print("\n" + "=" * 60)
    print("🤖 ЗАПУСК TELEGRAM БОТА")
    print("=" * 60)

    # Создаём НОВЫЙ event loop для этого потока
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        bot = AxiomBot()
        # Запускаем polling внутри этого loop
        loop.run_until_complete(bot.app.run_polling(drop_pending_updates=True))
    except Exception as e:
        print(f"\n❌ Ошибка в Telegram боте: {e}")
    finally:
        loop.close()


def run_websocket_server():
    """Запуск сервера"""
    print("\n" + "=" * 60)
    print("🚀 ЗАПУСК AXIOM TOKEN SERVER")
    print("=" * 60)
    try:
        run_server()
    except Exception as e:
        print(f"\n❌ Ошибка сервера: {e}")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║                  AXIOM TRACKER — FULL LAUNCH                 ║
║          Одновременный запуск сервера + бота                ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Сервер в отдельном потоке
    server_thread = threading.Thread(target=run_websocket_server, daemon=False)
    server_thread.start()

    time.sleep(3)  # Чтобы логи не смешались

    # Бот в отдельном потоке с собственным loop
    bot_thread = threading.Thread(target=run_telegram_bot, daemon=False)
    bot_thread.start()

    try:
        server_thread.join()
        bot_thread.join()
    except KeyboardInterrupt:
        print("\n\n🛑 Остановка по Ctrl+C")
        sys.exit(0)