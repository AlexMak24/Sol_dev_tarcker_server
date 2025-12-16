#!/usr/bin/env python3
# telegram_bot.py - Полная версия с принудительным подключением к основной БД сервера

import logging
import sys
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# ===================================================================
# ЖЁСТКО ЗАДАННЫЙ ПУТЬ К ОСНОВНОЙ БАЗЕ ДАННЫХ СЕРВЕРА
# ===================================================================
# ИЗМЕНИ ЭТУ СТРОКУ, ЕСЛИ ИМЯ ФАЙЛА БД ДРУГОЕ!
MAIN_DB_PATH = r"C:\Users\Alexander\PycharmProjects\SOLANA_DEV_TRACKER_FINAL\real_server\axiom_server.db"

# Проверка существования файла БД при запуске
if not os.path.exists(MAIN_DB_PATH):
    print(f"❌ ОШИБКА: Файл базы данных не найден!")
    print(f"Указанный путь: {MAIN_DB_PATH}")
    print("Проверь путь и имя файла БД.")
    sys.exit(1)

# Добавляем корневую папку проекта в sys.path для импорта database.py
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Импорт класса Database и конфига
try:
    from database import Database
except ImportError as e:
    print("❌ Файл database.py не найден в корне проекта!")
    print(f"Ошибка: {e}")
    sys.exit(1)

try:
    from . import bot_config  # Импорт из той же папки, где лежит telegram_bot.py
except ImportError as e:
    print("❌ Файл bot_config.py не найден в папке telegram_bot/")
    print(f"Ошибка: {e}")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO if bot_config.DEBUG else logging.WARNING
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(WAITING_USERNAME, WAITING_TG_USERNAME, WAITING_DAYS,
 WAITING_NEW_ACCOUNT_USERNAME) = range(4)


# ===================================================================
# Переопределённый класс Database с фиксированным путём к основной БД
# ===================================================================
class ServerDatabase(Database):
    """Наследуем оригинальный Database, но принудительно используем основной файл БД"""
    def __init__(self):
        import sqlite3
        self.db_file = MAIN_DB_PATH
        self.conn = sqlite3.connect(MAIN_DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        logger.info(f"✅ Подключено к основной БД сервера: {MAIN_DB_PATH}")


class AxiomBot:
    """Полный Telegram бот для Axiom Server"""

    def __init__(self):
        logger.info("🤖 Инициализация Axiom Bot...")

        # Используем наш класс с фиксированным путём к БД
        try:
            self.db = ServerDatabase()
            logger.info("✅ Основная база данных сервера успешно подключена")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к основной БД: {e}")
            raise

        # Создаём приложение Telegram
        self.app = Application.builder().token(bot_config.BOT_TOKEN).build()

        # Регистрация обработчиков
        self._register_handlers()

        logger.info("✅ Бот полностью инициализирован!")

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))

        # Добавление пользователя админом
        add_user_conv = ConversationHandler(
            entry_points=[CommandHandler("adduser", self.adduser_start)],
            states={
                WAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.adduser_get_username)],
                WAITING_TG_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.adduser_get_tg_username)],
                WAITING_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.adduser_get_days)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        self.app.add_handler(add_user_conv)

        # Создание аккаунта обычным пользователем
        create_account_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.create_account_start, pattern="^create_account$")],
            states={
                WAITING_NEW_ACCOUNT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.create_account_finish)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )
        self.app.add_handler(create_account_conv)

        # Команды админа
        self.app.add_handler(CommandHandler("deleteuser", self.deleteuser_command))
        self.app.add_handler(CommandHandler("listusers", self.listusers_command))
        self.app.add_handler(CommandHandler("userdetails", self.userdetails_command))
        self.app.add_handler(CommandHandler("activate", self.activate_command))
        self.app.add_handler(CommandHandler("deactivate", self.deactivate_command))
        self.app.add_handler(CommandHandler("extend", self.extend_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("logs", self.logs_command))
        self.app.add_handler(CommandHandler("cleanup", self.cleanup_command))

        # Управление админами
        self.app.add_handler(CommandHandler("admins", self.admins_command))
        self.app.add_handler(CommandHandler("addadmin", self.addadmin_command))
        self.app.add_handler(CommandHandler("removeadmin", self.removeadmin_command))

        # Кнопки
        self.app.add_handler(CallbackQueryHandler(self.button_handler))

        logger.info("✅ Все обработчики зарегистрированы")

    # ====================== ОСНОВНЫЕ КОМАНДЫ ======================

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        telegram_id = user.id
        telegram_username = f"@{user.username}" if user.username else None

        logger.info(f"👤 /start от {user.username or 'NoUsername'} (ID: {telegram_id})")

        if bot_config.is_super_admin(telegram_id):
            await self._show_admin_menu_without_db(update)
            return

        db_user = self.db.get_user_by_telegram_id(telegram_id)
        if db_user:
            await self._show_user_menu(update, db_user)
        else:
            await self._show_welcome(update, telegram_username)

    async def _show_admin_menu_without_db(self, update: Update):
        keyboard = [
            [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("📋 Логи", callback_data="admin_logs")],
            [InlineKeyboardButton("⚙️ Управление админами", callback_data="admin_admins")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = """
👑 <b>СУПЕР АДМИН ПАНЕЛЬ</b>

Вы вошли как супер администратор.
Доступны все функции управления.

<b>Команды:</b>
/adduser - Добавить пользователя
/deleteuser - Удалить
/listusers - Список всех
/userdetails - Детали
/activate - Активировать
/deactivate - Деактивировать
/extend - Продлить подписку

/stats - Статистика
/logs - Логи
/cleanup - Очистка БД

/admins - Управление админами
/addadmin - Добавить админа
/removeadmin - Убрать админа
"""
        await (update.message or update.callback_query.message).reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def _show_welcome(self, update: Update, telegram_username):
        keyboard = [
            [InlineKeyboardButton("🆕 Создать аккаунт (10 дней)", callback_data="create_account")],
            [InlineKeyboardButton("❓ Помощь", callback_data="help")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = """
👋 <b>Добро пожаловать в Axiom Token Tracker!</b>

Для начала работы создайте аккаунт.
Вы получите 10 дней бесплатного доступа.

После этого администратор может продлить подписку.
"""
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def _show_user_menu(self, update: Update, user: dict):
        telegram_id = update.effective_user.id
        is_admin = bot_config.is_admin(telegram_id) or user.get('is_admin', False)

        expires = datetime.fromisoformat(user['expires_at'])
        days_left = (expires - datetime.now()).days

        if days_left < 0:
            status_emoji = "❌"
            status_text = f"ИСТЕКЛА ({abs(days_left)} дней назад)"
        elif days_left <= 3:
            status_emoji = "⚠️"
            status_text = f"{days_left} дней осталось"
        else:
            status_emoji = "✅"
            status_text = f"{days_left} дней осталось"

        if is_admin:
            keyboard = [
                [InlineKeyboardButton("👑 Админ панель", callback_data="admin_panel")],
                [InlineKeyboardButton("🔑 Мой API ключ", callback_data="show_api")],
                [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
                [InlineKeyboardButton("ℹ️ Статус", callback_data="status")],
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("🔑 Мой API ключ", callback_data="show_api")],
                [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
                [InlineKeyboardButton("ℹ️ Статус", callback_data="status")],
                [InlineKeyboardButton("❓ Помощь", callback_data="help")],
            ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        role = "👑 АДМИН" if is_admin else "🟢 ПОЛЬЗОВАТЕЛЬ"

        text = f"""
<b>AXIOM TOKEN TRACKER</b>

{role}
👤 Username: <code>{user['username']}</code>
📅 Подписка: {status_emoji} {status_text}

Выберите действие:
"""
        msg = update.message or update.callback_query.message
        await msg.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        user = self.db.get_user_by_telegram_id(telegram_id)
        is_admin = bot_config.is_admin(telegram_id) or (user and user.get('is_admin'))

        help_text = "<b>📚 СПРАВКА</b>\n\n"
        if is_admin:
            help_text += """
<b>Команды админа:</b>
/adduser - Добавить пользователя
/deleteuser - Удалить пользователя  
/listusers - Список пользователей
/userdetails - Детали пользователя
/activate - Активировать
/deactivate - Деактивировать
/extend - Продлить подписку
/stats - Статистика сервера
/logs - Логи
/cleanup - Очистка БД
/admins - Управление админами
"""
        help_text += """
<b>Общие команды:</b>
/start - Главное меню
/help - Эта справка
"""
        await update.message.reply_text(help_text, parse_mode='HTML')

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ Операция отменена.")
        return ConversationHandler.END

    # ====================== КНОПКИ ======================

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        telegram_id = update.effective_user.id
        user = self.db.get_user_by_telegram_id(telegram_id)

        data = query.data
        if data == "show_api":
            await self._show_api_key(update, user)
        elif data == "my_stats":
            await self._show_my_stats(update, user)
        elif data == "status":
            await self._show_status(update, user)
        elif data == "admin_panel":
            await self._show_admin_panel(update)
        elif data == "help":
            await self._show_help(update)
        elif data == "back_to_menu":
            if user:
                await self._show_user_menu(update, user)

    async def _show_api_key(self, update: Update, user: dict):
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"""
🔑 <b>ВАШ API КЛЮЧ</b>

<code>{user['api_key']}</code>

Скопируйте ключ и используйте в приложении для подключения к серверу.

⚠️ Не передавайте ключ третьим лицам!
"""
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def _show_my_stats(self, update: Update, user: dict):
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        stats = self.db.get_user_statistics(user['id'])
        text = f"""
📊 <b>ВАША СТАТИСТИКА</b>

👤 Username: <code>{user['username']}</code>
📅 Зарегистрирован: {user['created_at'][:10]}

🎫 <b>Токены:</b>
   • Получено: {stats['tokens_received']}
   • Отфильтровано: {stats['tokens_filtered']}

🔌 <b>Подключения:</b>
   • Всего: {stats['connections']}

⚙️ <b>Запросы:</b>
   • Всего: {stats['requests']}
"""
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def _show_status(self, update: Update, user: dict):
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        expires = datetime.fromisoformat(user['expires_at'])
        days_left = (expires - datetime.now()).days

        status = "❌ ИСТЕКЛА" if days_left < 0 else ("⚠️ Истекает скоро" if days_left <= 3 else "✅ Активна")
        if days_left < 0:
            status += f" ({abs(days_left)} дней назад)"
        else:
            status += f" ({days_left} дней осталось)"

        active_status = "✅ Активен" if user['is_active'] else "❌ Деактивирован"

        text = f"""
ℹ️ <b>СТАТУС ПОДПИСКИ</b>

👤 Username: <code>{user['username']}</code>
🆔 Telegram: {user['telegram_username'] or 'N/A'}

📅 <b>Подписка:</b>
   • Создана: {user['created_at'][:10]}
   • Истекает: {user['expires_at'][:10]}
   • {status}

⚡ <b>Статус:</b>
   • {active_status}
"""
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def _show_admin_panel(self, update: Update):
        telegram_id = update.effective_user.id
        if not bot_config.is_admin(telegram_id):
            await update.callback_query.edit_message_text("❌ Доступно только администраторам")
            return

        keyboard = [
            [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("📋 Логи", callback_data="admin_logs")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = """
👑 <b>АДМИН ПАНЕЛЬ</b>

Выберите раздел или используйте команды:

<b>Управление:</b>
/adduser - Добавить пользователя
/deleteuser - Удалить  
/listusers - Список всех
/extend - Продлить подписку

<b>Просмотр:</b>
/stats - Статистика
/logs - Логи
/cleanup - Очистка БД
"""
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def _show_help(self, update: Update):
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = """
❓ <b>ПОМОЩЬ</b>

<b>Как начать работу:</b>
1. Создайте аккаунт через бота
2. Получите API ключ
3. Используйте ключ в приложении

<b>Если возникли проблемы:</b>
• Свяжитесь с администратором
• Проверьте статус подписки (/start)

<b>Команды:</b>
/start - Главное меню
/help - Справка
"""
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    # ====================== СОЗДАНИЕ АККАУНТА ======================

    async def create_account_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text(
            "📝 <b>Создание аккаунта</b>\n\n"
            "Введите желаемый username (латинские буквы, цифры, подчёркивание):\n\n"
            "Для отмены: /cancel",
            parse_mode='HTML'
        )
        return WAITING_NEW_ACCOUNT_USERNAME

    async def create_account_finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        username = update.message.text.strip()
        telegram_id = update.effective_user.id
        telegram_username = f"@{update.effective_user.username}" if update.effective_user.username else None

        if not username.replace('_', '').isalnum():
            await update.message.reply_text("❌ Только латинские буквы, цифры и _\nПопробуйте снова:")
            return WAITING_NEW_ACCOUNT_USERNAME

        api_key = self.db.add_user(
            username=username,
            telegram_username=telegram_username,
            subscription_days=10,
            telegram_id=telegram_id,
            is_admin=False
        )

        if api_key:
            expires = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
            keyboard = [
                [InlineKeyboardButton("🔑 Мой API ключ", callback_data="show_api")],
                [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"✅ <b>Аккаунт создан!</b>\n\n"
                f"👤 Username: <code>{username}</code>\n"
                f"📅 Подписка до: {expires} (10 дней)\n"
                f"🔑 Ваш API ключ:\n<code>{api_key}</code>\n\n"
                f"Скопируйте и вставьте в приложение.",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ Такой username уже занят.\nВведите другой:")
            return WAITING_NEW_ACCOUNT_USERNAME

        return ConversationHandler.END

    # ====================== КОМАНДЫ АДМИНА ======================

    async def adduser_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только для администраторов")
            return ConversationHandler.END
        await update.message.reply_text("➕ Введите username нового пользователя:\n/cancel — отмена", parse_mode='HTML')
        return WAITING_USERNAME

    async def adduser_get_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['new_username'] = update.message.text.strip()
        await update.message.reply_text("Введите Telegram username (@username) или '-' для пропуска:")
        return WAITING_TG_USERNAME

    async def adduser_get_tg_username(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg = update.message.text.strip()
        context.user_data['telegram_username'] = tg if tg != '-' else None
        await update.message.reply_text("Сколько дней подписки? (по умолчанию 30):")
        return WAITING_DAYS

    async def adduser_get_days(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            days = int(update.message.text.strip())
        except:
            days = 30

        username = context.user_data['new_username']
        tg_username = context.user_data.get('telegram_username')

        api_key = self.db.add_user(
            username=username,
            telegram_username=tg_username,
            subscription_days=days,
            is_admin=False
        )

        if api_key:
            expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            await update.message.reply_text(
                f"✅ Пользователь создан!\n\n"
                f"👤 Username: <code>{username}</code>\n"
                f"🆔 TG: {tg_username or 'N/A'}\n"
                f"📅 До: {expires} ({days} дней)\n"
                f"🔑 Ключ: <code>{api_key}</code>",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("❌ Пользователь с таким username уже существует!")
        return ConversationHandler.END

    async def deleteuser_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return
        if not context.args:
            await update.message.reply_text("Использование: /deleteuser USER_ID")
            return
        try:
            user_id = int(context.args[0])
            self.db.delete_user(user_id)
            await update.message.reply_text(f"✅ Пользователь ID {user_id} удалён")
        except:
            await update.message.reply_text("❌ Неверный ID")

    async def listusers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return

        users = self.db.get_all_users()
        if not users:
            await update.message.reply_text("Нет пользователей")
            return

        text = "👥 <b>СПИСОК ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
        now = datetime.now()
        for u in users[:20]:
            expires = datetime.fromisoformat(u['expires_at'])
            days_left = (expires - now).days
            status = "✅" if days_left >= 0 else "❌"
            active = "🟢" if u['is_active'] else "🔴"
            admin = "👑" if u['is_admin'] else ""
            text += f"{status} {active} {admin} <code>{u['username']}</code> (ID: {u['id']})\n"
            text += f"   📅 {days_left}d | 🆔 {u['telegram_username'] or 'N/A'}\n\n"

        if len(users) > 20:
            text += f"... и ещё {len(users) - 20}\n\n"
        text += f"<b>Всего:</b> {len(users)}"

        await update.message.reply_text(text, parse_mode='HTML')

    # Остальные команды админа (userdetails, activate, deactivate, extend, stats, logs, cleanup, admins, addadmin, removeadmin)
    # — оставлены без изменений, как у тебя в оригинале (они полностью рабочие)

    async def userdetails_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return
        if not context.args:
            await update.message.reply_text("Использование: /userdetails USERNAME")
            return
        user = self.db.get_user_by_username(context.args[0])
        if not user:
            await update.message.reply_text("❌ Пользователь не найден")
            return

        expires = datetime.fromisoformat(user['expires_at'])
        days_left = (expires - datetime.now()).days
        status = "✅ Активна" if days_left >= 0 else "❌ Истекла"
        active = "✅ Да" if user['is_active'] else "❌ Нет"
        admin = "👑 Да" if user['is_admin'] else "Нет"

        text = f"""
<b>ПОЛЬЗОВАТЕЛЬ: {user['username']}</b>

🆔 ID: {user['id']}
👤 Username: <code>{user['username']}</code>
🆔 Telegram: {user['telegram_username'] or 'N/A'}
📱 TG ID: {user['telegram_id'] or 'Не привязан'}
👑 Админ: {admin}

🔑 API Key: <code>{user['api_key']}</code>

📅 Создан: {user['created_at'][:10]}
📅 Истекает: {user['expires_at'][:10]}
⏳ Осталось: {days_left} дней
📊 Статус: {status}
⚡ Активен: {active}
"""
        await update.message.reply_text(text, parse_mode='HTML')

    async def activate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return
        if not context.args:
            await update.message.reply_text("Использование: /activate USERNAME")
            return
        user = self.db.get_user_by_username(context.args[0])
        if user:
            self.db.update_user_status(user['id'], 1)
            await update.message.reply_text(f"✅ {context.args[0]} активирован")
        else:
            await update.message.reply_text("❌ Не найден")

    async def deactivate_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return
        if not context.args:
            await update.message.reply_text("Использование: /deactivate USERNAME")
            return
        user = self.db.get_user_by_username(context.args[0])
        if user:
            self.db.update_user_status(user['id'], 0)
            await update.message.reply_text(f"✅ {context.args[0]} деактивирован")
        else:
            await update.message.reply_text("❌ Не найден")

    async def extend_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return
        if len(context.args) < 2:
            await update.message.reply_text("Использование: /extend USERNAME DAYS")
            return
        username, days_str = context.args[0], context.args[1]
        try:
            days = int(days_str)
        except:
            await update.message.reply_text("❌ Неверное число дней")
            return
        user = self.db.get_user_by_username(username)
        if user:
            self.db.extend_subscription(user['id'], days)
            new_date = (datetime.fromisoformat(user['expires_at']) + timedelta(days=days)).strftime("%Y-%m-%d")
            await update.message.reply_text(f"✅ Подписка {username} продлена на {days} дней\nНовая дата: {new_date}")
        else:
            await update.message.reply_text("❌ Пользователь не найден")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return
        stats = self.db.get_server_statistics()
        text = f"""
📊 <b>СТАТИСТИКА СЕРВЕРА</b>

👥 Пользователей: {stats['total_users']} (активных: {stats['active_users']})

📡 Сервер:
"""
        if 'last_update' in stats:
            text += f"   • Онлайн: {stats['active_connections']}\n"
            text += f"   • Токенов получено: {stats['tokens_received']}\n"
            text += f"   • Отправлено: {stats['tokens_sent']}\n"
            text += f"   • Отфильтровано: {stats['tokens_filtered']}\n"
            text += f"   • Обновлено: {stats['last_update'][:16]}\n"
        else:
            text += "   • Нет данных"
        await update.message.reply_text(text, parse_mode='HTML')

    async def logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только админы")
            return
        await update.message.reply_text("📋 Доступные команды логов:\n/logs connections\n/logs tokens\n/logs user USERNAME", parse_mode='HTML')

    async def cleanup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_super_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только супер-админ")
            return
        if not context.args:
            size = self.db.get_logs_size()
            await update.message.reply_text(
                f"🗄️ Размер БД:\nToken logs: {size['token_logs']:,}\n"
                f"Connections: {size['connection_logs']:,}\n"
                f"Requests: {size['request_logs']:,}\n"
                f"Stats: {size['server_stats']:,}\n"
                f"<b>Всего:</b> {size['total']:,}\n\n"
                f"Для очистки: /cleanup 30",
                parse_mode='HTML'
            )
            return
        try:
            days = int(context.args[0])
            result = self.db.cleanup_all_logs(days)
            await update.message.reply_text(
                f"✅ Очистка завершена (старше {days} дней):\n"
                f"Токены: {result['tokens']}\nПодключения: {result['connections']}\n"
                f"Запросы: {result['requests']}\nСтатистика: {result['stats']}\n"
                f"<b>Всего:</b> {result['total']}",
                parse_mode='HTML'
            )
        except:
            await update.message.reply_text("❌ Неверное число дней")

    async def admins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_super_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только супер-админ")
            return
        admins = bot_config.get_all_admins()
        text = "👑 <b>АДМИНИСТРАТОРЫ</b>\n\n"
        for i, a in enumerate(admins, 1):
            role = "👑 Супер" if a['is_super'] else "Админ"
            text += f"{i}. {role} — <code>{a['telegram_id']}</code>\n\n"
        text += f"<b>Всего:</b> {len(admins)}"
        await update.message.reply_text(text, parse_mode='HTML')

    async def addadmin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_super_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только супер-админ")
            return
        if not context.args:
            await update.message.reply_text("Использование: /addadmin TELEGRAM_ID")
            return
        try:
            tid = int(context.args[0])
            if bot_config.add_admin(tid):
                await update.message.reply_text(f"✅ Админ добавлен: <code>{tid}</code>", parse_mode='HTML')
            else:
                await update.message.reply_text("⚠️ Уже админ")
        except:
            await update.message.reply_text("❌ Неверный ID")

    async def removeadmin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not bot_config.is_super_admin(update.effective_user.id):
            await update.message.reply_text("❌ Только супер-админ")
            return
        if not context.args:
            await update.message.reply_text("Использование: /removeadmin TELEGRAM_ID")
            return
        try:
            tid = int(context.args[0])
            if bot_config.remove_admin(tid):
                await update.message.reply_text("✅ Админ удалён")
            else:
                await update.message.reply_text("❌ Не админ или это супер-админ")
        except:
            await update.message.reply_text("❌ Неверный ID")

    # ====================== ЗАПУСК ======================

    def run(self):
        logger.info("=" * 70)
        logger.info("🚀 ЗАПУСК AXIOM TELEGRAM BOT")
        logger.info("✅ Подключение к основной БД сервера:")
        logger.info(f"   {self.db.db_file}")
        logger.info(f"👑 Супер-админ: {bot_config.SUPER_ADMIN_ID}")
        logger.info("=" * 70)

        try:
            self.app.run_polling(allowed_updates=Update.ALL_TYPES)
        except KeyboardInterrupt:
            logger.info("Бот остановлен вручную")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            raise


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║              AXIOM TELEGRAM BOT — FULL VERSION               ║
║       Подключён к основной БД: real_server/axiom_server.db   ║
╚══════════════════════════════════════════════════════════════╝
    """)
    bot = AxiomBot()
    bot.run()