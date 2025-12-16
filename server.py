# server.py - ГЛАВНЫЙ СЕРВЕР ДЛЯ AXIOM TRACKER (WITH LOGGING - ONLY SENT TOKENS)
import asyncio
import websockets
import json
import sys
import time
from datetime import datetime
from threading import Thread
from database import Database
from user_manager import UserManager
import importlib.util

# Импортируем парсер токенов
spec = importlib.util.spec_from_file_location("axiom_module", "new_ws_final_V1.py")
axiom_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(axiom_module)


class TokenServer:
    """WebSocket сервер для рассылки токенов клиентам"""

    def __init__(self, host="0.0.0.0", port=8765, auth_file="auth_data.json",
                 twitter_api_key="", avg_tokens_count=10):
        self.host = host
        self.port = port
        self.auth_file = auth_file
        self.twitter_api_key = twitter_api_key
        self.avg_tokens_count = avg_tokens_count

        # База данных
        self.db = Database()

        # Активные клиенты: {websocket: {"user_id": int, "username": str, "manager": UserManager}}
        self.clients = {}

        # Очередь токенов (парсер кладёт → сервер забирает)
        self.token_queue = None  # создастся в async контексте

        # Event loop сервера (для callback из парсера)
        self.server_loop = None

        # Парсер токенов
        self.tracker = None
        self.tracker_thread = None

        # Статистика
        self.stats = {
            "tokens_received": 0,
            "tokens_sent": 0,
            "tokens_filtered": 0,
            "start_time": time.time()
        }

    def log(self, message, level="INFO"):
        """Логирование с flush"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")
        sys.stdout.flush()

    # ============================================================================
    # АУТЕНТИФИКАЦИЯ КЛИЕНТА
    # ============================================================================

    async def authenticate_client(self, websocket):
        """
        Аутентификация клиента по API key.
        Возвращает: {"user_id": int, "username": str, "settings": dict} или None
        """
        try:
            # Ждём сообщение с API key (таймаут 10 сек)
            auth_message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            auth_data = json.loads(auth_message)

            api_key = auth_data.get("api_key")

            if not api_key:
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "API key required"
                }))
                return None

            # Проверяем в базе
            if not self.db.is_user_active(api_key):
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Invalid or expired API key"
                }))
                return None

            # Получаем данные пользователя
            user = self.db.get_user_by_api_key(api_key)
            user_id = user['id']
            username = user['username']

            # Загружаем настройки
            settings = self.db.get_user_settings(user_id)

            # Загружаем whitelist/blacklist
            whitelist = self.db.get_user_whitelist(user_id)
            blacklist = self.db.get_user_blacklist(user_id)

            # Отправляем успешную аутентификацию
            await websocket.send(json.dumps({
                "type": "auth_success",
                "username": username,
                "settings": settings,
                "whitelist": whitelist,
                "blacklist": blacklist
            }))

            self.log(f"✅ Authenticated: {username} (ID: {user_id})")

            # ЛОГИРУЕМ ПОДКЛЮЧЕНИЕ В БД
            self.db.log_connection(
                user_id=user_id,
                action="connected",
                ip_address=str(websocket.remote_address[0]) if websocket.remote_address else None
            )

            return {
                "user_id": user_id,
                "username": username,
                "settings": settings
            }

        except asyncio.TimeoutError:
            self.log("⏱️ Auth timeout", "WARN")
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Authentication timeout"
            }))
            return None
        except json.JSONDecodeError:
            self.log("❌ Invalid JSON in auth", "ERROR")
            return None
        except Exception as e:
            self.log(f"❌ Auth error: {e}", "ERROR")
            return None

    # ============================================================================
    # ОБРАБОТКА КОМАНД ОТ КЛИЕНТА
    # ============================================================================

    async def handle_command(self, websocket, user_id, username, message):
        """Обработка команд от клиента"""
        try:
            data = json.loads(message)
            command = data.get("command")
            request_id = data.get("request_id")

            if command == "get_settings":
                # Получить текущие настройки
                settings = self.db.get_user_settings(user_id)
                await websocket.send(json.dumps({
                    "request_id": request_id,
                    "type": "settings",
                    "data": settings
                }))

            elif command == "update_settings":
                # Обновить настройки
                params = data.get("params", {})
                self.db.update_user_settings(user_id, **params)

                # ЛОГИРУЕМ ЗАПРОС
                self.db.log_request(
                    user_id=user_id,
                    request_type="update_settings",
                    request_data=params,
                    success=True
                )

                # Обновляем в кэше клиента
                if websocket in self.clients:
                    manager = self.clients[websocket]["manager"]
                    manager.settings = self.db.get_user_settings(user_id)

                # Подтверждение
                await websocket.send(json.dumps({
                    "request_id": request_id,
                    "type": "settings_updated",
                    "data": manager.settings
                }))

                self.log(f"⚙️ {username} updated settings: {list(params.keys())}")

            elif command == "add_whitelist":
                # Добавить в whitelist
                dev_wallet = data.get("dev_wallet")
                token_name = data.get("token_name")
                token_ticker = data.get("token_ticker")

                if dev_wallet:
                    added = self.db.add_to_whitelist(user_id, dev_wallet, token_name, token_ticker)

                    # ЛОГИРУЕМ ЗАПРОС
                    self.db.log_request(
                        user_id=user_id,
                        request_type="add_to_whitelist",
                        request_data={"dev_wallet": dev_wallet, "name": token_name, "ticker": token_ticker},
                        success=added
                    )

                    await websocket.send(json.dumps({
                        "request_id": request_id,
                        "type": "whitelist_updated",
                        "action": "added",
                        "dev_wallet": dev_wallet,
                        "token_name": token_name,
                        "token_ticker": token_ticker,
                        "success": added
                    }))
                    self.log(f"➕ {username} added to whitelist: {dev_wallet[:12]}...")

            elif command == "remove_whitelist":
                # Удалить из whitelist
                dev_wallet = data.get("dev_wallet")

                if dev_wallet:
                    removed = self.db.remove_from_whitelist(user_id, dev_wallet)

                    # ЛОГИРУЕМ ЗАПРОС
                    self.db.log_request(
                        user_id=user_id,
                        request_type="remove_from_whitelist",
                        request_data={"dev_wallet": dev_wallet},
                        success=removed
                    )

                    await websocket.send(json.dumps({
                        "request_id": request_id,
                        "type": "whitelist_updated",
                        "action": "removed",
                        "dev_wallet": dev_wallet,
                        "success": removed
                    }))
                    self.log(f"➖ {username} removed from whitelist: {dev_wallet[:12]}...")

            elif command == "add_blacklist":
                # Добавить в blacklist
                dev_wallet = data.get("dev_wallet")
                token_name = data.get("token_name")
                token_ticker = data.get("token_ticker")

                if dev_wallet:
                    added = self.db.add_to_blacklist(user_id, dev_wallet, token_name, token_ticker)

                    # ЛОГИРУЕМ ЗАПРОС
                    self.db.log_request(
                        user_id=user_id,
                        request_type="add_to_blacklist",
                        request_data={"dev_wallet": dev_wallet, "name": token_name, "ticker": token_ticker},
                        success=added
                    )

                    await websocket.send(json.dumps({
                        "request_id": request_id,
                        "type": "blacklist_updated",
                        "action": "added",
                        "dev_wallet": dev_wallet,
                        "token_name": token_name,
                        "token_ticker": token_ticker,
                        "success": added
                    }))
                    self.log(f"➕ {username} added to blacklist: {dev_wallet[:12]}...")

            elif command == "remove_blacklist":
                # Удалить из blacklist
                dev_wallet = data.get("dev_wallet")

                if dev_wallet:
                    removed = self.db.remove_from_blacklist(user_id, dev_wallet)

                    # ЛОГИРУЕМ ЗАПРОС
                    self.db.log_request(
                        user_id=user_id,
                        request_type="remove_from_blacklist",
                        request_data={"dev_wallet": dev_wallet},
                        success=removed
                    )

                    await websocket.send(json.dumps({
                        "request_id": request_id,
                        "type": "blacklist_updated",
                        "action": "removed",
                        "dev_wallet": dev_wallet,
                        "success": removed
                    }))
                    self.log(f"➖ {username} removed from blacklist: {dev_wallet[:12]}...")

            elif command == "get_whitelist":
                # Получить whitelist
                whitelist = self.db.get_user_whitelist(user_id)
                await websocket.send(json.dumps({
                    "request_id": request_id,
                    "type": "whitelist",
                    "data": whitelist
                }))

            elif command == "get_blacklist":
                # Получить blacklist
                blacklist = self.db.get_user_blacklist(user_id)
                await websocket.send(json.dumps({
                    "request_id": request_id,
                    "type": "blacklist",
                    "data": blacklist
                }))

            elif command == "ping":
                # Проверка соединения
                await websocket.send(json.dumps({
                    "request_id": request_id,
                    "type": "pong",
                    "timestamp": time.time()
                }))

            else:
                await websocket.send(json.dumps({
                    "request_id": request_id,
                    "type": "error",
                    "message": f"Unknown command: {command}"
                }))

        except json.JSONDecodeError:
            self.log(f"❌ Invalid JSON from {username}", "ERROR")
        except Exception as e:
            self.log(f"❌ Command error for {username}: {e}", "ERROR")

    # ============================================================================
    # ОБРАБОТКА КЛИЕНТА
    # ============================================================================

    async def handle_client(self, websocket, path):
        """Обработка подключения клиента"""

        # Аутентификация
        auth_result = await self.authenticate_client(websocket)

        if not auth_result:
            await websocket.close()
            return

        user_id = auth_result["user_id"]
        username = auth_result["username"]

        # Создаём UserManager для фильтрации
        user_manager = UserManager(self.db, user_id)

        # Добавляем в список активных клиентов
        self.clients[websocket] = {
            "user_id": user_id,
            "username": username,
            "manager": user_manager
        }

        self.log(f"📡 Connected: {username} | Total clients: {len(self.clients)}")

        try:
            # Слушаем команды от клиента
            async for message in websocket:
                await self.handle_command(websocket, user_id, username, message)

        except websockets.exceptions.ConnectionClosed:
            self.log(f"🔌 Disconnected: {username}")
        except Exception as e:
            self.log(f"❌ Client error for {username}: {e}", "ERROR")
        finally:
            # Удаляем из списка активных
            if websocket in self.clients:
                # ЛОГИРУЕМ ОТКЛЮЧЕНИЕ
                self.db.log_connection(
                    user_id=self.clients[websocket]["user_id"],
                    action="disconnected"
                )

                del self.clients[websocket]
            self.log(f"👋 Removed: {username} | Total clients: {len(self.clients)}")

    # ============================================================================
    # РАССЫЛКА ТОКЕНОВ КЛИЕНТАМ
    # ============================================================================

    async def broadcast_tokens(self):
        """
        Фоновая задача: забирает токены из очереди и рассылает клиентам.
        Работает постоянно в background.
        """
        self.log("🔄 Token broadcast loop started")

        while True:
            try:
                # Ждём новый токен из очереди
                token = await self.token_queue.get()

                self.stats["tokens_received"] += 1

                # ВСЕГДА выводим в консоль сервера
                self._log_token_to_console(token)

                # Рассылаем клиентам (параллельно), если они есть
                if self.clients:
                    await self._send_to_clients(token)
                else:
                    # Нет клиентов, просто логируем
                    self.stats["tokens_filtered"] += 1

            except Exception as e:
                self.log(f"❌ Broadcast error: {e}", "ERROR")

    async def print_statistics(self):
        """Фоновая задача: вывод статистики каждые 5 минут"""
        await asyncio.sleep(300)  # ждём 5 минут перед первым выводом

        while True:
            try:
                uptime = time.time() - self.stats["start_time"]
                uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"

                print("\n" + "=" * 80)
                print("📊 SERVER STATISTICS")
                print("=" * 80)
                print(f"   Uptime:          {uptime_str}")
                print(f"   Connected:       {len(self.clients)} client(s)")
                print(f"   Tokens received: {self.stats['tokens_received']}")
                print(f"   Tokens sent:     {self.stats['tokens_sent']}")
                print(f"   Tokens filtered: {self.stats['tokens_filtered']}")

                if self.clients:
                    print(f"   Active users:")
                    for client_info in self.clients.values():
                        print(f"     • {client_info['username']}")
                else:
                    print(f"   Active users:    None")

                print("=" * 80 + "\n")
                sys.stdout.flush()

                await asyncio.sleep(300)  # каждые 5 минут

            except Exception as e:
                self.log(f"❌ Statistics error: {e}", "ERROR")
                await asyncio.sleep(300)

    async def save_stats_periodically(self):
        """Сохранение статистики сервера в БД каждые 5 минут"""
        await asyncio.sleep(300)  # Ждём 5 минут перед первым сохранением

        while True:
            try:
                # Сохраняем текущую статистику в БД
                self.db.save_server_stats(
                    active_connections=len(self.clients),
                    tokens_received=self.stats["tokens_received"],
                    tokens_sent=self.stats["tokens_sent"],
                    tokens_filtered=self.stats["tokens_filtered"]
                )

                self.log("💾 Server stats saved to database")

                await asyncio.sleep(300)  # Каждые 5 минут

            except Exception as e:
                self.log(f"❌ Save stats error: {e}", "ERROR")
                await asyncio.sleep(300)

    def _log_token_to_console(self, token):
        """Вывод токена в консоль сервера"""
        has_twitter = token.get('twitter', '') and token['twitter'].strip() and token['twitter'] != 'null'
        is_post = 'status/' in token.get('twitter', '')

        print("\n" + "=" * 80)
        if has_twitter and not is_post:
            print("ТОКЕН НАЙДЕН С TWITTER!")
        elif is_post:
            print("ТОКЕН С ПОСТОМ TWITTER (ПРОПУЩЕН)")
        else:
            print("НОВЫЙ ТОКЕН")

        print("=" * 80)
        print(f"Token Address:    {token.get('token_address', 'N/A')}")
        print(f"Pair Address:     {token.get('pair_address', 'N/A')}")
        print(f"Token Name:       {token.get('token_name', 'N/A')}")
        print(f"Token Ticker:     {token.get('token_ticker', 'N/A')}")
        print(f"Deployer:         {token.get('deployer_address', 'N/A')}")
        print(f"Protocol:         {token.get('protocol', 'unknown')}")

        if is_post:
            print(f"Twitter:          Post URL (skipped) - {token.get('twitter', '')}")
        elif has_twitter:
            print(f"Twitter:          {token.get('twitter', '')}")
        else:
            print(f"Twitter:          Not found")

        # DEV STATS
        dev_mcap_info = token.get('dev_mcap_info', {})
        if dev_mcap_info:
            if dev_mcap_info.get('error'):
                print(f"Dev Stats:        {dev_mcap_info['error']}")
            elif dev_mcap_info.get('is_first_token'):
                print(f"Dev Stats:        First token (no history)")
                print(f"Migrated Tokens:  N/A (first token)")
                print(f"Non-Migrated:     N/A (first token)")
                print(f"Percentage:       N/A (first token)")
            else:
                cached_str = f" (cached {dev_mcap_info.get('cache_age', 0)}s)" if dev_mcap_info.get('cached') else ""
                valid_tokens = dev_mcap_info.get('valid_tokens', 0)
                api_used = dev_mcap_info.get('api_used', 'unknown')

                print(
                    f"Dev Avg MC:       ${dev_mcap_info.get('avg_mcap', 0):,.2f} ({valid_tokens} tokens){cached_str} via {api_used}")

                ath_count = dev_mcap_info.get('ath_calculated_for', 0)
                ath_str = f" (ATH for {ath_count} tokens)" if ath_count > 0 else ""
                print(f"Dev Avg ATH MC:   ${dev_mcap_info.get('avg_ath_mcap', 0):,.2f}{ath_str}")

                migrated = token.get('migrated', 0)
                total = token.get('total', 0)
                percentage = token.get('percentage', 0)

                print(f"Migrated Tokens:  {migrated}/{total}")
                print(f"Non-Migrated:     {total - migrated}/{total}")
                print(f"Percentage:       {percentage:.2f}%")
        else:
            print(f"Dev Stats:        Loading...")

        # TWITTER STATS
        twitter_stats = token.get('twitter_stats', {})
        if has_twitter and not is_post and twitter_stats and not twitter_stats.get("error"):
            print("-" * 80)
            print("TWITTER СТАТИСТИКА:")
            if "community_followers" in twitter_stats:
                print(f"   Community Members:    {twitter_stats.get('community_followers', 0):,}")
                if twitter_stats.get('admin_username'):
                    print(f"   Admin:                @{twitter_stats['admin_username']}")
                    print(f"   Admin Followers:      {twitter_stats.get('admin_followers', 0):,}")
                    print(f"   Admin Following:      {twitter_stats.get('admin_following', 0):,}")
            elif "followers" in twitter_stats:
                print(f"   Followers:            {twitter_stats.get('followers', 0):,}")
                print(f"   Following:            {twitter_stats.get('following', 0):,}")

        print("-" * 80)
        processing_ms = token.get('processing_time_ms', 0)
        print(f"Processing:       {processing_ms / 1000:.3f}s ({processing_ms:.2f}ms)")
        print("=" * 80)
        sys.stdout.flush()

    async def _send_to_clients(self, token):
        """Отправка токена клиентам с фильтрацией"""

        # Подготавливаем данные для фильтрации
        filter_data = self._prepare_filter_data(token)

        # Отправляем параллельно всем клиентам
        tasks = []
        sent_to = []
        filtered_for = []

        for websocket, client_info in list(self.clients.items()):
            username = client_info["username"]
            manager = client_info["manager"]

            try:
                # Фильтруем токен
                if manager.filter_token(filter_data):
                    # Токен прошёл фильтры → отправляем
                    task = websocket.send(json.dumps({
                        "type": "token",
                        "data": token
                    }))
                    tasks.append(task)
                    sent_to.append(username)
                else:
                    # Токен отфильтрован - ТОЛЬКО счётчик
                    self.stats["tokens_filtered"] += 1
                    filtered_for.append(username)

            except Exception as e:
                self.log(f"❌ Error sending to {username}: {e}", "ERROR")

        # Ждём отправки всем клиентам параллельно
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            self.stats["tokens_sent"] += len(sent_to)

        # ✅ ЛОГИРУЕМ ТОКЕН ОДИН РАЗ - если хотя бы кому-то отправили
        if sent_to:
            self.db.log_token_sent(
                user_id=None,  # Не привязываем к конкретному пользователю
                token_address=token.get("token_address"),
                token_name=token.get("token_name"),
                token_ticker=token.get("token_ticker"),
                filtered=False
            )

        # Логируем результат
        if sent_to:
            print(f"✅ Sent to {len(sent_to)} client(s): {', '.join(sent_to)}")
        if filtered_for:
            print(f"🚫 Filtered {len(filtered_for)} client(s): {', '.join(filtered_for)}")

        print("")  # пустая строка для читаемости
        sys.stdout.flush()

    def _prepare_filter_data(self, token):
        """Подготовка данных токена для фильтрации"""
        dev_mcap_info = token.get('dev_mcap_info', {})

        return {
            "deployer_address": token.get('deployer_address', ''),
            "avg_mcap": dev_mcap_info.get('avg_mcap', 0),
            "avg_ath_mcap": token.get('avg_ath_mcap', 0),
            "migration_percent": token.get('percentage', 0),
            "protocol": token.get('protocol', 'unknown'),
            "twitter_stats": token.get('twitter_stats', {}),
            "token_ticker": token.get('token_ticker', ''),
            "token_name": token.get('token_name', '')
        }

    # ============================================================================
    # ИНТЕГРАЦИЯ С ПАРСЕРОМ
    # ============================================================================

    def on_token_ready(self, token_data, timing_data=None):
        """Callback функция для парсера"""
        if self.server_loop and self.token_queue:
            asyncio.run_coroutine_threadsafe(
                self.token_queue.put(token_data),
                self.server_loop
            )

    def start_tracker(self):
        """Запуск парсера токенов в отдельном потоке"""

        def run_tracker():
            self.log("🔄 Starting Axiom Tracker...")

            self.tracker = axiom_module.AxiomTracker(
                auth_file=self.auth_file,
                twitter_api_key=self.twitter_api_key,
                avg_tokens_count=self.avg_tokens_count
            )

            original_output = self.tracker._output_token_info

            def custom_output(data, processing_time, source, twitter_stats=None,
                              migrated=None, non_migrated=None, percentage=None,
                              cache_time=0, dev_mcap_info=None):

                try:
                    if dev_mcap_info and not dev_mcap_info.get('error') and not dev_mcap_info.get('is_first_token'):
                        migrated = dev_mcap_info.get('migrated', 0)
                        total = dev_mcap_info.get('total', 0)
                        percentage = (migrated / total * 100) if total > 0 else 0.0
                    else:
                        migrated = 0
                        total = 0
                        percentage = 0.0

                    token_data = {
                        'token_name': data['token_name'],
                        'token_ticker': data['token_ticker'],
                        'token_address': data['token_address'],
                        'deployer_address': data['deployer_address'],
                        'twitter': data['twitter'],
                        'pair_address': data['pair_address'],
                        'twitter_stats': twitter_stats or {},
                        'dev_mcap_info': dev_mcap_info or {},
                        'migrated': migrated,
                        'total': total,
                        'percentage': round(percentage, 2),
                        'processing_time_ms': int(processing_time * 1000),
                        'created_at': data.get('created_at', ''),
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'avg_ath_mcap': dev_mcap_info.get('avg_ath_mcap',
                                                          0) if dev_mcap_info and 'error' not in dev_mcap_info else 0,
                        'avg_tokens_count': self.tracker.avg_tokens_count,
                        'protocol': data.get('protocol', 'unknown'),
                        'is_first_token': dev_mcap_info.get('is_first_token', False) if dev_mcap_info else False
                    }

                    token_data = {k: v for k, v in token_data.items() if v is not None}

                    if 'error' in token_data.get('dev_mcap_info', {}):
                        token_data['dev_mcap_info'] = {'avg_mcap': 0, 'avg_ath_mcap': 0, 'cached': False}

                    self.on_token_ready(token_data)

                except Exception as e:
                    self.log(f"❌ Error formatting token: {e}", "ERROR")

            self.tracker._output_token_info = custom_output
            self.tracker.start()

        self.tracker_thread = Thread(target=run_tracker, daemon=True)
        self.tracker_thread.start()

        time.sleep(3)
        self.log("✅ Axiom Tracker started")

    # ============================================================================
    # ЗАПУСК СЕРВЕРА
    # ============================================================================

    async def start(self):
        """Запуск сервера"""

        self.server_loop = asyncio.get_event_loop()
        self.token_queue = asyncio.Queue()

        # Баннер
        print("=" * 80)
        print("🚀 AXIOM TOKEN SERVER V2.0")
        print("=" * 80)
        print(f"📡 Server: ws://{self.host}:{self.port}")
        print(f"📊 Database: {self.db.db_file}")
        print(f"⚡ Avg tokens count: {self.avg_tokens_count}")
        print(f"⚡ Миграции и Avg MCAP: по ВСЕМ токенам")
        print(f"⚡ Avg ATH MCAP: по последним {self.avg_tokens_count} токенам")
        print(f"💾 Token logs: ONLY SENT TOKENS (filtered out are not logged)")
        print("=" * 80)
        sys.stdout.flush()

        # Запускаем парсер
        self.start_tracker()

        # Запускаем фоновые задачи
        asyncio.create_task(self.broadcast_tokens())
        asyncio.create_task(self.print_statistics())
        asyncio.create_task(self.save_stats_periodically())

        # Запускаем WebSocket сервер
        self.log(f"✅ WebSocket server starting on {self.host}:{self.port}...")

        async with websockets.serve(self.handle_client, self.host, self.port):
            self.log("✅ Server running! Waiting for clients...")
            print("=" * 80 + "\n")
            sys.stdout.flush()

            await asyncio.Future()

    def stop(self):
        """Остановка сервера"""
        self.log("🛑 Stopping server...")
        if self.tracker:
            self.tracker.stop()
        self.log("✅ Server stopped")


# ============================================================================
# ЗАПУСК
# ============================================================================

def run_server():
    """Точка входа"""

    sys.stdout.reconfigure(line_buffering=True)

    server = TokenServer(
        host="0.0.0.0",
        port=8765,
        auth_file="auth_data.json",
        twitter_api_key="new1_d84d121d635d4b2aa0680a22e25c08d2",
        avg_tokens_count=10
    )

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
        sys.stdout.flush()
    except Exception as e:
        print(f"\n\n❌ Server crashed: {e}")
        sys.stdout.flush()


if __name__ == "__main__":
    run_server()