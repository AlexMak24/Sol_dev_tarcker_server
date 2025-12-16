# database.py - РАСШИРЕННАЯ ВЕРСИЯ С ЛОГАМИ И TELEGRAM ID
import sqlite3
import secrets
import json
from datetime import datetime, timedelta


class Database:
    def __init__(self, db_file="axiom_server.db"):
        self.db_file = db_file
        self.init_database()

    def init_database(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Таблица пользователей (+ telegram_id и telegram_username)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                telegram_username TEXT,
                api_key TEXT UNIQUE NOT NULL,
                telegram_id INTEGER UNIQUE,
                is_admin INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        ''')

        # Расширенная таблица настроек
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                enable_avg_mcap INTEGER DEFAULT 0,
                min_avg_mcap REAL DEFAULT 0,
                enable_avg_ath_mcap INTEGER DEFAULT 0,
                min_avg_ath_mcap REAL DEFAULT 0,
                enable_migrations INTEGER DEFAULT 0,
                min_migration_percent REAL DEFAULT 0,
                dev_tokens_count INTEGER DEFAULT 10,
                enable_protocol_filter INTEGER DEFAULT 0,
                protocols TEXT DEFAULT '{}',
                enable_twitter_user INTEGER DEFAULT 0,
                min_twitter_followers INTEGER DEFAULT 0,
                enable_twitter_community INTEGER DEFAULT 0,
                min_community_members INTEGER DEFAULT 0,
                min_admin_followers INTEGER DEFAULT 0,
                use_and_mode INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        # Whitelist/Blacklist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                dev_wallet TEXT NOT NULL,
                token_name TEXT,
                token_ticker TEXT,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, dev_wallet),
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                dev_wallet TEXT NOT NULL,
                token_name TEXT,
                token_ticker TEXT,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, dev_wallet),
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        # === НОВЫЕ ТАБЛИЦЫ ДЛЯ ЛОГОВ ===

        # Логи подключений/отключений
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS connection_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        # Логи запросов (изменение настроек, whitelist/blacklist)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                request_type TEXT NOT NULL,
                request_data TEXT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                success INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        # Логи отправленных токенов (user_id может быть NULL если токен записан глобально)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS token_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                token_address TEXT NOT NULL,
                token_name TEXT,
                token_ticker TEXT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                filtered INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        # Статистика сервера
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS server_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                active_connections INTEGER DEFAULT 0,
                tokens_received INTEGER DEFAULT 0,
                tokens_sent INTEGER DEFAULT 0,
                tokens_filtered INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()
        print("[DB] ✅ Database initialized with logs support")

    def generate_api_key(self):
        return secrets.token_urlsafe(32)

    # ============================================================================
    # ПОЛЬЗОВАТЕЛИ
    # ============================================================================

    def add_user(self, username, telegram_username=None, subscription_days=30, telegram_id=None, is_admin=False):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        api_key = self.generate_api_key()
        created_at = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(days=subscription_days)).isoformat()

        try:
            cursor.execute('''
                INSERT INTO users (username, telegram_username, api_key, telegram_id, is_admin, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (username, telegram_username, api_key, telegram_id, 1 if is_admin else 0, created_at, expires_at))
            user_id = cursor.lastrowid

            # Создаём пустую запись настроек
            cursor.execute('INSERT INTO user_options (user_id) VALUES (?)', (user_id,))
            conn.commit()
            print(f"[DB] ✅ User added: {username} (ID: {user_id}, Admin: {is_admin}, TG: {telegram_username})")
            return api_key
        except sqlite3.IntegrityError as e:
            print(f"[DB] ❌ Error adding user: {e}")
            return None
        finally:
            conn.close()

    def get_user_by_api_key(self, api_key):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE api_key = ?', (api_key,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'telegram_username': user[2],
                'api_key': user[3],
                'telegram_id': user[4],
                'is_admin': bool(user[5]),
                'created_at': user[6],
                'expires_at': user[7],
                'is_active': bool(user[8])
            }
        return None

    def get_user_by_telegram_id(self, telegram_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'telegram_username': user[2],
                'api_key': user[3],
                'telegram_id': user[4],
                'is_admin': bool(user[5]),
                'created_at': user[6],
                'expires_at': user[7],
                'is_active': bool(user[8])
            }
        return None

    def link_telegram_account(self, user_id, telegram_id):
        """Привязать Telegram ID к пользователю"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        try:
            cursor.execute('UPDATE users SET telegram_id = ? WHERE id = ?', (telegram_id, user_id))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def get_user_by_username(self, username):
        """Найти пользователя по username"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'telegram_username': user[2],
                'api_key': user[3],
                'telegram_id': user[4],
                'is_admin': bool(user[5]),
                'created_at': user[6],
                'expires_at': user[7],
                'is_active': bool(user[8])
            }
        return None

    def get_user_by_id(self, user_id):
        """Найти пользователя по ID"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'telegram_username': user[2],
                'api_key': user[3],
                'telegram_id': user[4],
                'is_admin': bool(user[5]),
                'created_at': user[6],
                'expires_at': user[7],
                'is_active': bool(user[8])
            }
        return None

    def is_user_active(self, api_key):
        user = self.get_user_by_api_key(api_key)
        if not user or not user['is_active']:
            return False
        expires_at = datetime.fromisoformat(user['expires_at'])
        return datetime.now() < expires_at

    def get_all_users(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users')
        users = cursor.fetchall()
        conn.close()
        return [{
            'id': u[0],
            'username': u[1],
            'telegram_username': u[2],
            'api_key': u[3],
            'telegram_id': u[4],
            'is_admin': bool(u[5]),
            'created_at': u[6],
            'expires_at': u[7],
            'is_active': bool(u[8])
        } for u in users]

    def update_user_status(self, user_id, is_active):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_active = ? WHERE id = ?', (is_active, user_id))
        conn.commit()
        conn.close()

    def extend_subscription(self, user_id, days):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT expires_at FROM users WHERE id = ?', (user_id,))
        result = cursor.fetchone()
        if result:
            current_expires = datetime.fromisoformat(result[0])
            new_expires = current_expires + timedelta(days=days)
            cursor.execute('UPDATE users SET expires_at = ? WHERE id = ?', (new_expires.isoformat(), user_id))
            conn.commit()
        conn.close()

    def delete_user(self, user_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_options WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_whitelist WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_blacklist WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM connection_logs WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM request_logs WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM token_logs WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()

    # ============================================================================
    # НАСТРОЙКИ (без изменений)
    # ============================================================================

    def get_user_settings(self, user_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_options WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {}

        protocols_str = row[10] if len(row) > 10 else '{}'
        try:
            protocols = json.loads(protocols_str)
        except:
            protocols = {}

        return {
            'enable_avg_mcap': bool(row[2]),
            'min_avg_mcap': row[3] or 0,
            'enable_avg_ath_mcap': bool(row[4]),
            'min_avg_ath_mcap': row[5] or 0,
            'enable_migrations': bool(row[6]),
            'min_migration_percent': row[7] or 0,
            'dev_tokens_count': row[8] if len(row) > 8 else 10,
            'enable_protocol_filter': bool(row[9]) if len(row) > 9 else False,
            'protocols': protocols,
            'enable_twitter_user': bool(row[11]) if len(row) > 11 else False,
            'min_twitter_followers': row[12] if len(row) > 12 else 0,
            'enable_twitter_community': bool(row[13]) if len(row) > 13 else False,
            'min_community_members': row[14] if len(row) > 14 else 0,
            'min_admin_followers': row[15] if len(row) > 15 else 0,
            'use_and_mode': bool(row[16]) if len(row) > 16 else False
        }

    def update_user_settings(self, user_id, **kwargs):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute('SELECT id FROM user_options WHERE user_id = ?', (user_id,))
        exists = cursor.fetchone()
        if not exists:
            cursor.execute('INSERT INTO user_options (user_id) VALUES (?)', (user_id,))
            conn.commit()

        updates = []
        values = []

        allowed_keys = [
            'enable_avg_mcap', 'min_avg_mcap',
            'enable_avg_ath_mcap', 'min_avg_ath_mcap',
            'enable_migrations', 'min_migration_percent',
            'dev_tokens_count',
            'enable_protocol_filter', 'protocols',
            'enable_twitter_user', 'min_twitter_followers',
            'enable_twitter_community', 'min_community_members', 'min_admin_followers',
            'use_and_mode'
        ]

        for key, value in kwargs.items():
            if key not in allowed_keys:
                continue

            if key == 'protocols':
                updates.append("protocols = ?")
                values.append(json.dumps(value) if isinstance(value, dict) else '{}')
            else:
                updates.append(f"{key} = ?")
                if isinstance(value, bool):
                    values.append(1 if value else 0)
                else:
                    values.append(value)

        if updates:
            values.append(user_id)
            query = f"UPDATE user_options SET {', '.join(updates)} WHERE user_id = ?"
            cursor.execute(query, values)
            conn.commit()

        conn.close()

    # ============================================================================
    # WHITELIST / BLACKLIST (без изменений)
    # ============================================================================

    def add_to_whitelist(self, user_id, dev_wallet, token_name=None, token_ticker=None):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO user_whitelist 
                (user_id, dev_wallet, token_name, token_ticker, added_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            ''', (user_id, dev_wallet, token_name, token_ticker))
            conn.commit()
            added = cursor.rowcount > 0
            return added
        finally:
            conn.close()

    def add_to_blacklist(self, user_id, dev_wallet, token_name=None, token_ticker=None):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO user_blacklist 
                (user_id, dev_wallet, token_name, token_ticker, added_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            ''', (user_id, dev_wallet, token_name, token_ticker))
            conn.commit()
            added = cursor.rowcount > 0
            return added
        finally:
            conn.close()

    def remove_from_whitelist(self, user_id, dev_wallet):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_whitelist WHERE user_id = ? AND dev_wallet = ?', (user_id, dev_wallet))
        conn.commit()
        removed = cursor.rowcount > 0
        conn.close()
        return removed

    def remove_from_blacklist(self, user_id, dev_wallet):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_blacklist WHERE user_id = ? AND dev_wallet = ?', (user_id, dev_wallet))
        conn.commit()
        removed = cursor.rowcount > 0
        conn.close()
        return removed

    def get_user_whitelist(self, user_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT dev_wallet, token_name, token_ticker, added_at FROM user_whitelist WHERE user_id = ? ORDER BY added_at DESC',
            (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [{"dev_wallet": r[0], "name": r[1], "ticker": r[2], "added": r[3]} for r in rows]

    def get_user_blacklist(self, user_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT dev_wallet, token_name, token_ticker, added_at FROM user_blacklist WHERE user_id = ? ORDER BY added_at DESC',
            (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [{"dev_wallet": r[0], "name": r[1], "ticker": r[2], "added": r[3]} for r in rows]

    def is_dev_whitelisted(self, user_id, dev_wallet):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM user_whitelist WHERE user_id = ? AND dev_wallet = ?', (user_id, dev_wallet))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def is_dev_blacklisted(self, user_id, dev_wallet):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM user_blacklist WHERE user_id = ? AND dev_wallet = ?', (user_id, dev_wallet))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    # ============================================================================
    # ЛОГИ - НОВЫЕ МЕТОДЫ
    # ============================================================================

    def log_connection(self, user_id, action, ip_address=None, user_agent=None):
        """Логировать подключение/отключение"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO connection_logs (user_id, action, timestamp, ip_address, user_agent)
            VALUES (?, ?, datetime('now'), ?, ?)
        ''', (user_id, action, ip_address, user_agent))
        conn.commit()
        conn.close()

    def log_request(self, user_id, request_type, request_data=None, success=True):
        """Логировать запрос от пользователя"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        data_str = json.dumps(request_data) if request_data else None
        cursor.execute('''
            INSERT INTO request_logs (user_id, request_type, request_data, timestamp, success)
            VALUES (?, ?, ?, datetime('now'), ?)
        ''', (user_id, request_type, data_str, 1 if success else 0))
        conn.commit()
        conn.close()

    def log_token_sent(self, user_id, token_address, token_name=None, token_ticker=None, filtered=False):
        """Логировать отправку токена пользователю"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO token_logs (user_id, token_address, token_name, token_ticker, timestamp, filtered)
            VALUES (?, ?, ?, ?, datetime('now'), ?)
        ''', (user_id, token_address, token_name, token_ticker, 1 if filtered else 0))
        conn.commit()
        conn.close()

    def save_server_stats(self, active_connections, tokens_received, tokens_sent, tokens_filtered):
        """Сохранить статистику сервера"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO server_stats (timestamp, active_connections, tokens_received, tokens_sent, tokens_filtered)
            VALUES (datetime('now'), ?, ?, ?, ?)
        ''', (active_connections, tokens_received, tokens_sent, tokens_filtered))
        conn.commit()
        conn.close()

    # ============================================================================
    # ПОЛУЧЕНИЕ ЛОГОВ ДЛЯ БОТА
    # ============================================================================

    def get_recent_connections(self, limit=20, user_id=None):
        """Получить последние подключения"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        if user_id:
            cursor.execute('''
                SELECT c.timestamp, c.action, u.username, c.ip_address
                FROM connection_logs c
                JOIN users u ON c.user_id = u.id
                WHERE c.user_id = ?
                ORDER BY c.timestamp DESC
                LIMIT ?
            ''', (user_id, limit))
        else:
            cursor.execute('''
                SELECT c.timestamp, c.action, u.username, c.ip_address
                FROM connection_logs c
                JOIN users u ON c.user_id = u.id
                ORDER BY c.timestamp DESC
                LIMIT ?
            ''', (limit,))

        rows = cursor.fetchall()
        conn.close()
        return [{"timestamp": r[0], "action": r[1], "username": r[2], "ip": r[3]} for r in rows]

    def get_recent_requests(self, limit=20, user_id=None):
        """Получить последние запросы"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        if user_id:
            cursor.execute('''
                SELECT r.timestamp, r.request_type, u.username, r.success
                FROM request_logs r
                JOIN users u ON r.user_id = u.id
                WHERE r.user_id = ?
                ORDER BY r.timestamp DESC
                LIMIT ?
            ''', (user_id, limit))
        else:
            cursor.execute('''
                SELECT r.timestamp, r.request_type, u.username, r.success
                FROM request_logs r
                JOIN users u ON r.user_id = u.id
                ORDER BY r.timestamp DESC
                LIMIT ?
            ''', (limit,))

        rows = cursor.fetchall()
        conn.close()
        return [{"timestamp": r[0], "type": r[1], "username": r[2], "success": bool(r[3])} for r in rows]

    def get_user_statistics(self, user_id):
        """Получить статистику пользователя"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Количество подключений
        cursor.execute('SELECT COUNT(*) FROM connection_logs WHERE user_id = ? AND action = "connected"', (user_id,))
        connections = cursor.fetchone()[0]

        # Количество запросов
        cursor.execute('SELECT COUNT(*) FROM request_logs WHERE user_id = ?', (user_id,))
        requests = cursor.fetchone()[0]

        # Количество полученных токенов
        cursor.execute('SELECT COUNT(*) FROM token_logs WHERE user_id = ? AND filtered = 0', (user_id,))
        tokens_received = cursor.fetchone()[0]

        # Количество отфильтрованных токенов
        cursor.execute('SELECT COUNT(*) FROM token_logs WHERE user_id = ? AND filtered = 1', (user_id,))
        tokens_filtered = cursor.fetchone()[0]

        conn.close()

        return {
            "connections": connections,
            "requests": requests,
            "tokens_received": tokens_received,
            "tokens_filtered": tokens_filtered
        }

    def get_server_statistics(self):
        """Получить общую статистику сервера"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Последняя запись статистики
        cursor.execute('SELECT * FROM server_stats ORDER BY timestamp DESC LIMIT 1')
        last_stat = cursor.fetchone()

        # Общее количество пользователей
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]

        # Активные пользователи
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1 AND datetime(expires_at) > datetime("now")')
        active_users = cursor.fetchone()[0]

        conn.close()

        result = {
            "total_users": total_users,
            "active_users": active_users
        }

        if last_stat:
            result.update({
                "last_update": last_stat[1],
                "active_connections": last_stat[2],
                "tokens_received": last_stat[3],
                "tokens_sent": last_stat[4],
                "tokens_filtered": last_stat[5]
            })

        return result

    # === ДОБАВЛЕНО: МЕТОД ОЧИСТКИ ЛОГОВ ===

    def cleanup_token_logs(self, days=30, user_id=None):
        """
        Удалить логи токенов старше N дней

        Args:
            days: Удалить логи старше этого количества дней
            user_id: Если указан - удалить только для конкретного пользователя

        Returns:
            dict: Количество удалённых записей
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        if user_id:
            # Удаляем для конкретного пользователя
            cursor.execute('''
                DELETE FROM token_logs 
                WHERE user_id = ? AND datetime(timestamp) < datetime('now', '-' || ? || ' days')
            ''', (user_id, days))
        else:
            # Удаляем для всех пользователей
            cursor.execute('''
                DELETE FROM token_logs 
                WHERE datetime(timestamp) < datetime('now', '-' || ? || ' days')
            ''', (days,))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return {"deleted": deleted}

    def cleanup_all_logs(self, days=30):
        """
        Удалить ВСЕ типы логов старше N дней

        Args:
            days: Удалить логи старше этого количества дней

        Returns:
            dict: Количество удалённых записей по типам
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Удаляем старые логи токенов
        cursor.execute('''
            DELETE FROM token_logs 
            WHERE datetime(timestamp) < datetime('now', '-' || ? || ' days')
        ''', (days,))
        deleted_tokens = cursor.rowcount

        # Удаляем старые логи подключений
        cursor.execute('''
            DELETE FROM connection_logs 
            WHERE datetime(timestamp) < datetime('now', '-' || ? || ' days')
        ''', (days,))
        deleted_connections = cursor.rowcount

        # Удаляем старые логи запросов
        cursor.execute('''
            DELETE FROM request_logs 
            WHERE datetime(timestamp) < datetime('now', '-' || ? || ' days')
        ''', (days,))
        deleted_requests = cursor.rowcount

        # Удаляем старую статистику сервера
        cursor.execute('''
            DELETE FROM server_stats 
            WHERE datetime(timestamp) < datetime('now', '-' || ? || ' days')
        ''', (days,))
        deleted_stats = cursor.rowcount

        conn.commit()
        conn.close()

        return {
            "tokens": deleted_tokens,
            "connections": deleted_connections,
            "requests": deleted_requests,
            "stats": deleted_stats,
            "total": deleted_tokens + deleted_connections + deleted_requests + deleted_stats
        }

    def get_logs_size(self):
        """
        Получить размер каждой таблицы логов

        Returns:
            dict: Количество записей в каждой таблице
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM token_logs')
        tokens_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM connection_logs')
        connections_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM request_logs')
        requests_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM server_stats')
        stats_count = cursor.fetchone()[0]

        conn.close()

        return {
            "token_logs": tokens_count,
            "connection_logs": connections_count,
            "request_logs": requests_count,
            "server_stats": stats_count,
            "total": tokens_count + connections_count + requests_count + stats_count
        }