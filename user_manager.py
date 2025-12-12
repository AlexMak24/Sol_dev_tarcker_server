# user_manager.py - ОБНОВЛЁННАЯ ВЕРСИЯ С use_and_mode
import json

PROTOCOL_MAPPING = {
    'pump v1': 'pump v1',
    'meteora amm v2': 'meteora amm v2',
    'orca': 'orca',
    'virtual curve': 'virtual curve',
    'raydium cpmm': 'raydium cpmm',
    'launchlab': 'launchlab',
    'meteora dlmm': 'meteora dlmm',
    'sugar': 'sugar',
    'pump amm': 'pump amm',
    'raydium clmm': 'raydium clmm',
    'moonshot': 'moonshot',
    'other': 'other'
}


class UserManager:
    def __init__(self, db, user_id: int):
        self.db = db
        self.user_id = user_id
        self.settings = self.db.get_user_settings(user_id)

    def update_settings(self, params: dict):
        self.db.update_user_settings(self.user_id, **params)
        self.settings = self.db.get_user_settings(self.user_id)

    def add_to_whitelist(self, dev_wallet: str, token_name: str = None, token_ticker: str = None):
        added = self.db.add_to_whitelist(self.user_id, dev_wallet, token_name, token_ticker)
        return added

    def add_to_blacklist(self, dev_wallet: str, token_name: str = None, token_ticker: str = None):
        added = self.db.add_to_blacklist(self.user_id, dev_wallet, token_name, token_ticker)
        return added

    def remove_from_whitelist(self, dev_wallet: str):
        return self.db.remove_from_whitelist(self.user_id, dev_wallet)

    def remove_from_blacklist(self, dev_wallet: str):
        return self.db.remove_from_blacklist(self.user_id, dev_wallet)

    def get_whitelist(self):
        return self.db.get_user_whitelist(self.user_id)

    def get_blacklist(self):
        return self.db.get_user_blacklist(self.user_id)

    def is_blacklisted(self, dev_wallet: str) -> bool:
        return self.db.is_dev_blacklisted(self.user_id, dev_wallet)

    def is_whitelisted(self, dev_wallet: str) -> bool:
        return self.db.is_dev_whitelisted(self.user_id, dev_wallet)

    def filter_token(self, token: dict) -> bool:
        """
        Фильтрация токена с поддержкой use_and_mode.

        use_and_mode = False (OR): хотя бы один включённый фильтр должен пройти
        use_and_mode = True (AND): все включённые фильтры должны пройти
        """
        s = self.settings

        # Blacklist — всегда приоритет (не зависит от use_and_mode)
        deployer = token.get("deployer_address", "")
        if self.is_blacklisted(deployer):
            return False

        # Собираем результаты проверок ТОЛЬКО для включённых фильтров
        checks = []

        # Avg MCAP
        if s.get("enable_avg_mcap", False):
            checks.append(token.get("avg_mcap", 0) >= s.get("min_avg_mcap", 0))

        # Avg ATH MCAP
        if s.get("enable_avg_ath_mcap", False):
            checks.append(token.get("avg_ath_mcap", 0) >= s.get("min_avg_ath_mcap", 0))

        # Migration %
        if s.get("enable_migrations", False):
            checks.append(token.get("migration_percent", 0) >= s.get("min_migration_percent", 0))

        # Protocol filter
        if s.get("enable_protocol_filter", False):
            raw = token.get("protocol", "unknown")
            protocol = raw.lower() if isinstance(raw, str) else "unknown"
            allowed = s.get("protocols", {})

            matched = any(internal in protocol for internal in PROTOCOL_MAPPING.values())
            if matched:
                # Проверяем что протокол разрешён
                protocol_passes = any(
                    internal in protocol and allowed.get(internal, True)
                    for internal in PROTOCOL_MAPPING.values()
                )
                checks.append(protocol_passes)
            else:
                # "other" протокол
                checks.append(allowed.get("other", True))

        # Twitter User
        if s.get("enable_twitter_user", False):
            stats = token.get("twitter_stats", {})
            checks.append(stats.get("followers", 0) >= s.get("min_twitter_followers", 0))

        # Twitter Community
        if s.get("enable_twitter_community", False):
            stats = token.get("twitter_stats", {})
            members = stats.get("community_followers", 0)
            admin = stats.get("admin_followers", 0)
            # Для community оба условия должны выполняться
            checks.append(
                members >= s.get("min_community_members", 0) and
                admin >= s.get("min_admin_followers", 0)
            )

        # Если НЕТ включённых фильтров → токен проходит
        if not checks:
            return True

        # Применяем логику use_and_mode
        use_and_mode = s.get("use_and_mode", False)

        if use_and_mode:
            # AND режим: ВСЕ включённые фильтры должны пройти
            return all(checks)
        else:
            # OR режим: ХОТЯ БЫ ОДИН включённый фильтр должен пройти
            return any(checks)