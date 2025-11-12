#!/usr/bin/env python3
"""
Telegram бот для мониторинга событий из Apple Calendar (iCloud)
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from enum import Enum

import caldav
from caldav import DAVClient
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from ics import Calendar, Event as ICSEvent

from database import Database, User

# Загружаем переменные окружения (только для настроек БД и токена бота)
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
class ConversationState(Enum):
    ASK_CALENDAR = 1
    WAIT_USERNAME = 2
    WAIT_PASSWORD = 3
    WAIT_URL = 4


class CalendarService:
    """Сервис для работы с календарем"""
    
    @staticmethod
    def connect_to_calendar(icloud_url: str, icloud_username: str, icloud_password: str):
        """Подключается к iCloud календарю"""
        try:
            logger.info(f"Подключение к iCloud календарю для {icloud_username}...")
            client = DAVClient(
                url=icloud_url,
                username=icloud_username,
                password=icloud_password
            )
            
            principal = client.principal()
            calendars = principal.calendars()
            
            if not calendars:
                raise ValueError("Не найдено календарей в аккаунте")
            
            # Используем первый доступный календарь
            calendar = calendars[0]
            logger.info(f"Успешно подключено к календарю: {calendar.name}")
            return client, calendar
            
        except Exception as e:
            logger.error(f"Ошибка при подключении к календарю: {e}")
            raise
    
    @staticmethod
    def get_events(calendar, days_ahead: int = 7) -> List[ICSEvent]:
        """Получает события из календаря на указанное количество дней вперед"""
        try:
            now = datetime.now()
            end_date = now + timedelta(days=days_ahead)
            
            # Получаем события из календаря
            events = calendar.search(
                start=now,
                end=end_date,
                event=True
            )
            
            parsed_events = []
            for event in events:
                try:
                    # Парсим событие из iCalendar формата
                    ics_data = event.data
                    calendar_obj = Calendar(ics_data)
                    for ics_event in calendar_obj.events:
                        parsed_events.append(ics_event)
                except Exception as e:
                    logger.warning(f"Ошибка при парсинге события: {e}")
                    continue
            
            # Сортируем по времени начала
            parsed_events.sort(key=lambda x: x.begin.datetime)
            logger.info(f"Найдено {len(parsed_events)} событий на ближайшие {days_ahead} дней")
            
            return parsed_events
            
        except Exception as e:
            logger.error(f"Ошибка при получении событий: {e}")
            return []
    
    @staticmethod
    def format_event_message(event: ICSEvent) -> str:
        """Форматирует событие для отправки в Telegram"""
        lines = ["📅 Новое событие в календаре:", ""]
        
        # Название
        if event.name:
            lines.append(f"Название: {event.name}")
        
        # Дата и время
        start_time = event.begin.datetime
        if event.duration:
            end_time = start_time + event.duration
            time_str = f"{start_time.strftime('%d %B, %H:%M')}–{end_time.strftime('%H:%M')}"
        else:
            time_str = start_time.strftime('%d %B, %H:%M')
        
        # Форматируем месяц на русском
        months_ru = {
            'January': 'января', 'February': 'февраля', 'March': 'марта',
            'April': 'апреля', 'May': 'мая', 'June': 'июня',
            'July': 'июля', 'August': 'августа', 'September': 'сентября',
            'October': 'октября', 'November': 'ноября', 'December': 'декабря'
        }
        for en, ru in months_ru.items():
            time_str = time_str.replace(en, ru)
        
        lines.append(f"Когда: {time_str}")
        
        # Место
        if event.location:
            lines.append(f"Место: {event.location}")
        
        # Описание
        if event.description:
            lines.append(f"Описание: {event.description}")
        
        return "\n".join(lines)
    
    @staticmethod
    def get_event_id(event: ICSEvent) -> str:
        """Генерирует уникальный ID для события"""
        if event.uid:
            return event.uid
        return f"{event.name}_{event.begin.isoformat()}"


# Глобальные объекты
db = Database()
telegram_token = os.getenv('TELEGRAM_TOKEN')

if not telegram_token:
    raise ValueError("TELEGRAM_TOKEN должен быть указан в .env файле")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    chat_id = update.effective_chat.id
    
    # Проверяем, есть ли у пользователя уже настроенный календарь
    user = db.get_user(chat_id)
    
    if user and user.icloud_username and user.icloud_password:
        # У пользователя уже есть настройки
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить данные", callback_data="update_data")],
            [InlineKeyboardButton("📅 Ближайшие события", callback_data="next_events")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Привет! Ваш календарь уже настроен.\n\n"
            f"Apple ID: {user.icloud_username}\n\n"
            f"Что вы хотите сделать?",
            reply_markup=reply_markup
        )
        # Не начинаем conversation, просто показываем меню
        return ConversationHandler.END
    
    # Новый пользователь или без настроек
    keyboard = [
        [InlineKeyboardButton("✅ Да", callback_data="yes_calendar")],
        [InlineKeyboardButton("❌ Нет", callback_data="no_calendar")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Привет! Я бот для мониторинга событий из Apple Calendar.\n\n"
        "Хотите ли Вы получать события из своего календаря в этом чате?",
        reply_markup=reply_markup
    )
    return ConversationState.ASK_CALENDAR


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    chat_id = query.from_user.id
    
    if query.data == "yes_calendar":
        # Показываем инструкцию
        instruction_text = (
            "Отлично! Для подключения к вашему календарю нам понадобятся следующие данные:\n\n"
            "📋 Инструкция по получению App-Specific Password:\n\n"
            "1. Перейдите на https://appleid.apple.com\n"
            "2. Войдите в свой аккаунт Apple ID\n"
            "3. В разделе 'Безопасность' найдите 'Пароли приложений'\n"
            "4. Создайте новый пароль приложения для 'Другое' или 'Почта'\n"
            "5. Скопируйте сгенерированный пароль (16 символов без пробелов)\n\n"
            "⚠️ Важно: Используйте именно App-Specific Password, а не обычный пароль!\n\n"
            "Готовы предоставить данные? Нажмите кнопку ниже."
        )
        
        keyboard = [
            [InlineKeyboardButton("📝 Предоставить данные", callback_data="provide_data")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(instruction_text, reply_markup=reply_markup)
        return ConversationState.WAIT_USERNAME
    
    elif query.data == "no_calendar":
        await query.edit_message_text(
            "Хорошо, если передумаете - просто отправьте команду /start снова."
        )
        return ConversationHandler.END
    
    elif query.data == "update_data":
        instruction_text = (
            "Давайте обновим ваши данные.\n\n"
            "Пожалуйста, отправьте ваш Apple ID (email):"
        )
        await query.edit_message_text(instruction_text)
        return ConversationState.WAIT_USERNAME
    
    elif query.data == "provide_data":
        await query.edit_message_text(
            "Отлично! Начнем настройку.\n\n"
            "Пожалуйста, отправьте ваш Apple ID (email):"
        )
        return ConversationState.WAIT_USERNAME
    
    return ConversationHandler.END


async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает Apple ID от пользователя"""
    username = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    # Сохраняем username во временное хранилище
    context.user_data['icloud_username'] = username
    
    await update.message.reply_text(
        f"Отлично! Apple ID: {username}\n\n"
        "Теперь отправьте App-Specific Password (16 символов без пробелов):"
    )
    return ConversationState.WAIT_PASSWORD


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает пароль от пользователя"""
    password = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    # Сохраняем password во временное хранилище
    context.user_data['icloud_password'] = password
    username = context.user_data.get('icloud_username')
    
    # Пытаемся подключиться к календарю для проверки
    try:
        client, calendar = CalendarService.connect_to_calendar(
            'https://caldav.icloud.com/',
            username,
            password
        )
        
        # Если подключение успешно, сохраняем данные
        db.update_user_credentials(
            chat_id=chat_id,
            icloud_username=username,
            icloud_password=password,
            icloud_url='https://caldav.icloud.com/'
        )
        
        await update.message.reply_text(
            "✅ Отлично! Данные успешно сохранены и календарь подключен.\n\n"
            "Теперь я буду автоматически проверять ваш календарь и отправлять уведомления о новых событиях.\n\n"
            "Доступные команды:\n"
            "/next - показать ближайшие 3 события\n"
            "/start - обновить настройки"
        )
        
        # Очищаем временные данные
        context.user_data.clear()
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка при подключении к календарю: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при подключении к календарю: {str(e)}\n\n"
            "Проверьте правильность Apple ID и App-Specific Password.\n"
            "Попробуйте отправить Apple ID снова:"
        )
        return ConversationState.WAIT_USERNAME


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущую операцию"""
    await update.message.reply_text(
        "Операция отменена. Используйте /start для начала."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def get_next_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает ближайшие 3 события для пользователя"""
    chat_id = update.effective_chat.id
    user = db.get_user(chat_id)
    
    if not user or not user.icloud_username or not user.icloud_password:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "❌ Календарь не настроен. Используйте /start для настройки."
            )
        else:
            await update.message.reply_text(
                "❌ Календарь не настроен. Используйте /start для настройки."
            )
        return
    
    try:
        # Подключаемся к календарю
        client, calendar = CalendarService.connect_to_calendar(
            user.icloud_url,
            user.icloud_username,
            user.icloud_password
        )
        
        # Получаем события
        events = CalendarService.get_events(calendar, days_ahead=30)
        
        if not events:
            message = "Событий не найдено."
        else:
            # Берем ближайшие 3 события
            upcoming_events = [e for e in events if e.begin.datetime > datetime.now()][:3]
            
            if not upcoming_events:
                message = "Ближайших событий не найдено."
            else:
                messages = []
                for event in upcoming_events:
                    messages.append(CalendarService.format_event_message(event))
                message = "\n\n".join(messages)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
            
    except Exception as e:
        logger.error(f"Ошибка при получении событий: {e}")
        error_msg = f"Произошла ошибка: {str(e)}"
        if update.callback_query:
            await update.callback_query.edit_message_text(error_msg)
        else:
            await update.message.reply_text(error_msg)


async def next_events_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Ближайшие события'"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Получаю события из календаря...")
    await get_next_events(update, context)


async def check_events_for_user(user: User, application: Application):
    """Проверяет события для конкретного пользователя"""
    try:
        # Подключаемся к календарю
        client, calendar = CalendarService.connect_to_calendar(
            user.icloud_url,
            user.icloud_username,
            user.icloud_password
        )
        
        # Получаем события
        events = CalendarService.get_events(calendar, days_ahead=7)
        
        # Фильтруем только новые события
        new_events = []
        for event in events:
            event_id = CalendarService.get_event_id(event)
            
            # Проверяем, было ли событие уже отправлено
            if not db.is_event_sent(user.id, event_id):
                # Проверяем, что событие еще не началось или началось недавно
                start_time = event.begin.datetime
                time_diff = start_time - datetime.now()
                if time_diff.total_seconds() > -3600:  # Не старше часа
                    new_events.append(event)
        
        # Отправляем новые события
        for event in new_events:
            message = CalendarService.format_event_message(event)
            await application.bot.send_message(
                chat_id=user.chat_id,
                text=message
            )
            
            # Отмечаем событие как отправленное
            event_id = CalendarService.get_event_id(event)
            db.mark_event_as_sent(user.id, event_id)
        
        if new_events:
            logger.info(f"Отправлено {len(new_events)} новых событий пользователю {user.chat_id}")
            
    except Exception as e:
        logger.error(f"Ошибка при проверке событий для пользователя {user.chat_id}: {e}")


async def check_events_job(context: ContextTypes.DEFAULT_TYPE):
    """Задача для периодической проверки событий для всех пользователей"""
    logger.info("Запуск периодической проверки событий...")
    
    # Получаем всех активных пользователей
    users = db.get_active_users()
    
    if not users:
        logger.debug("Нет активных пользователей для проверки")
        return
    
    # Проверяем события для каждого пользователя
    for user in users:
        await check_events_for_user(user, context.application)


def main():
    """Основная функция запуска бота"""
    try:
        if not telegram_token:
            raise ValueError("TELEGRAM_TOKEN должен быть указан в .env файле")
        
        # Создаем приложение Telegram
        application = Application.builder().token(telegram_token).build()
        
        # Создаем ConversationHandler для настройки календаря
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", start),
                CallbackQueryHandler(button_callback, pattern="^(yes_calendar|no_calendar|update_data|provide_data)$")
            ],
            states={
                ConversationState.ASK_CALENDAR: [
                    CallbackQueryHandler(button_callback, pattern="^(yes_calendar|no_calendar|update_data|provide_data)$")
                ],
                ConversationState.WAIT_USERNAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)
                ],
                ConversationState.WAIT_PASSWORD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
        
        # Регистрируем обработчики (важен порядок - команды до conversation)
        application.add_handler(CommandHandler("next", get_next_events))
        application.add_handler(CallbackQueryHandler(next_events_callback, pattern="^next_events$"))
        application.add_handler(conv_handler)
        
        # Настраиваем планировщик для периодической проверки
        check_interval = int(os.getenv('CHECK_INTERVAL_MINUTES', '60'))
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            check_events_job,
            trigger=IntervalTrigger(minutes=check_interval),
            args=[application],
            id='check_events',
            replace_existing=True
        )
        
        # Запускаем планировщик
        scheduler.start()
        logger.info(f"Планировщик запущен. Проверка каждые {check_interval} минут.")
        
        # Запускаем бота
        logger.info("Бот запущен и готов к работе!")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise


if __name__ == '__main__':
    main()
