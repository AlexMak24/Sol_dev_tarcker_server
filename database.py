# database.py - РАСШИРЕННАЯ ВЕРСИЯ С WHITELIST/BLACKLIST И ПОЛНЫМИ НАСТРОЙКАМИ + use_and_mode
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

        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                api_key TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        ''')

        # Расширенная таблица настроек (добавлены новые поля + use_and_mode)
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

        # НОВАЯ: Whitelist деплоеров для пользователя
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

        # НОВАЯ: Blacklist деплоеров для пользователя
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

        conn.commit()
        conn.close()
        print("[DB] Инициализация завершена: добавлены whitelist/blacklist и расширенные настройки + use_and_mode")

    def generate_api_key(self):
        return secrets.token_urlsafe(32)

    def add_user(self, username, email=None, subscription_days=30):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        api_key = self.generate_api_key()
        created_at = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(days=subscription_days)).isoformat()
        try:
            cursor.execute('''
                INSERT INTO users (username, email, api_key, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, email, api_key, created_at, expires_at))
            user_id = cursor.lastrowid

            # Создаём пустую запись настроек
            cursor.execute('INSERT INTO user_options (user_id) VALUES (?)', (user_id,))
            conn.commit()
            print(f"[DB] Пользователь добавлен: {username} (ID: {user_id})")
            return api_key
        except sqlite3.IntegrityError as e:
            print(f"[DB] Ошибка добавления пользователя: {e}")
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
                'email': user[2],
                'api_key': user[3],
                'created_at': user[4],
                'expires_at': user[5],
                'is_active': user[6]
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
            'email': u[2],
            'api_key': u[3],
            'created_at': u[4],
            'expires_at': u[5],
            'is_active': u[6]
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

    # === РАСШИРЕННЫЕ НАСТРОЙКИ ===
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
            'use_and_mode': bool(row[16]) if len(row) > 16 else False  # ← ДОБАВЛЕНО
        }

    def update_user_settings(self, user_id, **kwargs):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Проверяем существование записи
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
            'use_and_mode'  # ← ДОБАВЛЕНО
        ]

        for key, value in kwargs.items():
            if key not in allowed_keys:
                continue

            if key == 'protocols':
                # Сохраняем как JSON строку
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
            print(f"[DB] Обновлены настройки для user_id={user_id}: {kwargs}")

        conn.close()

    # === WHITELIST / BLACKLIST МЕТОДЫ ===
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
        cursor.execute('SELECT dev_wallet, token_name, token_ticker, added_at FROM user_whitelist WHERE user_id = ? ORDER BY added_at DESC', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [{"dev_wallet": r[0], "name": r[1], "ticker": r[2], "added": r[3]} for r in rows]

    def get_user_blacklist(self, user_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('SELECT dev_wallet, token_name, token_ticker, added_at FROM user_blacklist WHERE user_id = ? ORDER BY added_at DESC', (user_id,))
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

    def delete_user(self, user_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_options WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_whitelist WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_blacklist WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()