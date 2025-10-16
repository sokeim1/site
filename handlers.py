from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaVideo, InputMediaDocument, BufferedInputFile, LabeledPrice, PreCheckoutQuery, WebAppInfo
from aiogram import Router, Bot
from aiogram.exceptions import TelegramBadRequest
from db import save_user
import time
import asyncio
import datetime
from datetime import timezone, timedelta

# Кэш для оптимизации сохранения пользователей
user_save_cache = {}

def optimized_save_user(user_id, username, first_name, last_name, language_code, is_bot):
    """Сохраняет пользователя только раз в 5 минут для ускорения работы"""
    current_time = time.time()
    
    # Проверяем последнее сохранение
    if user_id in user_save_cache:
        if current_time - user_save_cache[user_id] < 300:  # 5 минут
            return
    
    try:
        save_user(user_id, username, first_name, last_name, language_code, is_bot)
        user_save_cache[user_id] = current_time
    except Exception:
        pass

async def safe_send_message(callback: CallbackQuery, text: str, reply_markup=None, parse_mode="HTML"):
    """Безопасная отправка сообщения через callback"""
    if callback.message and callback.message.chat:
        await bot.send_message(
            callback.message.chat.id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    else:
        await callback.answer("Ошибка: сообщение недоступно", show_alert=True)

from config import API_TOKEN, BOT_USERNAME, ADMIN_IDS, CHANNEL_ID, CHANNEL_USERNAME, MINIAPP_BASE_URL, DAILY_CONTENT_LIMIT
from storage import MOVIES, SERIES_POSTERS
from db import save_user, add_referral, get_referrals_count, get_premium_users, is_premium_user, load_all_users, activate_premium, get_episode_qualities, add_episode_quality, episode_exists, get_episode_quality_file_id, get_user_stats, get_user_daily_content_count
from miniapp_security import generate_secure_miniapp_url, validate_miniapp_signature, get_user_limits_info
from keyboards import (get_seasons_keyboard, get_episodes_keyboard, get_back_to_episodes_keyboard, 
                      get_episode_share_keyboard, get_main_menu_keyboard, get_back_to_main_menu_keyboard, 
                      get_movies_menu_keyboard, get_phf_seasons_keyboard, get_lbsc_seasons_keyboard, 
                      get_lbsc_episodes_keyboard, get_irh_seasons_keyboard, get_irh_episodes_keyboard, 
                      get_wnd_seasons_keyboard, get_wnd_episodes_keyboard, get_loki_seasons_keyboard, 
                      get_loki_episodes_keyboard, get_broadcast_menu_keyboard, get_broadcast_confirm_keyboard,
                      get_broadcast_buttons_keyboard, get_broadcast_custom_button_keyboard)
import json
import os
import random
import logging
import datetime
import re
import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("bot_actions.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

STATS_FILE = 'stats.json'
# ADMIN_ID берём из config.py (или ENV ADMIN_ID)

# Глобальная переменная для хранения пользователей, ожидающих название плейлиста
waiting_for_playlist_name = set()

# Временное хранилище для выбора серий при создании плейлиста
# user_id: { 'name': str, 'episodes': set((season, episode)) }
temp_playlist_selections = {}

# Хранилище выбранных качеств для эпизодов
# user_id: { 'series_season_episode': 'quality' }
user_episode_qualities = {}

# --- Глобальное хранилище для пользователей, ожидающих ввода сообщения админу ---
waiting_for_admin_message = {}
# --- Глобальное хранилище для ожидания ответа админа пользователю ---
waiting_admin_reply = {}

# Проверка подписки на канал
async def check_subscription(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал"""
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        print(f"Статус пользователя {user_id} в канале: {member.status}")
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Ошибка проверки подписки для пользователя {user_id}: {e}")
        # Если ошибка - считаем что не подписан
        return False

def get_subscription_message(user_id: int = None) -> tuple[str, InlineKeyboardMarkup]:
    """Возвращает сообщение о необходимости подписки"""
    text = (
        "<b>ПОДПИШИТЕСЬ НА НАШ РЕСУРС, ПРЕЖДЕ ЧЕМ ПРОДОЛЖИТЬ ПОЛЬЗОВАТЬСЯ БОТОМ</b>\n\n"
        "Обычным пользователям нужно подписаться на наш канал, что бы продолжить спокойно пользоваться ботом. "
        "Получите премиум, что бы пользоваться ботом без лимитов и без рекламы: /ref"
    )
    
    # Формируем ссылку на канал из конфига
    channel_url = f"https://t.me/{CHANNEL_USERNAME}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📺 Подписаться на канал", url=channel_url)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")],
        [InlineKeyboardButton(text="🚫 Убрать рекламу", callback_data="ref_system")]
    ])
    
    return text, keyboard
# --- Глобальное хранилище для рассылки ---
broadcast_state = {}

# --- Функция создания предпросмотра рассылки ---
async def create_broadcast_preview(callback, state):
    """Создает предпросмотр рассылки с кнопками"""
    content = state.get("content", {})
    content_type = state.get("type")
    button_configs = state.get("button_configs", [])
    
    # Создаем клавиатуру из кнопок
    buttons = None
    if button_configs:
        keyboard_rows = []
        current_row = []
        
        for config in button_configs:
            if "url" in config:
                btn = InlineKeyboardButton(text=config["text"], url=config["url"])
                current_row.append(btn)
                
                # По 2 кнопки в ряд
                if len(current_row) == 2:
                    keyboard_rows.append(current_row)
                    current_row = []
        
        # Добавляем оставшиеся кнопки
        if current_row:
            keyboard_rows.append(current_row)
        
        if keyboard_rows:
            buttons = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    
    try:
        # Отправляем предпросмотр в зависимости от типа контента
        if content_type == "text":
            await callback.message.edit_text(
                f"📋 <b>Предпросмотр рассылки:</b>\n\n{content['text']}",
                parse_mode="HTML",
                reply_markup=buttons
            )
        elif content_type == "photo":
            await callback.message.delete()
            caption = f"📋 <b>Предпросмотр рассылки:</b>\n\n{content.get('caption', '')}"
            await bot.send_photo(
                callback.from_user.id,
                content["photo"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=buttons
            )
        elif content_type == "video":
            await callback.message.delete()
            caption = f"📋 <b>Предпросмотр рассылки:</b>\n\n{content.get('caption', '')}"
            await bot.send_video(
                callback.from_user.id,
                content["video"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=buttons
            )
        elif content_type == "document":
            await callback.message.delete()
            caption = f"📋 <b>Предпросмотр рассылки:</b>\n\n{content.get('caption', '')}"
            await bot.send_document(
                callback.from_user.id,
                content["document"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=buttons
            )
        elif content_type == "audio":
            await callback.message.delete()
            caption = f"📋 <b>Предпросмотр рассылки:</b>\n\n{content.get('caption', '')}"
            await bot.send_audio(
                callback.from_user.id,
                content["audio"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=buttons
            )
        elif content_type == "voice":
            await callback.message.delete()
            await bot.send_voice(
                callback.from_user.id,
                content["voice"],
                reply_markup=buttons
            )
        elif content_type == "video_note":
            await callback.message.delete()
            await bot.send_video_note(
                callback.from_user.id,
                content["video_note"],
                reply_markup=buttons
            )
        elif content_type == "sticker":
            await callback.message.delete()
            await bot.send_sticker(
                callback.from_user.id,
                content["sticker"],
                reply_markup=buttons
            )
        elif content_type == "animation":
            await callback.message.delete()
            caption = f"📋 <b>Предпросмотр рассылки:</b>\n\n{content.get('caption', '')}"
            await bot.send_animation(
                callback.from_user.id,
                content["animation"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=buttons
            )
        elif content_type == "location":
            await callback.message.delete()
            await bot.send_location(
                callback.from_user.id,
                content["latitude"],
                content["longitude"],
                reply_markup=buttons
            )
        elif content_type == "contact":
            await callback.message.delete()
            await bot.send_contact(
                callback.from_user.id,
                content["phone_number"],
                content["first_name"],
                last_name=content.get("last_name"),
                reply_markup=buttons
            )
        elif content_type == "media_group":
            await callback.message.delete()
            # Для медиагруппы отправляем альбом
            media_list = []
            for i, media_item in enumerate(state["media_group"]):
                if media_item["type"] == "photo":
                    from aiogram.types import InputMediaPhoto
                    media = InputMediaPhoto(
                        media=media_item["media"],
                        caption=f"📋 <b>Предпросмотр альбома ({i+1}/{len(state['media_group'])})</b>\n\n{media_item.get('caption', '')}" if i == 0 else media_item.get('caption', ''),
                        parse_mode="HTML" if i == 0 else None
                    )
                elif media_item["type"] == "video":
                    from aiogram.types import InputMediaVideo
                    media = InputMediaVideo(
                        media=media_item["media"],
                        caption=f"📋 <b>Предпросмотр альбома ({i+1}/{len(state['media_group'])})</b>\n\n{media_item.get('caption', '')}" if i == 0 else media_item.get('caption', ''),
                        parse_mode="HTML" if i == 0 else None
                    )
                media_list.append(media)
            
            await bot.send_media_group(callback.from_user.id, media_list)
            
            # Отправляем кнопки отдельным сообщением для медиагруппы
            if buttons:
                await bot.send_message(
                    callback.from_user.id,
                    "👆 <i>Кнопки будут прикреплены к последнему медиафайлу в альбоме</i>",
                    parse_mode="HTML",
                    reply_markup=buttons
                )
        
        # Отправляем кнопки подтверждения
        confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить рассылку", callback_data="broadcast_send")],
            [InlineKeyboardButton(text="✏️ Изменить кнопки", callback_data="broadcast_buttons")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
        ])
        
        await bot.send_message(
            callback.from_user.id,
            "🎯 <b>Предпросмотр готов!</b>\n\n"
            "☝️ Выше показано, как будет выглядеть рассылка у пользователей.\n"
            "🔘 Кнопки в предпросмотре работают.\n\n"
            "📤 <b>Отправить рассылку всем пользователям?</b>",
            parse_mode="HTML",
            reply_markup=confirm_keyboard
        )
        
    except Exception as e:
        logging.error(f"Error creating broadcast preview: {e}")
        await callback.message.answer(
            "❌ Ошибка при создании предпросмотра. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
            ])
        )

# --- Функция завершения медиагруппы ---
async def finish_media_group_after_delay(user_id, media_group_id):
    """Завершает медиагруппу через 3 секунды если не поступают новые медиафайлы"""
    await asyncio.sleep(3)
    
    if user_id not in broadcast_state:
        return
        
    state = broadcast_state[user_id]
    if state.get("media_group_id") != media_group_id:
        return
        
    if state.get("type") == "media_group" and len(state.get("media_group", [])) > 0:
        # Завершаем медиагруппу
        state["step"] = "buttons"
        
        try:
            await bot.send_message(
                user_id,
                f"📸 <b>Альбом готов!</b>\n\n"
                f"Добавлено медиафайлов: {len(state['media_group'])}\n\n"
                "Теперь выберите кнопки для добавления к альбому или нажмите 'Готово' для предпросмотра:",
                parse_mode="HTML",
                reply_markup=get_broadcast_buttons_keyboard(state.get("selected_buttons", set()))
            )
        except Exception as e:
            logging.error(f"Error finishing media group: {e}")

# --- Глобальное состояние мастера добавления фильма ---
# addfilm_state[user_id] = { 'step': 'key'|'file_id'|'title'|'aliases'|'poster', 'data': {...} }
addfilm_state = {}
addserial_state = {}
tech_support_state = {}  # Состояние пользователей в тех.поддержке

# --- Реклама удалена ---
TTSAVE_BOT_SPAM = ''

# --- Глобальное хранилище для рекламы ---
# ad_waiting_state[user_id] = { 'movie_key': str, 'timestamp': float }
ad_waiting_state = {}

# Партнерская ссылка для рекламы (прямая - гарантированный учет кликов)
AD_LINK = "https://zmgig.com/g/zm0bbusas0a5d14b5688f9ed9c6b58/"

# Сервер для отслеживания кликов (если используете)
# Раскомментируйте и укажите свой домен:
# AD_TRACKER_URL = "https://your-server.com/track/"
AD_TRACKER_URL = None  # Пока отключено

# === Клавиатура благодарности (поиск + связаться с админом) ===
def get_gratitude_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔎 Начать поиск", switch_inline_query_current_chat=""),
            InlineKeyboardButton(text="💬 Связаться с админом", callback_data="contact_admin_start"),
        ]
    ])

# === Периодическая рассылка благодарности ===
async def periodic_gratitude_broadcast(bot: Bot, interval_hours: int = 5):
    """Периодически отправляет сообщение благодарности всем пользователям из stats['users']."""
    while True:
        users = list(set(stats.get("users", []) or []))
        if users:
            text = (
                "🙏 Спасибо, что пользуетесь нашим ботом!\n\n"
                "Напишите нам, какие фильмы ещё добавить — прислушиваемся к каждому запросу."
            )
            for uid in users:
                try:
                    await bot.send_message(int(uid), text, reply_markup=get_gratitude_keyboard())
                    await asyncio.sleep(0.05)  # лёгкий троттлинг
                except Exception:
                    # Игнорируем недоставленные (например, стопнули бота)
                    continue
        # Ждём до следующей рассылки
        await asyncio.sleep(max(1, int(interval_hours * 3600)))

# === Варианты подсказки для карточек фильмов ===
WATCH_HINTS = [
    "Нажми ▶️ Смотреть, чтобы отправить видео.",
    "Нажми ▶️ Смотреть, чтобы открыть плеер.",
    "Тапни ▶️ Смотреть — начнём!",
    "Жми ▶️ Смотреть — и поехали!",
    "Выбери ▶️ Смотреть, чтобы запустить.",
    "Нажми ▶️ Смотреть, чтобы смотреть сейчас."
]

def get_watch_hint() -> str:
    try:
        return random.choice(WATCH_HINTS)
    except Exception:
        return WATCH_HINTS[0]

# === Функции для системы лимитов ===
def format_time_remaining(seconds: int) -> str:
    """Форматирует оставшееся время в формате ЧЧ:ММ:СС"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def get_movie_limit_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для сообщения о лимите фильмов"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить время", callback_data="refresh_movie_limit")],
        [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="ref_system")]
    ])

def get_episode_limit_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для сообщения о лимите серий"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить время", callback_data="refresh_episode_limit")],
        [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="ref_system")]
    ])

# === Функция для получения всех доступных сериалов ===
def get_all_available_series() -> list:
    """Получает список всех доступных сериалов из базы данных и хардкодированных"""
    series_list = []
    
    # Добавляем хардкодированные сериалы
    hardcoded_series = [
        {"key": "rm", "title": "Рик и Морти", "description": "сериал"},
        {"key": "phf", "title": "Финес и Ферб", "description": "сериал"},
        {"key": "lbsc", "title": "Леди Баг и Супер‑Кот", "description": "сериал"},
        {"key": "irh", "title": "Железное сердце", "description": "сериал"},
        {"key": "wnd", "title": "Уэнсдэй (2022)", "description": "сериал"},
        {"key": "loki", "title": "Локи (2021)", "description": "сериал"}
    ]
    
    # Добавляем сериалы из базы данных
    try:
        from db import load_all_series
        db_series = load_all_series()
        for series in db_series:
            # Проверяем, что сериал не дублируется с хардкодированными
            if not any(s["key"] == series["key"] for s in hardcoded_series):
                series_list.append({
                    "key": series["key"],
                    "title": series["title"],
                    "description": "сериал"
                })
    except Exception as e:
        logging.exception(f"[get_all_available_series] Ошибка при загрузке сериалов из БД: {e}")
    
    # Объединяем все сериалы
    all_series = hardcoded_series + series_list
    return all_series


async def send_episode_to_user(callback, series_key: str, season: int, episode: int, is_auto_first_episode: bool = False):
    """Отправляет серию пользователю автоматически"""
    try:
        from storage import get_cached_episode
        
        # Получаем выбранное пользователем качество
        user_id = callback.from_user.id
        episode_key = f"{series_key}_{season}_{episode}"
        selected_quality = "1080p"  # По умолчанию
        
        if user_id in user_episode_qualities and episode_key in user_episode_qualities[user_id]:
            selected_quality = user_episode_qualities[user_id][episode_key]
        
        # Получаем данные эпизода в зависимости от выбранного качества
        if selected_quality == "1080p":
            # Базовое качество из основной таблицы
            episode_data = get_cached_episode(series_key, season, episode)
            if not episode_data:
                logging.warning(f"[send_episode_to_user] Серия не найдена: {series_key} S{season}E{episode}")
                return
            file_id = episode_data['file_id']
            file_type = episode_data['type']
        else:
            # Дополнительное качество из таблицы episode_qualities
            file_id = get_episode_quality_file_id(series_key, season, episode, selected_quality)
            if not file_id:
                # Если качество не найдено, используем базовое
                episode_data = get_cached_episode(series_key, season, episode)
                if not episode_data:
                    logging.warning(f"[send_episode_to_user] Серия не найдена: {series_key} S{season}E{episode}")
                    return
                file_id = episode_data['file_id']
                file_type = episode_data['type']
                selected_quality = "1080p"
            else:
                file_type = "video"
        
        # Определяем название сериала
        series_titles = {
            "rm": "Рик и Морти",
            "lbsc": "Леди Баг и Супер Кот", 
            "phf": "Финес и Ферб",
            "wnd": "Уэнсдэй (2022)",
            "irh": "Железное сердце",
            "loki": "Локи (2021)"
        }
        
        series_title = series_titles.get(series_key, series_key.upper())
        caption = f"<b>🎬 Серия {episode}</b>\n<b>Сезон {season}</b>\n{series_title}\n<b>Качество: {selected_quality}</b>\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"
        
        # Создаем клавиатуру с кнопкой для серии
        share_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к навигации", callback_data=f"dynamic_episode_{series_key}_{season}_{episode}")],
            [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
        ])
        
        # Отправляем серию
        if file_type == 'video':
            await callback.message.answer_video(
                video=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=share_keyboard
            )
        else:
            await callback.message.answer_document(
                document=file_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=share_keyboard
            )
        
        # Добавляем просмотр серии в статистику (не считаем первую серию)
        if not is_auto_first_episode:
            try:
                from db import add_content_view
                episode_key = f"{series_key}_{season}_{episode}"
                add_content_view(callback.from_user.id, 'episode', episode_key)
                # Также добавляем просмотр сериала в целом
                add_content_view(callback.from_user.id, 'series', series_key)
            except Exception as e:
                logging.error(f"Ошибка при добавлении просмотра серии {series_key} S{season}E{episode}: {e}")
        
        logging.info(f"[send_episode_to_user] Отправлена серия: {series_key} S{season}E{episode} пользователю {callback.from_user.id}")
        
    except Exception as e:
        logging.exception(f"[send_episode_to_user] Ошибка: {e}")

# === Функция для создания навигации сериалов ===
async def show_series_navigation(callback: CallbackQuery, series_key: str, season: int = None, episode: int = None) -> bool:
    """Отображает навигацию по сериалу, удаляя старое сообщение и отправляя новое."""
    try:
        user_id = callback.from_user.id
        is_action = season is not None or episode is not None
        logging.info(f"[NAV_START] user={user_id}, series={series_key}, season={season}, episode={episode}, is_action={is_action}")

        # Используем кэшированные данные вместо загрузки всех данных
        from storage import get_cached_series_data, get_cached_episode
        from db import load_all_series

        # Получаем кэшированные данные сериала
        cache_data = get_cached_series_data(series_key)
        series_episodes = cache_data['episodes']
        available_seasons = cache_data['available_seasons']

        if not series_episodes:
            await callback.answer("Для этого сериала еще не добавлены эпизоды.", show_alert=True)
            return False

        # Получаем информацию о сериале (можно тоже кэшировать в будущем)
        all_db_series = load_all_series()
        series_info = next((s for s in all_db_series if s['key'] == series_key), None)
        title = series_info['title'] if series_info else series_key.upper()
        callback_prefix = f"dynamic_episode_{series_key}"

        target_season = season if season in available_seasons else available_seasons[0]
        target_episode = episode if episode is not None else 1
        
        logging.info(f"[NAV_TARGET] Цель: S{target_season}E{target_episode}")

        # Используем кэшированную функцию для получения серии
        episode_data = get_cached_episode(series_key, target_season, target_episode)

        if not episode_data:
            available_in_season = [ep for ep in series_episodes if ep['season'] == target_season]
            if available_in_season:
                episode_data = sorted(available_in_season, key=lambda x: x['episode'])[0]
                target_episode = episode_data['episode']
                logging.warning(f"[NAV_FALLBACK] Серия не найдена. Взяли первую в сезоне: S{target_season}E{target_episode}")
            else:
                episode_data = sorted(series_episodes, key=lambda x: (x['season'], x['episode']))[0]
                target_season = episode_data['season']
                target_episode = episode_data['episode']
                logging.error(f"[NAV_FALLBACK] В сезоне нет серий. Взяли первую в сериале: S{target_season}E{target_episode}")

        # Проверяем выбранное пользователем качество и обновляем episode_data при необходимости
        episode_key = f"{series_key}_{target_season}_{target_episode}"
        if user_id not in user_episode_qualities:
            user_episode_qualities[user_id] = {}
        
        selected_quality = user_episode_qualities[user_id].get(episode_key, "1080p")
        
        # Если выбрано качество отличное от базового 1080p, получаем соответствующий file_id
        if selected_quality != "1080p":
            quality_file_id = get_episode_quality_file_id(series_key, target_season, target_episode, selected_quality)
            if quality_file_id:
                # Создаем копию episode_data с обновленным file_id
                episode_data = episode_data.copy()
                episode_data['file_id'] = quality_file_id
                episode_data['type'] = 'video'  # Предполагаем, что дополнительные качества - это видео
                logging.info(f"[NAV_QUALITY] Используем качество {selected_quality} для S{target_season}E{target_episode}")
            else:
                # Если файл для выбранного качества не найден, сбрасываем на базовое
                user_episode_qualities[user_id][episode_key] = "1080p"
                selected_quality = "1080p"
                logging.warning(f"[NAV_QUALITY] Качество {selected_quality} не найдено, используем базовое 1080p")

        season_buttons = []
        if len(available_seasons) > 1:
            current_season_index = available_seasons.index(target_season)
            prev_season = available_seasons[current_season_index - 1]
            next_season = available_seasons[(current_season_index + 1) % len(available_seasons)]
            season_buttons.extend([
                InlineKeyboardButton(text="◀", callback_data=f"series_nav_{series_key}_{prev_season}"),
                InlineKeyboardButton(text=f"Сезон {target_season}", callback_data="noop"),
                InlineKeyboardButton(text="▶", callback_data=f"series_nav_{series_key}_{next_season}")
            ])
        else:
            season_buttons.append(InlineKeyboardButton(text=f"Сезон {target_season}", callback_data="noop"))
        
        # Оптимизированное получение серий в сезоне - используем кэшированные данные
        episodes_in_season = sorted([ep['episode'] for ep in series_episodes if ep['season'] == target_season])
        episode_buttons = []
        row = []
        for ep_num in episodes_in_season:
            text = f"[ {ep_num} ]" if ep_num == target_episode else str(ep_num)
            row.append(InlineKeyboardButton(text=text, callback_data=f"{callback_prefix}_{target_season}_{ep_num}"))
            if len(row) == 5:
                episode_buttons.append(row)
                row = []
        if row: episode_buttons.append(row)

        from keyboards import BACK_TO_MAIN_MENU_BUTTON
        
        # Проверяем, добавлена ли серия в избранное
        from db import is_in_favorites
        user_id = callback.from_user.id
        
        # Формируем ключ для проверки
        if series_key == "lbsc":
            check_key = f"lbsc_{target_season}_{target_episode}"
            content_type = "lbsc_series"
        else:
            check_key = f"{series_key}_{target_season}_{target_episode}"
            content_type = "series"
        
        is_favorited = is_in_favorites(user_id, content_type, check_key)
        
        # Создаем кнопку в зависимости от статуса избранного
        if is_favorited:
            favorite_button = [InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{check_key}")]
        else:
            favorite_button = [InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"{series_key}_fav_{target_season}_{target_episode}")]
        
        # Добавляем кнопку качества с текущим выбранным качеством
        quality_text = f"Качество: {selected_quality}"
        
        quality_button = [InlineKeyboardButton(text=quality_text, callback_data=f"quality_{series_key}_{target_season}_{target_episode}")]
        
        # Добавляем кнопку "Случайная серия" для всех пользователей
        random_episode_button = [InlineKeyboardButton(text="🎯 Случайная серия", callback_data=f"random_episode_{series_key}")]
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[season_buttons] + episode_buttons + [favorite_button] + [quality_button] + [random_episode_button] + [BACK_TO_MAIN_MENU_BUTTON])

        caption = f"<b>{title}</b>\nСезон {target_season} • Серия {target_episode}\n\n• Выберите серию:\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"

        # ПРОВЕРКА ЕДИНОГО ЛИМИТА ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ (только при выборе серии, не при первом открытии)
        is_admin = user_id in ADMIN_IDS
        is_premium = is_premium_user(user_id)
        logging.info(f"[NAV_LIMIT_CHECK] user_id={user_id}, is_action={is_action}, is_admin={is_admin}, is_premium={is_premium}")
        
        if is_action and not is_admin and not is_premium:
            daily_content = get_user_daily_content_count(user_id)
            logging.info(f"[NAV] Пользователь {user_id} просмотрел {daily_content} контента за 24 часа")
            
            if daily_content > DAILY_CONTENT_LIMIT:
                from db import get_time_until_limit_reset
                reset_time = get_time_until_limit_reset(user_id, 'episode')  # Используем любой тип для расчета времени
                hours = reset_time // 3600
                minutes = (reset_time % 3600) // 60
                
                time_text = ""
                if hours > 0:
                    time_text += f"{hours} ч. "
                if minutes > 0:
                    time_text += f"{minutes} мин."
                if not time_text:
                    time_text = "менее минуты"
                
                limit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_content_limit")],
                    [InlineKeyboardButton(text="💎 Получить премиум", callback_data="ref_system")],
                    [BACK_TO_MAIN_MENU_BUTTON]
                ])
                
                await callback.edit_message_text(
                    f"🚫 <b>Лимит на контент превышен</b>\n\n"
                    f"🎬 Вы уже посмотрели <b>{daily_content}/{DAILY_CONTENT_LIMIT}</b> контента за последние 24 часа.\n\n"
                    f"⏰ Лимит сбросится через: <b>{time_text}</b>\n\n"
                    f"💎 <b>Премиум пользователи</b> могут смотреть без ограничений!",
                    parse_mode="HTML",
                    reply_markup=limit_keyboard
                )
                return

        # Если это не первый запуск, пытаемся редактировать
        if is_action:
            current_media_id = None
            if callback.message.video:
                current_media_id = callback.message.video.file_id
            elif callback.message.document:
                current_media_id = callback.message.document.file_id

            # Если file_id отличается, меняем медиа
            if episode_data and episode_data['file_id'] != current_media_id:
                try:
                    media_type = 'video' if episode_data['type'] == 'video' else 'document'
                    media = InputMediaVideo(media=episode_data['file_id'], caption=caption, parse_mode="HTML") if media_type == 'video' else InputMediaDocument(media=episode_data['file_id'], caption=caption, parse_mode="HTML")
                    await callback.message.edit_media(media=media, reply_markup=keyboard)
                    logging.info(f"[NAV_EDIT_MEDIA] Медиа обновлено для S{target_season}E{target_episode}")
                except TelegramBadRequest as e:
                    if "message is not modified" in e.message:
                        logging.warning("[NAV_EDIT_MEDIA] Сообщение не изменено, пропуск.")
                    else:
                        logging.exception(f"[NAV_EDIT_MEDIA] Ошибка BadRequest при обновлении медиа: {e}")
                except Exception as e:
                    logging.exception(f"[NAV_EDIT_MEDIA] Глобальная ошибка при обновлении медиа: {e}")
            # Если file_id тот же, меняем только клавиатуру и заголовок
            else:
                try:
                    await callback.message.edit_caption(caption=caption, reply_markup=keyboard, parse_mode="HTML")
                    logging.info(f"[NAV_EDIT_CAPTION] Заголовок и клавиатура обновлены для S{target_season}E{target_episode}")
                except TelegramBadRequest as e:
                    if "message is not modified" in e.message:
                        # Если сообщение не изменилось, попробуем обновить только клавиатуру
                        try:
                            await callback.message.edit_reply_markup(reply_markup=keyboard)
                            logging.info(f"[NAV_EDIT_KEYBOARD] Клавиатура обновлена для S{target_season}E{target_episode}")
                        except Exception as keyboard_error:
                            logging.exception(f"[NAV_EDIT_KEYBOARD] Ошибка при обновлении клавиатуры: {keyboard_error}")
                    else:
                        logging.exception(f"[NAV_EDIT_CAPTION] Ошибка BadRequest при обновлении заголовка: {e}")
                except Exception as e:
                    logging.exception(f"[NAV_EDIT_CAPTION] Глобальная ошибка при обновлении заголовка: {e}")
        # Если это первый запуск, отправляем новое сообщение
        else:
            if episode_data['type'] == 'video':
                await bot.send_video(callback.message.chat.id, video=episode_data['file_id'], caption=caption, reply_markup=keyboard, parse_mode="HTML")
            else:
                await bot.send_document(callback.message.chat.id, document=episode_data['file_id'], caption=caption, reply_markup=keyboard, parse_mode="HTML")
            logging.info(f"[NAV_SEND] Отправлено новое сообщение S{target_season}E{target_episode}")
            
            # Добавляем просмотр серии в статистику (первая серия не считается)
            # Первая серия открывается автоматически, поэтому не считаем
            # Не добавляем просмотр для первой серии
        
        # Добавляем просмотр серии в статистику, если это НЕ первая серия
        if is_action:
            try:
                from db import add_content_view
                episode_key = f"{series_key}_{target_season}_{target_episode}"
                add_content_view(user_id, 'episode', episode_key)
                # Также добавляем просмотр сериала в целом
                add_content_view(user_id, 'series', series_key)
                logging.info(f"[NAV] Просмотр серии {episode_key} добавлен в статистику")
            except Exception as e:
                logging.error(f"Ошибка при добавлении просмотра серии {series_key} S{target_season}E{target_episode}: {e}")
        
        return True

    except Exception as e:
        logging.exception(f"[NAV_ERROR] Глобальная ошибка в навигации: {e}")
        await callback.answer("Произошла серьезная ошибка при навигации.", show_alert=True)
        return False

# === Обработчики состояний для добавления контента ===
async def handle_addserial_state(message: Message):
    """Обработка пошагового добавления сериала"""
    user_id = message.from_user.id
    state = addserial_state[user_id]
    step = state['step']
    data = state['data']
    
    if step == 'key':
        # Валидация ключа
        key = message.text.strip()
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', key):
            from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="addserial_cancel_step")]
            ])
            await message.reply("❌ Ключ должен содержать только латинские буквы, цифры и подчеркивания. Попробуйте еще раз:", reply_markup=cancel_keyboard)
            return
        
        data['key'] = key
        state['step'] = 'title'
        from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="addserial_cancel_step")]
        ])
        await message.reply(
            "📺 <b>Название сериала</b>\n\n"
            "Введите название сериала:\n"
            "<i>Например: Локи (2021), Игра престолов, Во все тяжкие</i>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
    
    elif step == 'title':
        title = message.text.strip()
        if not title:
            from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="addserial_cancel_step")]
            ])
            await message.reply("❌ Название не может быть пустым. Попробуйте еще раз:", reply_markup=cancel_keyboard)
            return
        
        data['title'] = title
        # Автоматически генерируем ключевые слова
        data['aliases'] = generate_keywords_from_title(title)
        state['step'] = 'poster'
        from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="addserial_cancel_step")]
        ])
        await message.reply(
            "🖼 <b>Постер сериала</b>\n\n"
            "Отправьте URL постера сериала:\n"
            "<i>Например: https://example.com/poster.jpg</i>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
    
    elif step == 'poster':
        poster_url = message.text.strip()
        if not poster_url.startswith(('http://', 'https://')):
            from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="addserial_cancel_step")]
            ])
            await message.reply("❌ URL должен начинаться с http:// или https://. Попробуйте еще раз:", reply_markup=cancel_keyboard)
            return
        
        data['poster_url'] = poster_url
        state['step'] = 'confirm'
        
        # Показываем предварительный просмотр
        keywords_text = ", ".join(data['aliases'][:5]) + ("..." if len(data['aliases']) > 5 else "")
        
        from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сохранить", callback_data="addserial_confirm")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="addserial_cancel")]
        ])
        
        await message.reply(
            f"📺 <b>Подтверждение добавления сериала</b>\n\n"
            f"🔑 <b>Ключ:</b> <code>{data['key']}</code>\n"
            f"📺 <b>Название:</b> {data['title']}\n"
            f"🖼 <b>Постер:</b> {poster_url}\n"
            f"🏷 <b>Ключевые слова:</b> {keywords_text}\n\n"
            f"Все верно?",
            parse_mode="HTML",
            reply_markup=keyboard
        )

async def handle_addfilm_state(message: Message):
    """Обработка пошагового добавления фильма"""
    user_id = message.from_user.id
    state = addfilm_state[user_id]
    step = state['step']
    data = state['data']
    
    if step == 'key':
        # Валидация ключа
        key = message.text.strip()
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', key):
            from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
            ])
            await message.reply("❌ Ключ должен содержать только латинские буквы, цифры и подчеркивания. Попробуйте еще раз:", reply_markup=cancel_keyboard)
            return
        
        data['key'] = key
        state['step'] = 'title'
        from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
        ])
        await message.reply(
            "🎬 <b>Название фильма</b>\n\n"
            "Введите название фильма:\n"
            "<i>Например: Аватар: Путь воды, Мстители: Финал</i>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
    
    elif step == 'title':
        title = message.text.strip()
        if not title:
            from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
            ])
            await message.reply("❌ Название не может быть пустым. Попробуйте еще раз:", reply_markup=cancel_keyboard)
            return
        
        data['title'] = title
        # Автоматически генерируем ключевые слова
        data['aliases'] = generate_keywords_from_title(title)
        state['step'] = 'file_id'
        from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
        ])
        await message.reply(
            "📱 <b>File ID видео</b>\n\n"
            "Отправьте видео или используйте команду /fileid для получения file_id:",
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
    
    elif step == 'file_id':
        file_id = None
        if message.video:
            file_id = message.video.file_id
        elif message.document:
            file_id = message.document.file_id
        elif message.text:
            file_id = message.text.strip()
        
        if not file_id:
            from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
            ])
            await message.reply("❌ Отправьте видео или введите file_id. Попробуйте еще раз:", reply_markup=cancel_keyboard)
            return
        
        data['file_id'] = file_id
        state['step'] = 'poster'
        from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
        ])
        await message.reply(
            "🖼 <b>Постер фильма</b>\n\n"
            "Отправьте URL постера фильма:\n"
            "<i>Например: https://example.com/poster.jpg</i>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
    
    elif step == 'poster':
        poster_url = message.text.strip()
        if not poster_url.startswith(('http://', 'https://')):
            from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
            cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
            ])
            await message.reply("❌ URL должен начинаться с http:// или https://. Попробуйте еще раз:", reply_markup=cancel_keyboard)
            return
        
        data['poster_url'] = poster_url
        state['step'] = 'confirm'
        
        # Показываем предварительный просмотр
        keywords_text = ", ".join(data['aliases'][:5]) + ("..." if len(data['aliases']) > 5 else "")
        
        from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сохранить", callback_data="addfilm_confirm")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel")]
        ])
        
        await message.reply(
            f"🎬 <b>Подтверждение добавления фильма</b>\n\n"
            f"🔑 <b>Ключ:</b> <code>{data['key']}</code>\n"
            f"📺 <b>Название:</b> {data['title']}\n"
            f"📱 <b>File ID:</b> <code>{data['file_id']}</code>\n"
            f"🖼 <b>Постер:</b> {poster_url}\n"
            f"🏷 <b>Ключевые слова:</b> {keywords_text}\n\n"
            f"Все верно?",
            parse_mode="HTML",
            reply_markup=keyboard
        )

# Обработчик show_media_file_id перемещен в конец файла


def _build_stats_text():
    """Построить текст со статистикой бота"""
    stats = get_user_stats()
    
    text = f"""📊 <b>Статистика бота</b>

👥 <b>Пользователи:</b>
• Всего зарегистрировано: <code>{stats['total_users']}</code>
• Активных за неделю: <code>{stats['active_users']}</code>

💬 <b>Сообщения:</b>
• Всего обработано: <code>{stats['total_messages']}</code>

🕐 <b>Обновлено:</b> {datetime.datetime.now(timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M')} (Киев)"""
    
    return text


def _stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Обновить", callback_data="stats_refresh")]])


@router.message(Command("test"))
async def test_command(message: Message):
    """Тестовая команда для проверки работы бота"""
    await message.reply("✅ Бот работает! Команды обрабатываются корректно.")

@router.message(Command("stats"))
async def show_stats(message: Message):
    user_id = message.from_user.id
    print(f"DEBUG: User {user_id} trying to use /stats command")
    print(f"DEBUG: ADMIN_IDS = {ADMIN_IDS}")
    print(f"DEBUG: User in admins: {user_id in ADMIN_IDS}")
    
    if user_id not in ADMIN_IDS:
        await message.reply(f"⛔️ У вас нет доступа к этой команде.\nВаш ID: {user_id}\nАдмин IDs: {ADMIN_IDS}")
        return
    
    try:
        text = _build_stats_text()
        stats_keyboard = _stats_keyboard()
        await message.reply(text, parse_mode="HTML", reply_markup=stats_keyboard)
    except Exception as e:
        await message.reply(f"❌ Ошибка при получении статистики: {e}")
        print(f"ERROR in stats command: {e}")

# === Утилита: показать мой Telegram ID ===
@router.message(Command("myid"))
async def cmd_myid(message: Message):
    try:
        await message.reply(f"Ваш Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось определить ID")

# === Реферальная система ===
@router.message(Command("ref"))
async def referral_system(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "пользователь"
    
    # Сохраняем пользователя в БД
    save_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code
    )
    
    # Получаем количество рефералов
    referrals_count = get_referrals_count(user_id)
    
    # Создаем реферальную ссылку
    bot_username = BOT_USERNAME.replace("@", "")
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    # Формируем текст сообщения
    text = (
        f"<b><i>Привет, это реферальная система.</i></b>\n\n"
        f"Вам нужно пригласить как минимум 2 человек, что бы приобрести так называемый <b>премиум-статус🤑</b>\n\n"
        f"<b><i>Премиум-статус даёт:</i></b>\n"
        f"<b>Возможность добавлять фильмы, серии в избранное;\n"
        f"Доступ к кнопке \"Случайный фильм\" и \"Случайная серия\" вашего любимого сериала;\n"
        f"А также ваш телеграмм-ник отобразится в кнопке \"Премиум-пользователи\"</b>\n\n"
        f"<b>Ваша реферальная ссылка:</b> <code>{referral_link}</code>\n"
        f"Вы пригласили людей: {referrals_count}/2\n\n"
        f"<b><i>Скопируй ссылку, и отправь ее другу!</i></b>"
    )
    
    # Создаем кнопку назад в главное меню
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

# === Премиум пользователи ===
@router.message(Command("puser"))
async def cmd_premium_users(message: Message):
    """Показать список премиум пользователей"""
    premium_users = get_premium_users()
    
    if not premium_users:
        text = "🍬 <b>Премиум пользователи</b>\n\nПока нет пользователей с премиум-статусом.\nПригласите друзей и получите премиум!"
    else:
        text = "🍬 <b>Премиум пользователи</b>\n\n"
        for i, user in enumerate(premium_users, 1):
            name = user['first_name'] or "Пользователь"
            if user['last_name']:
                name += f" {user['last_name']}"
            text += f"{i}. {name} ({user['referrals_count']} рефералов)\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(Command("saved"))
async def cmd_saved(message: Message):
    """Показать избранные фильмы и серии пользователя (только для премиум пользователей и админа)"""
    user_id = message.from_user.id
    
    # Проверяем, является ли пользователь админом или имеет премиум статус
    if user_id not in ADMIN_IDS and not is_premium_user(user_id):
        await message.answer(
            "🔒 <b>Доступ ограничен</b>\n\n"
            "Эта функция доступна только для премиум пользователей!\n\n"
            "💰 Пригласите 2 друзей через реферальную систему и получите премиум статус.",
            parse_mode="HTML"
        )
        return
    
    from db import get_favorites_count
    
    # Подсчитываем количество избранных фильмов и серий
    movies_count = get_favorites_count(user_id, 'movie')
    lbsc_series_count = get_favorites_count(user_id, 'lbsc_series')
    other_series_count = get_favorites_count(user_id, 'series')
    series_count = lbsc_series_count + other_series_count
    
    text = (
        "<b><i>⭐️Ваши избранные серии:</i></b>\n\n"
        f"Вы добавили фильмов: {movies_count}\n"
        f"<b>Вы добавили серий: {series_count}</b>\n\n"
        "<b><i>Нажмите, в какой раздел хотите зайти:</i></b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Фильмы", callback_data="favorites_movies"),
            InlineKeyboardButton(text="📺 Серии", callback_data="favorites_series")
        ],
        [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.message(Command("reffull"))
async def cmd_reffull(message: Message):
    """Команда для админа - дает пользователю 2 реферала (премиум статус)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔️ Команда только для админа")
        return
    
    user_id = message.from_user.id
    
    # Сохраняем пользователя в БД
    save_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code
    )
    
    # Устанавливаем количество рефералов = 2 напрямую в БД
    from db import get_conn
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET referrals_count = 2 WHERE user_id = %s",
                (user_id,)
            )
            conn.commit()
        conn.close()
        
        await message.answer(
            "✅ <b>Премиум статус активирован!</b>\n\n"
            "🤑 Вам установлено 2 реферала\n"
            "⭐️ Теперь вы можете использовать команду /saved\n"
            "🎬 Добавлять фильмы и серии в избранное",
            parse_mode="HTML"
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при установке рефералов: {e}")
        logging.error(f"Error setting referrals for admin {user_id}: {e}")

# === Команда /start с обработкой реферальных ссылок ===
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    
    # Сохраняем пользователя в БД
    save_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code
    )
    
    # Проверка подписки (кроме админов и премиум пользователей)
    if user_id not in ADMIN_IDS and not is_premium_user(user_id):
        if not await check_subscription(user_id):
            text, keyboard = get_subscription_message(user_id)
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
            return
    
    # Проверяем, есть ли реферальный код
    if message.text and len(message.text.split()) > 1:
        start_param = message.text.split()[1]
        
        if start_param.startswith("ref_"):
            try:
                referrer_id = int(start_param.replace("ref_", ""))
                logging.info(f"Processing referral: user {user_id} from referrer {referrer_id}")
                
                # Добавляем реферала
                referral_result = add_referral(referrer_id, user_id)
                logging.info(f"Referral result for {user_id} from {referrer_id}: {referral_result}")
                
                if referral_result:
                    # Уведомляем нового пользователя
                    is_premium = is_premium_user(user_id)
                    premium_status = "<b>Вы являетесь премиум пользователем</b>" if is_premium else "<b>Вы не являетесь премиум пользователем</b>"
                    
                    await message.answer(
                        "🎉 Привет!👋\n\n"
                        "<i>Ты попал в кино-бот по реферальной ссылке!</i> <b>У нас большая коллекция фильмов и сериалов на любой вкус!</b>🎥\n\n"
                        f"{premium_status}\n\n"
                        "<b><i>Что бы ознакомиться с ботом, нажми /help либо \"Помощь\".</i></b>\n\n"
                        "Нажми на \"Начать поиск\" и приятного тебе <b>просмотра!</b>",
                        parse_mode="HTML",
                        reply_markup=get_main_menu_keyboard()
                    )
                    
                    # Уведомляем пригласившего пользователя
                    try:
                        referrals_count = get_referrals_count(referrer_id)
                        
                        # Активируем премиум на 7 дней при достижении 2 рефералов
                        if referrals_count >= 2:
                            activate_premium(referrer_id, 7, f"referral_{referrer_id}")
                            await bot.send_message(
                                referrer_id,
                                f"🎉 <b>Поздравляем!</b>\n\n"
                                f"Новый пользователь присоединился по вашей реферальной ссылке!\n"
                                f"Теперь у вас {referrals_count} рефералов.\n\n"
                                f"🤑 <b>Вы получили премиум-статус на 7 дней!</b>\n\n"
                                f"Теперь вам доступны:\n"
                                f"• Безлимитный просмотр\n"
                                f"• Избранное\n"
                                f"• Случайные фильмы и серии",
                                parse_mode="HTML"
                            )
                        else:
                            await bot.send_message(
                                referrer_id,
                                f"🎉 <b>Поздравляем!</b>\n\n"
                                f"Новый пользователь присоединился по вашей реферальной ссылке!\n"
                                f"Теперь у вас {referrals_count} рефералов.\n\n"
                                f"Осталось пригласить: {2 - referrals_count} человек для премиум-статуса на 7 дней",
                                parse_mode="HTML"
                            )
                    except Exception as e:
                        logging.error(f"Error notifying referrer {referrer_id}: {e}")
                    
                    return
                else:
                    # Реферал уже был добавлен или другая ошибка
                    logging.info(f"Referral failed for {user_id} from {referrer_id} - already exists or error")
                    
                    is_premium = is_premium_user(user_id)
                    premium_status = "<b>Вы являетесь премиум пользователем</b>" if is_premium else "<b>Вы не являетесь премиум пользователем</b>"
                    
                    await message.answer(
                        "Привет!👋\n\n"
                        "<i>Ты попал в кино-бот!</i> <b>У нас большая коллекция фильмов и сериалов на любой вкус!</b>🎥\n\n"
                        f"{premium_status}\n\n"
                        "<b><i>Что бы ознакомиться с ботом, нажми /help либо \"Помощь\".</i></b>\n\n"
                        "Нажми на \"Начать поиск\" и приятного тебе <b>просмотра!</b>\n\n"
                        "<i>Примечание: Реферальная ссылка уже была использована ранее.</i>",
                        parse_mode="HTML",
                        reply_markup=get_main_menu_keyboard()
                    )
                    return
                    
            except ValueError:
                # Неверный формат реферального кода
                pass
    
    
    # Обычное приветствие без реферального кода
    is_premium = is_premium_user(user_id)
    premium_status = "<b>Вы являетесь премиум пользователем</b>" if is_premium else "<b>Вы не являетесь премиум пользователем</b>"
    
    await message.answer(
        "Привет!👋\n\n"
        "<i>Ты попал в кино-бот!</i> <b>У нас большая коллекция фильмов и сериалов на любой вкус!</b>🎥\n\n"
        f"{premium_status}\n\n"
        "<b><i>Что бы ознакомиться с ботом, нажми /help либо \"Помощь\".</i></b>\n\n"
        "Нажми на \"Начать поиск\" и приятного тебе <b>просмотра!</b>",
        parse_mode="HTML",
        reply_markup=get_main_menu_keyboard()
    )

# === Команда /clearreferrals — очистить все рефералы (только для админа) ===
@router.message(Command("clearreferrals"))
async def cmd_clear_referrals(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ Эта команда доступна только администратору.")
        return
    
    from db import clear_all_referrals
    
    try:
        result = clear_all_referrals()
        if result:
            await message.reply("✅ Все рефералы успешно очищены!")
        else:
            await message.reply("❌ Ошибка при очистке рефералов.")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
        logging.error(f"Error in clearreferrals command: {e}")

# === Команда /clearlimit — очистить свой лимит за 24 часа ===
@router.message(Command("clearlimit"))
async def cmd_clear_limit(message: Message):
    """Очистить лимит просмотров фильмов и серий за 24 часа"""
    user_id = message.from_user.id
    
    # Проверка на админа
    if user_id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    from db import clear_user_daily_limits, get_user_daily_movies_count, get_user_daily_episodes_count
    
    # Получаем текущие значения до очистки
    movies_before = get_user_daily_movies_count(user_id)
    episodes_before = get_user_daily_episodes_count(user_id)
    
    try:
        result = clear_user_daily_limits(user_id)
        if result:
            text = (
                "✅ <b>Лимит успешно очищен!</b>\n\n"
                f"🎬 Фильмов было: {movies_before}/2\n"
                f"📺 Серий было: {episodes_before}/4\n\n"
                "🆕 Теперь вы можете снова смотреть фильмы и серии!"
            )
            await message.reply(text, parse_mode="HTML")
        else:
            await message.reply("❌ Ошибка при очистке лимита.")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")
        logging.error(f"Error in clearlimit command: {e}")

# === Утилита: /fileid — ответить file_id любого присланного медиа ===
@router.message(Command("fileid"))
async def cmd_fileid(message: Message):
    if not (message.video or message.document or message.photo):
        # Если это ответ на сообщение с медиа — возьмём из reply_to_message
        m = message.reply_to_message
    else:
        m = message
    fid = None
    media_type = None
    try:
        if m and getattr(m, 'video', None):
            fid = m.video.file_id
            media_type = 'video'
        elif m and getattr(m, 'document', None):
            fid = m.document.file_id
            media_type = 'document'
        elif m and getattr(m, 'photo', None):
            fid = m.photo[-1].file_id
            media_type = 'photo'
    except Exception:
        fid = None
    if fid:
        await message.reply(f"Тип: <b>{media_type}</b>\nfile_id:\n<code>{fid}</code>", parse_mode="HTML")
    else:
        await message.reply("Пришлите медиа или ответьте на сообщение с медиа командой /fileid")

# === Функция для генерации ключевых слов ===
def generate_keywords_from_title(title: str) -> list:
    """Генерирует ключевые слова из названия"""
    import re
    
    # Убираем специальные символы и разбиваем на слова
    words = re.findall(r'\b\w+\b', title.lower())
    
    # Убираем короткие слова (менее 3 символов) и стоп-слова
    stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'от', 'до', 'из', 'к', 'о', 'об', 'the', 'and', 'or', 'of', 'to', 'in', 'a', 'an'}
    keywords = [word for word in words if len(word) >= 3 and word not in stop_words]
    
    # Добавляем полное название как ключевое слово
    keywords.append(title.lower())
    
    # Убираем дубликаты и возвращаем первые 10 ключевых слов
    return list(set(keywords))[:10]

# === Добавление фильма через меню (/addfilm) ===
@router.message(Command("addfilm"))
async def addfilm_start(message: Message):
    """Начинает процесс добавления фильма через пошаговое меню"""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Инициализируем состояние
    addfilm_state[message.from_user.id] = {
        'step': 'key',
        'data': {}
    }
    
    from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="addfilm_cancel_step")]
    ])
    
    await message.reply(
        "🎬 <b>Добавление фильма</b>\n\n"
        "🔑 Введите ключ фильма (латинские буквы, цифры и подчеркивания):\n"
        "<i>Например: avatar, avengers_endgame, matrix</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard
    )

# === Добавление сериала через меню (/addserial) ===
@router.message(Command("addserial"))
async def addserial_start(message: Message):
    """Начинает процесс добавления сериала через пошаговое меню"""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Инициализируем состояние
    addserial_state[message.from_user.id] = {
        'step': 'key',
        'data': {}
    }
    
    from keyboards import InlineKeyboardMarkup, InlineKeyboardButton
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="addserial_cancel_step")]
    ])
    
    await message.reply(
        "📺 <b>Добавление сериала</b>\n\n"
        "🔑 Введите ключ сериала (латинские буквы, цифры и подчеркивания):\n"
        "<i>Например: loki, breaking_bad, game_of_thrones</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard
    )

# === Добавление качества к фильму (/addka) ===
@router.message(Command("addka"))
async def addka_command(message: Message):
    """Добавление дополнительного качества к существующему фильму.
    Формат: /addka <movie_key> <file_id> <quality>
    Пример: /addka avatar BAADBAADqwADBREAAR4W9wABHg 720p
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []
    if len(args) < 3:
        help_text = (
            "<b>🎬 Добавление качества к фильму</b>\n\n"
            "<b>Формат:</b>\n"
            "<code>/addka &lt;movie_key&gt; &lt;file_id&gt; &lt;quality&gt;</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <code>movie_key</code> - ключ фильма в базе данных\n"
            "• <code>file_id</code> - Telegram file_id видео\n"
            "• <code>quality</code> - качество (720p, 480p, 4K и т.д.)\n\n"
            "<b>Пример:</b>\n"
            "<code>/addka avatar BAADBAADqwADBREAAR4W9wABHg 720p</code>\n\n"
            "<i>Команда добавляет дополнительное качество к уже существующему фильму.</i>"
        )
        await message.reply(help_text, parse_mode="HTML")
        return
    
    movie_key = args[0].strip()
    file_id = args[1].strip()
    quality = args[2].strip()
    
    # Проверяем, что фильм существует
    from db import movie_exists, add_movie_quality
    if not movie_exists(movie_key):
        await message.reply(f"❌ Фильм с ключом <code>{movie_key}</code> не найден в базе данных.", parse_mode="HTML")
        return
    
    # Определяем тип файла (по умолчанию video)
    file_type = "video"
    
    try:
        # Добавляем качество в базу данных
        success = add_movie_quality(movie_key, quality, file_id, file_type)
        
        if success:
            # Обновляем кэш после добавления качества
            from storage import _load_to_memory
            _load_to_memory()
            
            await message.reply(
                f"✅ <b>Качество добавлено!</b>\n\n"
                f"🎬 Фильм: <code>{movie_key}</code>\n"
                f"📱 Качество: <code>{quality}</code>\n"
                f"🆔 File ID: <code>{file_id[:20]}...</code>\n\n"
                f"🔄 Кэш автоматически обновлен",
                parse_mode="HTML"
            )
            logging.info(f"[ADDKA] Добавлено качество {quality} для фильма {movie_key}, кэш обновлен")
        else:
            await message.reply("❌ Ошибка при добавлении качества в базу данных.")
            
    except Exception as e:
        logging.error(f"[ADDKA] Ошибка при добавлении качества: {e}")
        await message.reply(f"❌ Ошибка: {e}")

# === Добавление качества к эпизоду (/addkaepisode) ===
@router.message(Command("addkaepisode"))
async def addkaepisode_command(message: Message):
    """Добавление дополнительного качества к существующему эпизоду.
    Формат: /addkaepisode <series_key> <season> <episode> <file_id> <quality>
    Пример: /addkaepisode loki 1 5 BAADBAADqwADBREAAR4W9wABHg 720p
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []
    if len(args) < 5:
        help_text = (
            "<b>📺 Добавление качества к эпизоду</b>\n\n"
            "<b>Формат:</b>\n"
            "<code>/addkaepisode &lt;series_key&gt; &lt;season&gt; &lt;episode&gt; &lt;file_id&gt; &lt;quality&gt;</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <code>series_key</code> - ключ сериала в базе данных\n"
            "• <code>season</code> - номер сезона\n"
            "• <code>episode</code> - номер эпизода\n"
            "• <code>file_id</code> - Telegram file_id видео\n"
            "• <code>quality</code> - качество (720p, 480p, 4K и т.д.)\n\n"
            "<b>Пример:</b>\n"
            "<code>/addkaepisode loki 1 5 BAADBAADqwADBREAAR4W9wABHg 720p</code>\n\n"
            "<i>Команда добавляет дополнительное качество к уже существующему эпизоду.</i>"
        )
        await message.reply(help_text, parse_mode="HTML")
        return
    
    series_key = args[0].strip()
    try:
        season = int(args[1].strip())
        episode = int(args[2].strip())
    except ValueError:
        await message.reply("❌ Номер сезона и эпизода должны быть числами.")
        return
    
    file_id = args[3].strip()
    quality = args[4].strip()
    
    # Проверяем, что эпизод существует
    if not episode_exists(series_key, season, episode):
        await message.reply(
            f"❌ Эпизод <code>{series_key}</code> S{season}E{episode} не найден в базе данных.", 
            parse_mode="HTML"
        )
        return
    
    # Определяем тип файла (по умолчанию video)
    file_type = "video"
    
    try:
        # Добавляем качество в базу данных
        success = add_episode_quality(series_key, season, episode, quality, file_id, file_type)
        
        if success:
            # Обновляем кэш после добавления качества
            from storage import _load_to_memory
            _load_to_memory()
            
            await message.reply(
                f"✅ <b>Качество добавлено!</b>\n\n"
                f"📺 Сериал: <code>{series_key}</code>\n"
                f"🎬 Эпизод: S{season}E{episode}\n"
                f"📱 Качество: <code>{quality}</code>\n"
                f"🆔 File ID: <code>{file_id[:20]}...</code>\n\n"
                f"🔄 Кэш автоматически обновлен",
                parse_mode="HTML"
            )
            logging.info(f"[ADDKAEPISODE] Добавлено качество {quality} для эпизода {series_key} S{season}E{episode}, кэш обновлен")
        else:
            await message.reply("❌ Ошибка при добавлении качества в базу данных.")
            
    except Exception as e:
        logging.error(f"[ADDKAEPISODE] Ошибка при добавлении качества: {e}")
        await message.reply(f"❌ Ошибка: {e}")

# === Обновление кэша (/reload_cache) ===
@router.message(Command("reload_cache"))
async def reload_cache_command(message: Message):
    """Принудительное обновление кэша фильмов и сериалов"""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    try:
        from storage import _load_to_memory
        _load_to_memory()
        await message.reply("✅ Кэш успешно обновлен!")
        logging.info("[RELOAD_CACHE] Кэш обновлен админом")
    except Exception as e:
        await message.reply(f"❌ Ошибка при обновлении кэша: {e}")
        logging.error(f"[RELOAD_CACHE] Ошибка: {e}")

# === Управление админами ===

@router.message(Command("addadmin"))
async def add_admin_command(message: Message):
    """Выдать админские права пользователю
    Формат: /addadmin <user_id> или ответить на сообщение пользователя
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для главного админа")
        return
    
    target_user_id = None
    target_user = None
    
    # Проверяем, есть ли ответ на сообщение
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
    else:
        # Парсим аргументы команды
        text = message.text or ""
        parts = text.split()
        
        if len(parts) < 2:
            await message.reply(
                "❌ <b>Неверный формат команды</b>\n\n"
                "<b>Использование:</b>\n"
                "• <code>/addadmin &lt;user_id&gt;</code>\n"
                "• Ответить на сообщение пользователя командой <code>/addadmin</code>\n\n"
                "<b>Пример:</b>\n"
                "<code>/addadmin 123456789</code>",
                parse_mode="HTML"
            )
            return
        
        try:
            target_user_id = int(parts[1])
        except ValueError:
            await message.reply("❌ User ID должен быть числом")
            return
    
    if target_user_id == message.from_user.id:
        await message.reply("❌ Нельзя выдать админку самому себе")
        return
    
    # Проверяем, не является ли пользователь уже админом
    from db import is_admin_in_db, add_admin
    if is_admin_in_db(target_user_id):
        await message.reply("❌ Пользователь уже является админом")
        return
    
    # Добавляем админа в базу данных
    username = target_user.username if target_user else None
    first_name = target_user.first_name if target_user else None
    last_name = target_user.last_name if target_user else None
    
    success = add_admin(
        user_id=target_user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        granted_by=message.from_user.id
    )
    
    if success:
        # Добавляем в список ADMIN_IDS для немедленного применения
        ADMIN_IDS.add(target_user_id)
        
        user_info = f"@{username}" if username else f"ID: {target_user_id}"
        if first_name:
            user_info += f" ({first_name}"
            if last_name:
                user_info += f" {last_name}"
            user_info += ")"
        
        await message.reply(
            f"✅ <b>Админские права выданы!</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_info}\n"
            f"🆔 <b>User ID:</b> <code>{target_user_id}</code>\n"
            f"👑 <b>Выдал:</b> @{message.from_user.username or 'admin'}\n"
            f"📅 <b>Дата:</b> {time.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"🔄 Права применены немедленно",
            parse_mode="HTML"
        )
        
        # Уведомляем нового админа
        try:
            await bot.send_message(
                target_user_id,
                f"🎉 <b>Поздравляем!</b>\n\n"
                f"Вам выданы админские права в боте!\n"
                f"👑 Выдал: @{message.from_user.username or 'admin'}\n\n"
                f"Теперь вы можете использовать админские команды.",
                parse_mode="HTML"
            )
        except Exception:
            pass  # Пользователь может не начать диалог с ботом
        
        logging.info(f"[ADD_ADMIN] {message.from_user.id} выдал админку пользователю {target_user_id}")
    else:
        await message.reply("❌ Ошибка при выдаче админских прав")


@router.message(Command("removeadmin"))
async def remove_admin_command(message: Message):
    """Забрать админские права у пользователя
    Формат: /removeadmin <user_id> или ответить на сообщение пользователя
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для главного админа")
        return
    
    target_user_id = None
    target_user = None
    
    # Проверяем, есть ли ответ на сообщение
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
    else:
        # Парсим аргументы команды
        text = message.text or ""
        parts = text.split()
        
        if len(parts) < 2:
            await message.reply(
                "❌ <b>Неверный формат команды</b>\n\n"
                "<b>Использование:</b>\n"
                "• <code>/removeadmin &lt;user_id&gt;</code>\n"
                "• Ответить на сообщение пользователя командой <code>/removeadmin</code>\n\n"
                "<b>Пример:</b>\n"
                "<code>/removeadmin 123456789</code>",
                parse_mode="HTML"
            )
            return
        
        try:
            target_user_id = int(parts[1])
        except ValueError:
            await message.reply("❌ User ID должен быть числом")
            return
    
    if target_user_id == message.from_user.id:
        await message.reply("❌ Нельзя забрать админку у самого себя")
        return
    
    # Проверяем, является ли пользователь админом
    from db import is_admin_in_db, remove_admin
    if not is_admin_in_db(target_user_id):
        await message.reply("❌ Пользователь не является админом")
        return
    
    # Удаляем админа из базы данных
    success = remove_admin(target_user_id)
    
    if success:
        # Удаляем из списка ADMIN_IDS для немедленного применения
        ADMIN_IDS.discard(target_user_id)
        
        user_info = f"@{target_user.username}" if target_user and target_user.username else f"ID: {target_user_id}"
        if target_user and target_user.first_name:
            user_info += f" ({target_user.first_name}"
            if target_user.last_name:
                user_info += f" {target_user.last_name}"
            user_info += ")"
        
        await message.reply(
            f"✅ <b>Админские права отозваны!</b>\n\n"
            f"👤 <b>Пользователь:</b> {user_info}\n"
            f"🆔 <b>User ID:</b> <code>{target_user_id}</code>\n"
            f"👑 <b>Отозвал:</b> @{message.from_user.username or 'admin'}\n"
            f"📅 <b>Дата:</b> {time.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"🔄 Права отозваны немедленно",
            parse_mode="HTML"
        )
        
        # Уведомляем бывшего админа
        try:
            await bot.send_message(
                target_user_id,
                f"⚠️ <b>Уведомление</b>\n\n"
                f"Ваши админские права в боте были отозваны.\n"
                f"👑 Отозвал: @{message.from_user.username or 'admin'}",
                parse_mode="HTML"
            )
        except Exception:
            pass
        
        logging.info(f"[REMOVE_ADMIN] {message.from_user.id} отозвал админку у пользователя {target_user_id}")
    else:
        await message.reply("❌ Ошибка при отзыве админских прав")


@router.message(Command("admins"))
async def list_admins_command(message: Message):
    """Показать список всех админов"""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    from db import get_all_admins
    admins = get_all_admins()
    
    if not admins:
        await message.reply("📋 Список админов пуст")
        return
    
    text = "👑 <b>Список админов</b>\n\n"
    
    for i, admin in enumerate(admins, 1):
        user_info = f"@{admin['username']}" if admin['username'] else f"ID: {admin['user_id']}"
        if admin['first_name']:
            user_info += f" ({admin['first_name']}"
            if admin['last_name']:
                user_info += f" {admin['last_name']}"
            user_info += ")"
        
        granted_date = admin['granted_at'].strftime('%d.%m.%Y %H:%M') if admin['granted_at'] else 'Неизвестно'
        
        text += f"{i}. {user_info}\n"
        text += f"   🆔 <code>{admin['user_id']}</code>\n"
        text += f"   📅 {granted_date}\n"
        if admin['granted_by']:
            text += f"   👑 Выдал: <code>{admin['granted_by']}</code>\n"
        text += "\n"
    
    text += f"📊 <b>Всего админов:</b> {len(admins)}"
    
    await message.reply(text, parse_mode="HTML")

# === Быстрое добавление эпизода (/addepisode) ===
@router.message(Command("addepisode"))
async def addepisode_quick(message: Message):
    """Быстрое добавление эпизода одной командой.
    Формат: /addepisode <show> <season> <episode> <file_id> [type]
    Пример: /addepisode rm 8 11 BAADBAADqwADBREAAR4W9wABHg video
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []
    if len(args) < 4:
        help_text = (
            "<b>📺 Быстрое добавление эпизода</b>\n\n"
            "<b>Формат:</b>\n"
            "<code>/addepisode &lt;show&gt; &lt;season&gt; &lt;episode&gt; &lt;file_id&gt; [type]</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <code>show</code> - ключ сериала (rm, phf, lbsc, irh, wnd, loki)\n"
            "• <code>season</code> - номер сезона\n"
            "• <code>episode</code> - номер эпизода\n"
            "• <code>file_id</code> - Telegram file_id видео\n"
            "• <code>type</code> - тип файла (video/document, по умолчанию video)\n\n"
            "<b>Пример:</b>\n"
            "<code>/addepisode rm 8 11 BAADBAADqwADBREAAR4W9wABHg video</code>"
        )
        await message.reply(help_text, parse_mode="HTML")
        return
    
    show = args[0].lower()
    try:
        season = int(args[1])
        episode = int(args[2])
    except ValueError:
        await message.reply("❌ Сезон и эпизод должны быть числами")
        return
    
    file_id = args[3]
    file_type = args[4] if len(args) > 4 else "video"
    
    # Проверяем существование сериала в базе данных
    from db import load_all_series
    try:
        all_series = load_all_series()
        valid_shows = {series['key'] for series in all_series}
        # Добавляем старые хардкодированные сериалы для обратной совместимости
        valid_shows.update({"rm", "phf", "lbsc", "irh", "wnd", "loki"})
        
        if show not in valid_shows:
            available_shows = ', '.join(sorted(valid_shows))
            await message.reply(f"❌ Неизвестный сериал '{show}'. Доступные: {available_shows}")
            return
    except Exception as e:
        logging.exception(f"[addepisode] Ошибка при проверке сериалов: {e}")
        # Fallback к старым сериалам
        valid_shows = {"rm", "phf", "lbsc", "irh", "wnd", "loki"}
        if show not in valid_shows:
            await message.reply(f"❌ Неизвестный сериал. Доступные: {', '.join(valid_shows)}")
            return
    
    try:
        from db import bulk_upsert_episodes
        from storage import _load_to_memory
        
        logging.info(f"[addepisode] Добавляем эпизод: show={show}, season={season}, episode={episode}, file_id={file_id}, type={file_type}")
        
        # Добавляем эпизод в БД
        bulk_upsert_episodes([(show, season, episode, file_id, file_type)])
        logging.info(f"[addepisode] Эпизод успешно добавлен в БД")
        
        # Проверяем и обновляем количество эпизодов в сезоне
        from db import load_all_episodes, upsert_season_counts
        
        # Подсчитываем фактическое количество эпизодов для данного сезона
        all_episodes = load_all_episodes()
        episodes_in_season = []
        for ep in all_episodes:
            if ep['show'] == show and ep['season'] == season:
                episodes_in_season.append(ep['episode'])
        
        # Обновляем счетчик сезона (используем фактическое количество эпизодов)
        episodes_count = len(episodes_in_season)
        if episodes_count > 0:
            upsert_season_counts([(show, season, episodes_count)])
            logging.info(f"[addepisode] Обновлен счетчик сезона: {show} сезон {season} = {episodes_count} эпизодов (эпизоды: {sorted(episodes_in_season)})")
        
        # Обновляем кэш в памяти
        _load_to_memory()
        logging.info(f"[addepisode] Кэш в памяти обновлен")
        
        # Проверяем, что эпизод действительно добавлен
        # Все серии теперь загружаются из базы данных через show_series_navigation
        
        episode_found = False
        season_count = 0
        
        # Проверяем в соответствующих структурах данных
        # Проверяем через базу данных
        from db import load_all_episodes, load_all_seasons
        try:
            episodes = load_all_episodes(show)
            seasons = load_all_seasons(show)
            
            # Проверяем существование серии
            episode_found = any(ep['season'] == season and ep['episode'] == episode for ep in episodes)
            season_count = len([s for s in seasons if s['season'] == season])
            if season_count == 0 and episodes:
                # Если сезонов нет в таблице seasons, считаем по эпизодам
                season_episodes = [ep for ep in episodes if ep['season'] == season]
                season_count = len(season_episodes)
        except Exception as e:
            logging.error(f"Ошибка при проверке серии {show} {season}x{episode}: {e}")
            episode_found = False
            season_count = 0
        except Exception as e:
            logging.error(f"Ошибка при загрузке данных из базы для {show}: {e}")
            await query.answer([], cache_time=1, is_personal=True)
            return
        else:
            # Для новых сериалов проверяем в базе данных
            try:
                from db import get_conn
                import psycopg2
                conn = get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT COUNT(*) FROM episodes WHERE show = %s AND season = %s AND episode = %s",
                            (show, season, episode)
                        )
                        if cur.fetchone()[0] > 0:
                            episode_found = True
                            # Получаем количество эпизодов в сезоне
                            cur.execute(
                                "SELECT episodes_count FROM seasons WHERE show = %s AND season = %s",
                                (show, season)
                            )
                            result = cur.fetchone()
                            season_count = result[0] if result else episodes_count
                finally:
                    conn.close()
            except Exception as db_e:
                logging.exception(f"[addepisode] Ошибка при проверке эпизода в БД: {db_e}")
                episode_found = True  # Предполагаем успех если не можем проверить
        
        # Получаем информацию о сериале для отображения
        series_title = show.upper()
        try:
            all_series = load_all_series()
            for series in all_series:
                if series['key'] == show:
                    series_title = series['title']
                    break
        except Exception:
            pass
        
        if episode_found:
            await message.reply(
                f"✅ Эпизод успешно добавлен:\n"
                f"📺 Сериал: <b>{series_title}</b> ({show})\n"
                f"📅 Сезон: <b>{season}</b> (всего эпизодов: <b>{season_count}</b>)\n"
                f"🎬 Эпизод: <b>{episode}</b>\n"
                f"📁 Тип: <b>{file_type}</b>\n\n"
                f"🔍 Эпизод готов к использованию!\n"
                f"📊 Счетчик сезона обновлен автоматически.",
                parse_mode="HTML"
            )
        else:
            await message.reply(
                f"⚠️ Эпизод добавлен в БД:\n"
                f"📺 Сериал: <b>{series_title}</b> ({show})\n"
                f"📅 Сезон: <b>{season}</b>\n"
                f"🎬 Эпизод: <b>{episode}</b>\n"
                f"📁 Тип: <b>{file_type}</b>\n\n"
                f"✨ Для новых сериалов эпизоды будут доступны после перезапуска бота.",
                parse_mode="HTML"
            )
        
    except Exception as e:
        logging.exception(f"[addepisode] Ошибка при добавлении эпизода: {e}")
        await message.reply(f"❌ Ошибка при добавлении эпизода: {e}")

# === Быстрое добавление сезона (/addseason) ===
@router.message(Command("addseason"))
async def addseason_quick(message: Message):
    """Быстрое добавление информации о сезоне.
    Формат: /addseason <show> <season> <episodes_count>
    Пример: /addseason rm 8 10
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []
    if len(args) < 3:
        help_text = (
            "<b>📺 Быстрое добавление сезона</b>\n\n"
            "<b>Формат:</b>\n"
            "<code>/addseason &lt;show&gt; &lt;season&gt; &lt;episodes_count&gt;</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <code>show</code> - ключ сериала (rm, phf, lbsc, irh, wnd, loki)\n"
            "• <code>season</code> - номер сезона\n"
            "• <code>episodes_count</code> - количество эпизодов в сезоне\n\n"
            "<b>Пример:</b>\n"
            "<code>/addseason rm 8 10</code>"
        )
        await message.reply(help_text, parse_mode="HTML")
        return
    
    show = args[0].lower()
    try:
        season = int(args[1])
        episodes_count = int(args[2])
    except ValueError:
        await message.reply("❌ Сезон и количество эпизодов должны быть числами")
        return
    
    # Проверяем валидность show
    valid_shows = {"rm", "phf", "lbsc", "irh", "wnd", "loki"}
    if show not in valid_shows:
        await message.reply(f"❌ Неизвестный сериал. Доступные: {', '.join(valid_shows)}")
        return
    
    try:
        from db import upsert_season_counts
        from storage import _load_to_memory
        
        # Добавляем информацию о сезоне в БД
        upsert_season_counts([(show, season, episodes_count)])
        
        # Обновляем кэш в памяти
        _load_to_memory()
        
        await message.reply(
            f"✅ Сезон добавлен:\n"
            f"📺 Сериал: <b>{show}</b>\n"
            f"📅 Сезон: <b>{season}</b>\n"
            f"🎬 Эпизодов: <b>{episodes_count}</b>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при добавлении сезона: {e}")

# === Редактирование эпизода (/addizm) ===
@router.message(Command("addizm"))
async def edit_episode(message: Message):
    """Редактирование file_id существующего эпизода.
    Формат: /addizm <show> <season> <episode> <new_file_id> [type]
    Пример: /addizm phf 5 9 BAADBAADqwADBREAAR4W9wABHg video
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []
    if len(args) < 4:
        help_text = (
            "<b>✏️ Редактирование эпизода</b>\n\n"
            "<b>Формат:</b>\n"
            "<code>/addizm &lt;show&gt; &lt;season&gt; &lt;episode&gt; &lt;new_file_id&gt; [type]</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <code>show</code> - ключ сериала (rm, phf, lbsc, irh, wnd, loki)\n"
            "• <code>season</code> - номер сезона\n"
            "• <code>episode</code> - номер эпизода\n"
            "• <code>new_file_id</code> - новый Telegram file_id\n"
            "• <code>type</code> - тип файла (video/document, по умолчанию video)\n\n"
            "<b>Пример:</b>\n"
            "<code>/addizm phf 5 9 BAADBAADqwADBREAAR4W9wABHg video</code>"
        )
        await message.reply(help_text, parse_mode="HTML")
        return
    
    show = args[0].lower()
    try:
        season = int(args[1])
        episode = int(args[2])
    except ValueError:
        await message.reply("❌ Сезон и эпизод должны быть числами")
        return
    
    new_file_id = args[3]
    file_type = args[4] if len(args) > 4 else "video"
    
    # Проверяем валидность show
    valid_shows = {"rm", "phf", "lbsc", "irh", "wnd", "loki"}
    if show not in valid_shows:
        await message.reply(f"❌ Неизвестный сериал. Доступные: {', '.join(valid_shows)}")
        return
    
    try:
        from db import bulk_upsert_episodes
        from storage import _load_to_memory
        import psycopg2
        from config import DATABASE_URL
        
        # Проверяем, существует ли эпизод
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT file_id FROM episodes WHERE show = %s AND season = %s AND episode = %s",
                    (show, season, episode)
                )
                existing = cur.fetchone()
                
                if not existing:
                    await message.reply(
                        f"❌ Эпизод {show.upper()} S{season}E{episode} не найден в базе данных.\n"
                        f"Используйте /addepisode для добавления нового эпизода."
                    )
                    return
                
                old_file_id = existing[0]
        finally:
            conn.close()
        
        # Обновляем эпизод в БД
        bulk_upsert_episodes([(show, season, episode, new_file_id, file_type)])
        
        # Обновляем кэш в памяти
        _load_to_memory()
        
        await message.reply(
            f"✅ Эпизод обновлен:\n"
            f"📺 Сериал: <b>{show.upper()}</b>\n"
            f"📅 Сезон: <b>{season}</b>\n"
            f"🎬 Эпизод: <b>{episode}</b>\n"
            f"📁 Тип: <b>{file_type}</b>\n\n"
            f"🔄 Старый file_id: <code>{old_file_id[:30]}...</code>\n"
            f"🆕 Новый file_id: <code>{new_file_id[:30]}...</code>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при обновлении эпизода: {e}")

# === Редактирование фильма (/addizmfilm) ===
@router.message(Command("addizmfilm"))
async def edit_movie(message: Message):
    """Редактирование file_id существующего фильма.
    Формат: /addizmfilm <movie_key> <new_file_id> [type]
    Пример: /addizmfilm avatar_2009 BAADBAADqwADBREAAR4W9wABHg video
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []
    if len(args) < 2:
        help_text = (
            "<b>✏️ Редактирование фильма</b>\n\n"
            "<b>Формат:</b>\n"
            "<code>/addizmfilm &lt;movie_key&gt; &lt;new_file_id&gt; [type]</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <code>movie_key</code> - ключ фильма в базе данных\n"
            "• <code>new_file_id</code> - новый Telegram file_id\n"
            "• <code>type</code> - тип файла (video/document, по умолчанию video)\n\n"
            "<b>Пример:</b>\n"
            "<code>/addizmfilm avatar_2009 BAADBAADqwADBREAAR4W9wABHg video</code>"
        )
        await message.reply(help_text, parse_mode="HTML")
        return
    
    movie_key = args[0]
    new_file_id = args[1]
    file_type = args[2] if len(args) > 2 else "video"
    
    try:
        import psycopg2
        from config import DATABASE_URL
        from storage import _load_to_memory
        
        # Проверяем, существует ли фильм
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT file_id FROM movies WHERE key = %s",
                    (movie_key,)
                )
                existing = cur.fetchone()
                
                if not existing:
                    await message.reply(
                        f"❌ Фильм с ключом '{movie_key}' не найден в базе данных.\n"
                        f"Используйте /addmovie для добавления нового фильма."
                    )
                    return
                
                old_file_id = existing[0]
                
                # Обновляем file_id и type фильма
                cur.execute(
                    "UPDATE movies SET file_id = %s, type = %s WHERE key = %s",
                    (new_file_id, file_type, movie_key)
                )
                conn.commit()
                
        finally:
            conn.close()
        
        # Обновляем кэш в памяти
        _load_to_memory()
        
        await message.reply(
            f"✅ Фильм обновлен:\n"
            f"🎬 Ключ: <b>{movie_key}</b>\n"
            f"📁 Тип: <b>{file_type}</b>\n\n"
            f"🔄 Старый file_id: <code>{old_file_id[:30]}...</code>\n"
            f"🆕 Новый file_id: <code>{new_file_id[:30]}...</code>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при обновлении фильма: {e}")

# === Массовое добавление эпизодов (/addepisodes) ===
@router.message(Command("addepisodes"))
async def addepisodes_bulk(message: Message):
    """Массовое добавление эпизодов одной командой.
    Формат: /addepisodes <show> <season> <start_episode>-<end_episode> <file_id1,file_id2,...> [type]
    Пример: /addepisodes rm 8 1-3 file1,file2,file3 video
    """
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Парсим аргументы команды
    args = message.text.split()[1:] if message.text else []
    if len(args) < 4:
        help_text = (
            "<b>📺 Массовое добавление эпизодов</b>\n\n"
            "<b>Формат:</b>\n"
            "<code>/addepisodes &lt;show&gt; &lt;season&gt; &lt;start&gt;-&lt;end&gt; &lt;file_ids&gt; [type]</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <code>show</code> - ключ сериала (rm, phf, lbsc, irh, wnd, loki)\n"
            "• <code>season</code> - номер сезона\n"
            "• <code>start-end</code> - диапазон эпизодов (например: 1-5)\n"
            "• <code>file_ids</code> - file_id через запятую\n"
            "• <code>type</code> - тип файла (video/document, по умолчанию video)\n\n"
            "<b>Пример:</b>\n"
            "<code>/addepisodes rm 8 1-3 file1,file2,file3 video</code>"
        )
        await message.reply(help_text, parse_mode="HTML")
        return
    
    show = args[0].lower()
    try:
        season = int(args[1])
    except ValueError:
        await message.reply("❌ Сезон должен быть числом")
        return
    
    # Парсим диапазон эпизодов
    episode_range = args[2]
    if '-' not in episode_range:
        await message.reply("❌ Неверный формат диапазона. Используйте: start-end (например: 1-5)")
        return
    
    try:
        start_ep, end_ep = map(int, episode_range.split('-'))
    except ValueError:
        await message.reply("❌ Неверный формат диапазона эпизодов")
        return
    
    # Парсим file_id
    file_ids = args[3].split(',')
    file_type = args[4] if len(args) > 4 else "video"
    
    # Проверяем соответствие количества
    expected_count = end_ep - start_ep + 1
    if len(file_ids) != expected_count:
        await message.reply(
            f"❌ Количество file_id ({len(file_ids)}) не соответствует "
            f"количеству эпизодов ({expected_count})"
        )
        return
    
    # Проверяем валидность show
    valid_shows = {"rm", "phf", "lbsc", "irh", "wnd", "loki"}
    if show not in valid_shows:
        await message.reply(f"❌ Неизвестный сериал. Доступные: {', '.join(valid_shows)}")
        return
    
    try:
        from db import bulk_upsert_episodes, upsert_season_counts
        from storage import _load_to_memory
        
        # Подготавливаем данные для вставки
        episodes_data = []
        for i, file_id in enumerate(file_ids):
            episode_num = start_ep + i
            episodes_data.append((show, season, episode_num, file_id.strip(), file_type))
        
        # Добавляем эпизоды в БД
        bulk_upsert_episodes(episodes_data)
        
        # Обновляем информацию о сезоне
        upsert_season_counts([(show, season, end_ep)])
        
        # Обновляем кэш в памяти
        _load_to_memory()
        
        await message.reply(
            f"✅ Добавлено {len(episodes_data)} эпизодов:\n"
            f"📺 Сериал: <b>{show}</b>\n"
            f"📅 Сезон: <b>{season}</b>\n"
            f"🎬 Эпизоды: <b>{start_ep}-{end_ep}</b>\n"
            f"📁 Тип: <b>{file_type}</b>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        await message.reply(f"❌ Ошибка при добавлении эпизодов: {e}")

# === Обновление статистики по кнопке (обрабатываем в общем callback-хендлере) ===

@router.message(Command("broadcast"))
async def broadcast(message: Message):
    logging.info(f"User {message.from_user.id} tried to use /broadcast command.")
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ У вас нет доступа к этой команде.")
        return
    
    # Инициализируем состояние рассылки
    broadcast_state[message.from_user.id] = {
        "step": "content",
        "media_group": [],
        "selected_buttons": set(),
        "button_configs": []
    }
    
    text = (
        "<b>🚀 Создание рассылки</b>\n\n"
        "📤 <b>Отправьте любой контент для рассылки:</b>\n\n"
        "📝 • Текстовое сообщение\n"
        "🖼 • Фото (одно или несколько)\n"
        "🎥 • Видео (одно или несколько)\n"
        "📄 • Документы\n"
        "🎵 • Аудио\n"
        "🎤 • Голосовые сообщения\n"
        "📍 • Геолокация\n"
        "📞 • Контакты\n"
        "🎲 • Стикеры\n"
        "🎮 • GIF анимации\n\n"
        "💡 <b>Возможности:</b>\n"
        "• Отправляйте медиа по одному или альбомом\n"
        "• Добавляйте подписи к медиафайлам\n"
        "• Создавайте URL кнопки\n"
        "• Полный предпросмотр перед отправкой\n\n"
        "<i>После отправки контента вы сможете добавить кнопки и отправить рассылку.</i>"
    )
    
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    await message.reply(text, parse_mode="HTML", reply_markup=cancel_keyboard)

# Добавляю сохранение user_id при любом взаимодействии
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Message, CallbackQuery

class SaveUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = str(event.from_user.id)
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = str(event.from_user.id)
        if user_id:
            # Сохраняем пользователя в базу данных
            from db import save_user
            try:
                if isinstance(event, Message):
                    save_user(
                        user_id=int(user_id),
                        username=event.from_user.username,
                        first_name=event.from_user.first_name,
                        last_name=event.from_user.last_name,
                        language_code=event.from_user.language_code,
                        is_bot=event.from_user.is_bot
                    )
                elif isinstance(event, CallbackQuery):
                    optimized_save_user(
                        int(user_id),
                        event.from_user.username,
                        event.from_user.first_name,
                        event.from_user.last_name,
                        event.from_user.language_code,
                        event.from_user.is_bot
                    )
            except Exception:
                pass
        return await handler(event, data)

@router.callback_query()
async def handle_callback(callback: CallbackQuery):
    data = callback.data
    user_id = str(callback.from_user.id)
    user_id_int = int(user_id)
    
    # Оптимизированное сохранение пользователя (раз в 5 минут)
    try:
        optimized_save_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
            callback.from_user.last_name,
            callback.from_user.language_code,
            callback.from_user.is_bot
        )
    except Exception:
        pass
    
    # Проверка подписки для всех действий (кроме самой кнопки проверки подписки, кнопки "Убрать рекламу", админов и премиум пользователей)
    if data not in ["check_subscription", "ref_system"] and user_id_int not in ADMIN_IDS and not is_premium_user(user_id_int):
        if not await check_subscription(user_id_int):
            text, keyboard = get_subscription_message(user_id_int)
            try:
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
            except Exception:
                await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer("⚠️ Необходима подписка на канал", show_alert=True)
            return
    
    # Обработка кнопки "Проверить подписку"
    if data == "check_subscription":
        if await check_subscription(user_id_int):
            # Сохраняем пользователя в БД после успешной подписки
            save_user(
                user_id=user_id_int,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
                last_name=callback.from_user.last_name,
                language_code=callback.from_user.language_code
            )
            
            await callback.answer("✅ Вы подписаны! Добро пожаловать!", show_alert=True)
            
            # Проверяем премиум статус
            is_premium = is_premium_user(user_id_int)
            premium_status = "<b>Вы являетесь премиум пользователем</b>" if is_premium else "<b>Вы не являетесь премиум пользователем</b>"
            
            # Показываем главное меню
            text = (
                "Привет!👋\n\n"
                "<i>Ты попал в кино-бот!</i> <b>У нас большая коллекция фильмов и сериалов на любой вкус!</b>🎥\n\n"
                f"{premium_status}\n\n"
                "<b><i>Что бы ознакомиться с ботом, нажми /help либо \"Помощь\".</i></b>\n\n"
                "Нажми на \"Начать поиск\" и приятного тебе <b>просмотра!</b>"
            )
            try:
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())
            except Exception:
                await callback.message.answer(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())
        else:
            await callback.answer("❌ Вы еще не подписаны на канал", show_alert=True)
        return
    
    # Обработчики кнопок обновления лимитов
    if data == "refresh_movie_limit":
        from db import get_user_daily_content_count, get_time_until_limit_reset
        user_id_int = int(user_id)
        
        daily_content = get_user_daily_content_count(user_id_int)
        
        # Админы и премиум пользователи не имеют лимитов
        if user_id_int in ADMIN_IDS or is_premium_user(user_id_int) or daily_content <= DAILY_CONTENT_LIMIT:
            await callback.answer("✅ Лимит снят! Вы можете продолжить просмотр.", show_alert=True)
            try:
                await callback.message.delete()
            except Exception:
                pass
        else:
            time_remaining = get_time_until_limit_reset(user_id_int, 'movie')
            time_str = format_time_remaining(time_remaining)
            
            limit_text = (
                "ЛИМИТ НА КОНТЕНТ В ДЕНЬ!\n\n"
                f"⏰ Лимит будет снят через {time_str}\n\n"
                f"Обычные пользователи без премиум статуса могут просматривать лишь {DAILY_CONTENT_LIMIT} контента за 24 часа.\n\n"
                "Что бы получить премиум статус нужно пригласить всего 2 друга по вашей собственной реферальной ссылке: /ref"
            )
            
            keyboard = get_movie_limit_keyboard(user_id_int)
            
            try:
                await callback.message.edit_text(
                    text=limit_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения: {e}")
            
            await callback.answer(f"🔄 Обновлено. Осталось: {time_str}")
        return
    
    if data == "refresh_episode_limit":
        from db import get_user_daily_content_count, get_time_until_limit_reset
        user_id_int = int(user_id)
        
        daily_content = get_user_daily_content_count(user_id_int)
        
        # Админы и премиум пользователи не имеют лимитов
        if user_id_int in ADMIN_IDS or is_premium_user(user_id_int) or daily_content <= DAILY_CONTENT_LIMIT:
            await callback.answer("✅ Лимит снят! Вы можете продолжить просмотр.", show_alert=True)
            try:
                await callback.message.delete()
            except Exception:
                pass
        else:
            time_remaining = get_time_until_limit_reset(user_id_int, 'movie')
            time_str = format_time_remaining(time_remaining)
            
            limit_text = (
                f"Упс... Кажется вы исчерпали свой лимит в {DAILY_CONTENT_LIMIT} контента за 24 часа.\n\n"
                f"⏰ Лимит будет снят через: {time_str}\n\n"
                f"У обычных пользователей без премиум-статус лимит на {DAILY_CONTENT_LIMIT} контента за 24 часа. "
                "Что бы получить премиум статус вам нужно пригласить двух людей в бот по вашей собственной реферальной ссылке: /ref"
            )
            
            keyboard = get_episode_limit_keyboard(user_id_int)
            
            try:
                await callback.message.edit_text(
                    text=limit_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения: {e}")
            
            await callback.answer(f"🔄 Обновлено. Осталось: {time_str}")
        return
    
    if data == "refresh_content_limit":
        from db import get_user_daily_content_count, get_time_until_limit_reset
        user_id_int = int(user_id)
        
        daily_content = get_user_daily_content_count(user_id_int)
        
        # Админы и премиум пользователи не имеют лимитов
        if user_id_int in ADMIN_IDS or is_premium_user(user_id_int) or daily_content <= DAILY_CONTENT_LIMIT:
            await callback.answer("✅ Лимит снят! Вы можете продолжить просмотр.", show_alert=True)
            try:
                await callback.message.delete()
            except Exception:
                pass
        else:
            time_remaining = get_time_until_limit_reset(user_id_int, 'movie')
            time_str = format_time_remaining(time_remaining)
            
            limit_text = (
                f"Упс... Кажется вы исчерпали свой лимит в {DAILY_CONTENT_LIMIT} контента за 24 часа.\n\n"
                f"⏰ Лимит будет снят через: {time_str}\n\n"
                f"У обычных пользователей без премиум-статус лимит на {DAILY_CONTENT_LIMIT} контента за 24 часа. "
                "Что бы получить премиум статус вам нужно пригласить двух людей в бот по вашей собственной реферальной ссылке: /ref"
            )
            
            keyboard = get_episode_limit_keyboard(user_id_int)
            
            try:
                await callback.message.edit_text(
                    text=limit_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except Exception as e:
                logging.error(f"Ошибка обновления сообщения: {e}")
            
            await callback.answer(f"🔄 Обновлено. Осталось: {time_str}")
        return
    
    # Обработчик кнопки "Смотреть в боте" для фильмов
    if data.startswith("movie_play_"):
        movie_key = data.replace("movie_play_", "")
        from storage import MOVIES
        from db import should_show_ad, increment_movie_view, get_user_daily_movies_count, get_time_until_limit_reset
        import time
        
        meta = MOVIES.get(movie_key)
        user_id_int = int(user_id)
        
        logging.info(f"[MOVIE_PLAY] Запрос фильма: {movie_key}, user: {user_id}")
        
        if not meta:
            logging.warning(f"[MOVIE_PLAY] Фильм не найден: {movie_key}")
            await callback.answer("❌ Фильм не найден", show_alert=True)
            return
        
        # ПРОВЕРКА ЕДИНОГО ЛИМИТА ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ
        if user_id_int not in ADMIN_IDS and not is_premium_user(user_id_int):
            daily_content = get_user_daily_content_count(user_id_int)
            logging.info(f"[MOVIE_PLAY] Пользователь {user_id} просмотрел {daily_content} контента за 24 часа")
            
            if daily_content > DAILY_CONTENT_LIMIT:
                # Пользователь достиг лимита
                time_remaining = get_time_until_limit_reset(user_id_int, 'movie')
                time_str = format_time_remaining(time_remaining)
                
                limit_text = (
                    "ЛИМИТ НА КОНТЕНТ В ДЕНЬ!\n\n"
                    f"⏰ Лимит будет снят через {time_str}\n\n"
                    f"Обычные пользователи без премиум статуса могут просматривать лишь {DAILY_CONTENT_LIMIT} контента за 24 часа.\n\n"
                    "Что бы получить премиум статус нужно пригласить всего 2 друга по вашей собственной реферальной ссылке: /ref"
                )
                
                keyboard = get_movie_limit_keyboard(user_id_int)
                
                try:
                    await bot.send_message(
                        chat_id=callback.message.chat.id,
                        text=limit_text,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки сообщения о лимите: {e}")
                
                await callback.answer("⛔️ Достигнут лимит на контент за 24 часа!", show_alert=True)
                return
        
        try:
            file_id = meta.get('file_id')
            if not file_id:
                logging.error(f"[MOVIE_PLAY] Отсутствует file_id для фильма: {movie_key}")
                await callback.answer("❌ Файл фильма не найден в базе данных", show_alert=True)
                return
            
            # Проверяем валидность file_id
            if not _is_valid_file_id(file_id):
                logging.error(f"[MOVIE_PLAY] Невалидный file_id для фильма: {movie_key}")
                await callback.answer("❌ Файл фильма поврежден или недоступен", show_alert=True)
                return
            
            # РЕКЛАМА ОТКЛЮЧЕНА
            # if should_show_ad(user_id_int, ad_frequency=2):
            #     # Код рекламы закомментирован
            #     pass
            
            logging.info(f"[MOVIE_PLAY] Отправка фильма {movie_key}, type: {meta.get('type')}, file_id: {file_id[:20]}...")
            
            # Проверяем, добавлен ли фильм в избранное
            from db import is_in_favorites
            is_favorited = is_in_favorites(user_id, 'movie', movie_key)
            
            # Создаем кнопку в зависимости от статуса избранного
            if is_favorited:
                fav_button = InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{movie_key}")
            else:
                fav_button = InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"fav_{movie_key}")
            
            # Отправляем видео фильма без ответа на сообщение
            caption = f"<b>{meta['title']}</b>\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"
            
            # Проверяем доступные качества для фильма
            from db import get_movie_qualities
            qualities = get_movie_qualities(movie_key)
            
            # Создаем клавиатуру с кнопками
            keyboard_buttons = []
            
            # Всегда добавляем кнопку качества
            current_quality = meta.get('quality', '1080p')
            if len(qualities) > 1:
                # Если есть несколько качеств - кнопка активна
                keyboard_buttons.append([InlineKeyboardButton(text=f"📱 Качество: {current_quality}", callback_data=f"quality_select_{movie_key}")])
            else:
                # Если только одно качество - показываем информативную кнопку
                keyboard_buttons.append([InlineKeyboardButton(text=f"📱 Качество: {current_quality}", callback_data=f"quality_info_{movie_key}")])
            
            keyboard_buttons.append([fav_button])
            keyboard_buttons.append([InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            if meta.get('type') == 'video':
                try:
                    await bot.send_video(
                        chat_id=callback.message.chat.id,
                        video=file_id,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                except Exception as video_error:
                    logging.error(f"[MOVIE_PLAY] Ошибка отправки видео {movie_key}: {video_error}")
                    # Пытаемся отправить как документ в случае ошибки с видео
                    try:
                        await bot.send_document(
                            chat_id=callback.message.chat.id,
                            document=file_id,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=keyboard
                        )
                    except Exception as doc_error:
                        logging.error(f"[MOVIE_PLAY] Ошибка отправки документа {movie_key}: {doc_error}")
                        await callback.answer("❌ Файл фильма недоступен или поврежден. Попробуйте позже.", show_alert=True)
                        return
            else:
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            
            logging.info(f"[MOVIE_PLAY] Фильм {movie_key} успешно отправлен")
            
            # Добавляем просмотр в статистику (ТОЛЬКО ОДИН РАЗ!)
            try:
                from db import add_content_view
                add_content_view(user_id_int, 'movie', movie_key)
            except Exception as e:
                logging.error(f"Ошибка при добавлении просмотра фильма {movie_key}: {e}")
            
            await callback.answer("🎬 Фильм отправлен!")
            
        except Exception as e:
            logging.error(f"[MOVIE_PLAY] Ошибка отправки фильма {movie_key}: {e}", exc_info=True)
            await callback.answer("❌ Ошибка при отправке фильма", show_alert=True)
        
        return
    
    # Обработчик кнопки выбора качества фильма
    if data.startswith("quality_select_"):
        movie_key = data.replace("quality_select_", "")
        logging.info(f"[QUALITY_SELECT] movie_key='{movie_key}'")
        
        from storage import MOVIES
        from db import get_movie_qualities
        
        # Проверяем права доступа
        if user_id not in ADMIN_IDS:
            # Для обычных пользователей показываем все доступные качества
            pass
        
        meta = MOVIES.get(movie_key)
        if not meta:
            # Попробуем обновить кэш и проверить снова
            try:
                from storage import _load_to_memory
                _load_to_memory()
                meta = MOVIES.get(movie_key)
            except Exception as e:
                logging.error(f"[QUALITY_SELECT] Ошибка обновления кэша: {e}")
        
        if not meta:
            logging.error(f"[QUALITY_SELECT] Фильм '{movie_key}' не найден в кэше. Доступные ключи: {list(MOVIES.keys())[:10]}")
            await callback.answer("❌ Фильм не найден в кэше", show_alert=True)
            return
        
        # Получаем все доступные качества
        qualities = get_movie_qualities(movie_key)
        logging.info(f"[QUALITY_SELECT] Найдено качеств для '{movie_key}': {len(qualities)} - {[q['quality'] for q in qualities]}")
        
        if len(qualities) <= 1:
            await callback.answer("❌ Для этого фильма доступно только одно качество", show_alert=True)
            return
        
        # Создаем клавиатуру с выбором качества
        quality_buttons = []
        for quality_info in qualities:
            quality = quality_info['quality']
            # Отмечаем текущее качество
            current_quality = meta.get('quality', '1080p')
            if quality == current_quality:
                button_text = f"✅ {quality}"
            else:
                button_text = f"📱 {quality}"
            
            quality_buttons.append([InlineKeyboardButton(
                text=button_text, 
                callback_data=f"quality_change_{movie_key}_{quality}"
            )])
        
        # Добавляем кнопку "Назад"
        quality_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"movie_play_{movie_key}")])
        
        quality_keyboard = InlineKeyboardMarkup(inline_keyboard=quality_buttons)
        
        try:
            await callback.message.edit_reply_markup(reply_markup=quality_keyboard)
            await callback.answer("📱 Выберите качество")
        except Exception as e:
            logging.error(f"Error updating quality menu: {e}")
            await callback.answer("❌ Ошибка при обновлении меню")
        
        return
    
    # Обработчик изменения качества фильма
    if data.startswith("quality_change_"):
        # Более надежный парсинг: убираем префикс и разделяем по последнему _
        data_without_prefix = data.replace("quality_change_", "")
        
        # Находим последнее подчеркивание (это разделитель между ключом и качеством)
        last_underscore = data_without_prefix.rfind("_")
        if last_underscore == -1:
            await callback.answer("❌ Неверный формат данных", show_alert=True)
            return
        
        movie_key = data_without_prefix[:last_underscore]
        selected_quality = data_without_prefix[last_underscore + 1:]
        
        logging.info(f"[QUALITY_CHANGE] movie_key='{movie_key}', quality='{selected_quality}'")
        
        from storage import MOVIES
        from db import get_movie_quality_file_id
        
        meta = MOVIES.get(movie_key)
        if not meta:
            # Попробуем обновить кэш и проверить снова
            try:
                from storage import _load_to_memory
                _load_to_memory()
                meta = MOVIES.get(movie_key)
            except Exception as e:
                logging.error(f"[QUALITY_CHANGE] Ошибка обновления кэша: {e}")
        
        if not meta:
            logging.error(f"[QUALITY_CHANGE] Фильм '{movie_key}' не найден в кэше. Доступные ключи: {list(MOVIES.keys())[:10]}")
            await callback.answer("❌ Фильм не найден в кэше", show_alert=True)
            return
        
        # Получаем file_id для выбранного качества
        quality_file_id = get_movie_quality_file_id(movie_key, selected_quality)
        if not quality_file_id:
            logging.error(f"[QUALITY_CHANGE] Файл для качества '{selected_quality}' фильма '{movie_key}' не найден")
            await callback.answer("❌ Файл для выбранного качества не найден", show_alert=True)
            return
        
        # Обновляем мета-информацию в кэше
        MOVIES[movie_key]['quality'] = selected_quality
        MOVIES[movie_key]['file_id'] = quality_file_id
        
        logging.info(f"[QUALITY_CHANGE] Обновлен кэш для '{movie_key}': качество={selected_quality}, file_id={quality_file_id[:20]}...")
        
        # Возвращаемся к исходному меню фильма с обновленным качеством
        await callback.answer(f"✅ Выбрано качество: {selected_quality}")
        
        # Обновляем существующее сообщение с новым качеством
        try:
            from db import is_in_favorites
            is_favorited = is_in_favorites(user_id, 'movie', movie_key)
            
            # Создаем кнопку в зависимости от статуса избранного
            if is_favorited:
                fav_button = InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{movie_key}")
            else:
                fav_button = InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"fav_{movie_key}")
            
            # Обновляем подпись с новым качеством
            caption = f"<b>{meta['title']}</b>\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"
            
            # Проверяем доступные качества для фильма
            from db import get_movie_qualities
            qualities = get_movie_qualities(movie_key)
            
            # Создаем клавиатуру с кнопками
            keyboard_buttons = []
            
            # Всегда добавляем кнопку качества с обновленным значением
            current_quality = selected_quality
            if len(qualities) > 1:
                # Если есть несколько качеств - кнопка активна
                keyboard_buttons.append([InlineKeyboardButton(text=f"📱 Качество: {current_quality}", callback_data=f"quality_select_{movie_key}")])
            else:
                # Если только одно качество - показываем информативную кнопку
                keyboard_buttons.append([InlineKeyboardButton(text=f"📱 Качество: {current_quality}", callback_data=f"quality_info_{movie_key}")])
            
            keyboard_buttons.append([fav_button])
            keyboard_buttons.append([InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            # Обновляем медиа в существующем сообщении
            if meta.get('type') == 'video':
                await callback.message.edit_media(
                    media=InputMediaVideo(
                        media=quality_file_id,
                        caption=caption,
                        parse_mode="HTML"
                    ),
                    reply_markup=keyboard
                )
            else:
                await callback.message.edit_media(
                    media=InputMediaDocument(
                        media=quality_file_id,
                        caption=caption,
                        parse_mode="HTML"
                    ),
                    reply_markup=keyboard
                )
            
            logging.info(f"[QUALITY_CHANGE] Обновлено сообщение с фильмом {movie_key}, качество {selected_quality}")
            
        except Exception as e:
            logging.error(f"[QUALITY_CHANGE] Ошибка обновления сообщения с новым качеством: {e}")
            # Если не удалось обновить, отправляем новое сообщение как fallback
            try:
                if meta.get('type') == 'video':
                    await bot.send_video(
                        chat_id=callback.message.chat.id,
                        video=quality_file_id,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                else:
                    await bot.send_document(
                        chat_id=callback.message.chat.id,
                        document=quality_file_id,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                logging.info(f"[QUALITY_CHANGE] Отправлено новое сообщение как fallback")
            except Exception as e2:
                logging.error(f"[QUALITY_CHANGE] Ошибка fallback отправки: {e2}")
                await callback.answer("❌ Ошибка при обновлении качества", show_alert=True)
    
    # Обработчик информативной кнопки качества (когда только одно качество)
    if data.startswith("quality_info_"):
        movie_key = data.replace("quality_info_", "")
        from storage import MOVIES
        
        meta = MOVIES.get(movie_key)
        if not meta:
            await callback.answer("❌ Фильм не найден", show_alert=True)
            return
        
        current_quality = meta.get('quality', '1080p')
        await callback.answer(f"ℹ️ Доступно только качество: {current_quality}", show_alert=True)
        return
    
    # Обработчик кнопки качества для эпизодов
    if data.startswith("quality_"):
        # Парсим данные: quality_series_season_episode
        parts = data.split("_")
        if len(parts) >= 4 and parts[0] == "quality":
            series_key = parts[1]
            try:
                season = int(parts[2])
                episode = int(parts[3])
            except ValueError:
                await callback.answer("❌ Неверный формат данных", show_alert=True)
                return
            
            logging.info(f"[EPISODE_QUALITY] series={series_key}, season={season}, episode={episode}")
            
            # Получаем доступные качества для эпизода
            qualities = get_episode_qualities(series_key, season, episode)
            
            # Всегда есть базовое качество 1080p из основной таблицы episodes
            base_quality = "1080p"
            
            if not qualities:
                # Если нет дополнительных качеств - показываем информацию о единственном качестве
                await callback.answer(f"ℹ️ Доступно только качество: {base_quality}", show_alert=True)
                return
            
            # Есть дополнительные качества - показываем меню выбора
            quality_buttons = []
            
            # Создаем список всех качеств включая базовое
            all_qualities = []
            
            # Добавляем базовое качество 1080p
            all_qualities.append({'quality': base_quality, 'is_base': True})
            
            # Добавляем дополнительные качества
            for quality_info in qualities:
                all_qualities.append({'quality': quality_info['quality'], 'is_base': False})
            
            # Сортируем все качества в правильном порядке (от большего к меньшему)
            quality_order = {'4K': 1, '1080p': 2, '720p': 3, '480p': 4, '360p': 5}
            all_qualities.sort(key=lambda x: quality_order.get(x['quality'], 99))
            
            # Получаем текущее выбранное качество пользователя
            user_id_int = callback.from_user.id
            episode_key = f"{series_key}_{season}_{episode}"
            current_selected_quality = "1080p"  # По умолчанию
            
            if user_id_int in user_episode_qualities and episode_key in user_episode_qualities[user_id_int]:
                current_selected_quality = user_episode_qualities[user_id_int][episode_key]
            
            # Создаем кнопки в правильном порядке
            for quality_item in all_qualities:
                quality = quality_item['quality']
                
                # Добавляем галочку для текущего выбранного качества
                if quality == current_selected_quality:
                    if quality_item['is_base']:
                        button_text = f"✅ {quality} (основное)"
                    else:
                        button_text = f"✅ {quality}"
                else:
                    if quality_item['is_base']:
                        button_text = f"{quality} (основное)"
                    else:
                        button_text = f"{quality}"
                
                quality_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"episode_quality_change_{series_key}_{season}_{episode}_{quality}"
                )])
            
            # Добавляем кнопку "Назад"
            quality_buttons.append([InlineKeyboardButton(
                text="🔙 Назад", 
                callback_data=f"dynamic_episode_{series_key}_{season}_{episode}"
            )])
            
            quality_keyboard = InlineKeyboardMarkup(inline_keyboard=quality_buttons)
            
            try:
                await callback.message.edit_reply_markup(reply_markup=quality_keyboard)
                await callback.answer("📱 Выберите качество")
            except Exception as e:
                logging.error(f"Error updating episode quality menu: {e}")
                await callback.answer("❌ Ошибка при обновлении меню", show_alert=True)
            
            return
    
    # Обработчик изменения качества эпизода
    if data.startswith("episode_quality_change_"):
        # Парсим данные: episode_quality_change_series_season_episode_quality
        data_without_prefix = data.replace("episode_quality_change_", "")
        parts = data_without_prefix.split("_")
        
        if len(parts) >= 4:
            series_key = parts[0]
            try:
                season = int(parts[1])
                episode = int(parts[2])
                selected_quality = "_".join(parts[3:])  # Качество может содержать _
            except ValueError:
                await callback.answer("❌ Неверный формат данных", show_alert=True)
                return
            
            logging.info(f"[EPISODE_QUALITY_CHANGE] series={series_key}, season={season}, episode={episode}, quality={selected_quality}")
            
            # Получаем file_id для выбранного качества
            if selected_quality == "1080p":
                # Базовое качество из основной таблицы episodes
                from storage import get_cached_episode
                episode_data = get_cached_episode(series_key, season, episode)
                if not episode_data:
                    await callback.answer("❌ Эпизод не найден", show_alert=True)
                    return
                quality_file_id = episode_data['file_id']
                file_type = episode_data['type']
            else:
                # Дополнительное качество из таблицы episode_qualities
                quality_file_id = get_episode_quality_file_id(series_key, season, episode, selected_quality)
                if not quality_file_id:
                    await callback.answer("❌ Файл для выбранного качества не найден", show_alert=True)
                    return
                file_type = "video"  # По умолчанию
            
            # Определяем название сериала
            series_titles = {
                'loki': 'Локи',
                'wnd': 'Уэнсдэй',
                'irh': 'Дом Дракона',
                'lbsc': 'Последние из нас'
            }
            series_title = series_titles.get(series_key, series_key.upper())
            
            # Сохраняем выбранное качество для пользователя
            user_id_int = callback.from_user.id
            episode_key = f"{series_key}_{season}_{episode}"
            
            if user_id_int not in user_episode_qualities:
                user_episode_qualities[user_id_int] = {}
            
            user_episode_qualities[user_id_int][episode_key] = selected_quality
            
            # Отправляем видео с новым качеством
            try:
                # Определяем название сериала
                series_titles = {
                    'loki': 'Локи',
                    'wnd': 'Уэнсдэй',
                    'irh': 'Дом Дракона',
                    'lbsc': 'Последние из нас'
                }
                series_title = series_titles.get(series_key, series_key.upper())
                
                # Формируем caption
                caption = f"<b>{series_title}</b>\nСезон {season} • Серия {episode}\n\n• Выберите серию:\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"
                
                # Создаем клавиатуру (используем ту же логику что и в show_series_navigation)
                from storage import get_cached_series_data
                cache_data = get_cached_series_data(series_key)
                available_seasons = cache_data['available_seasons']
                series_episodes = cache_data['episodes']
                
                # Кнопки сезонов
                season_buttons = []
                if len(available_seasons) > 1:
                    current_season_index = available_seasons.index(season)
                    prev_season = available_seasons[current_season_index - 1]
                    next_season = available_seasons[(current_season_index + 1) % len(available_seasons)]
                    season_buttons.extend([
                        InlineKeyboardButton(text="◀", callback_data=f"series_nav_{series_key}_{prev_season}"),
                        InlineKeyboardButton(text=f"Сезон {season}", callback_data="noop"),
                        InlineKeyboardButton(text="▶", callback_data=f"series_nav_{series_key}_{next_season}")
                    ])
                else:
                    season_buttons.append(InlineKeyboardButton(text=f"Сезон {season}", callback_data="noop"))
                
                # Кнопки эпизодов
                episodes_in_season = sorted([ep['episode'] for ep in series_episodes if ep['season'] == season])
                episode_buttons = []
                row = []
                callback_prefix = f"dynamic_episode_{series_key}"
                for ep_num in episodes_in_season:
                    text = f"[ {ep_num} ]" if ep_num == episode else str(ep_num)
                    row.append(InlineKeyboardButton(text=text, callback_data=f"{callback_prefix}_{season}_{ep_num}"))
                    if len(row) == 5:
                        episode_buttons.append(row)
                        row = []
                if row: episode_buttons.append(row)
                
                # Кнопка избранного
                from db import is_in_favorites
                if series_key == "lbsc":
                    check_key = f"lbsc_{season}_{episode}"
                    content_type = "lbsc_series"
                else:
                    check_key = f"{series_key}_{season}_{episode}"
                    content_type = "series"
                
                is_favorited = is_in_favorites(user_id_int, content_type, check_key)
                if is_favorited:
                    favorite_button = [InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{check_key}")]
                else:
                    favorite_button = [InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"{series_key}_fav_{season}_{episode}")]
                
                # Кнопка качества с обновленным текстом
                quality_text = f"Качество: {selected_quality}"
                quality_button = [InlineKeyboardButton(text=quality_text, callback_data=f"quality_{series_key}_{season}_{episode}")]
                
                # Кнопка случайной серии
                random_episode_button = [InlineKeyboardButton(text="🎯 Случайная серия", callback_data=f"random_episode_{series_key}")]
                
                # Кнопка назад
                from keyboards import BACK_TO_MAIN_MENU_BUTTON
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[season_buttons] + episode_buttons + [favorite_button] + [quality_button] + [random_episode_button] + [BACK_TO_MAIN_MENU_BUTTON])
                
                # Отправляем видео с новым качеством
                if file_type == 'video':
                    media = InputMediaVideo(media=quality_file_id, caption=caption, parse_mode="HTML")
                else:
                    media = InputMediaDocument(media=quality_file_id, caption=caption, parse_mode="HTML")
                
                await callback.message.edit_media(media=media, reply_markup=keyboard)
                await callback.answer(f"✅ Выбрано качество: {selected_quality}")
                
            except Exception as e:
                logging.error(f"Ошибка при смене качества: {e}")
                await callback.answer("❌ Ошибка при смене качества", show_alert=True)
            
            return
    
    # Обработчик кнопки "Перейти по ссылке" (ВАРИАНТ Б - callback)
    if data.startswith("ad_click_"):
        import time
        movie_key = data.replace("ad_click_", "")
        user_id_int = int(user_id)
        
        logging.info(f"[AD_CLICK] Пользователь {user_id} нажал на рекламную ссылку")
        
        # Записываем что пользователь кликнул
        try:
            from db import mark_ad_clicked
            mark_ad_clicked(user_id_int)
        except Exception as e:
            logging.error(f"Ошибка при отметке клика: {e}")
        
        # Обновляем timestamp для более точного контроля
        if user_id_int in ad_waiting_state:
            ad_waiting_state[user_id_int]['clicked'] = True
            ad_waiting_state[user_id_int]['click_time'] = time.time()
        
        # Отправляем сообщение с прямой ссылкой на рекламу
        ad_message = (
            "✅ <b>Отлично!</b>\n\n"
            "Теперь нажмите на кнопку ниже, чтобы открыть рекламу:"
        )
        
        ad_link_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть рекламу", url=AD_LINK)],
            [InlineKeyboardButton(text="✅ Продолжить просмотр", callback_data=f"ad_continue_{movie_key}")]
        ])
        
        try:
            await bot.send_message(
                chat_id=callback.message.chat.id,
                text=ad_message,
                parse_mode="HTML",
                reply_markup=ad_link_keyboard
            )
            await callback.answer("✅ Клик записан!")
        except Exception as e:
            logging.error(f"Ошибка отправки сообщения с рекламой: {e}")
            await callback.answer("✅ Теперь нажмите 'Продолжить просмотр'")
        
        return
    
    # Обработчик кнопки "Продолжить просмотр" после рекламы
    if data.startswith("ad_continue_"):
        import time
        movie_key = data.replace("ad_continue_", "")
        from storage import MOVIES
        from db import increment_movie_view, mark_ad_clicked
        
        user_id_int = int(user_id)
        
        logging.info(f"[AD_CONTINUE] Пользователь {user_id} продолжает просмотр фильма {movie_key}")
        
        # Проверяем что пользователь был в состоянии ожидания
        if user_id_int not in ad_waiting_state:
            await callback.answer("⚠️ Сначала нажмите на кнопку 'Перейти по ссылке'", show_alert=True)
            return
        
        # ПРОВЕРКА ПЕРЕХОДА ПО ССЫЛКЕ (ТОЛЬКО РЕАЛЬНЫЙ КЛИК!)
        
        # Проверяем что пользователь РЕАЛЬНО нажал callback кнопку
        if not ad_waiting_state[user_id_int].get('clicked', False):
            await callback.answer(
                "❌ Сначала нажмите на кнопку 'Перейти по ссылке'",
                show_alert=True
            )
            return
        
        # Дополнительная защита: проверяем что прошло хотя бы 2 секунды после клика
        click_time = ad_waiting_state[user_id_int].get('click_time', 0)
        if time.time() - click_time < 2:
            remaining = int(2 - (time.time() - click_time))
            await callback.answer(
                f"⏳ Подождите {remaining} сек. после перехода по ссылке",
                show_alert=True
            )
            return
        
        # Отмечаем что пользователь прошел по рекламе
        try:
            mark_ad_clicked(user_id_int)
        except Exception as e:
            logging.error(f"Ошибка при отметке клика по рекламе: {e}")
        
        # Удаляем состояние ожидания
        ad_waiting_state.pop(user_id_int, None)
        
        meta = MOVIES.get(movie_key)
        
        if not meta:
            await callback.answer("❌ Фильм не найден", show_alert=True)
            return
        
        try:
            file_id = meta.get('file_id')
            if not file_id:
                await callback.answer("❌ Файл фильма не найден", show_alert=True)
                return
            
            # Проверяем, добавлен ли фильм в избранное
            from db import is_in_favorites
            is_favorited = is_in_favorites(user_id, 'movie', movie_key)
            
            # Создаем кнопку в зависимости от статуса избранного
            if is_favorited:
                fav_button = InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{movie_key}")
            else:
                fav_button = InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"fav_{movie_key}")
            
            # Отправляем видео фильма
            caption = f"<b>{meta['title']}</b>\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [fav_button],
                [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
            ])
            
            if meta.get('type') == 'video':
                await bot.send_video(
                    chat_id=callback.message.chat.id,
                    video=file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            else:
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            
            logging.info(f"[AD_CONTINUE] Фильм {movie_key} отправлен после просмотра рекламы")
            
            # Добавляем просмотр в статистику (ТОЛЬКО ОДИН РАЗ!)
            try:
                from db import add_content_view
                add_content_view(user_id_int, 'movie', movie_key)
            except Exception as e:
                logging.error(f"Ошибка при добавлении просмотра: {e}")
            
            await callback.answer("✅ Спасибо! Приятного просмотра!")
            
        except Exception as e:
            logging.error(f"[AD_CONTINUE] Ошибка: {e}", exc_info=True)
            await callback.answer("❌ Ошибка при отправке фильма", show_alert=True)
        
        return
    
    # Обработчик кнопки "Лимит превышен"
    if data == "show_limits":
        user_id = callback.from_user.id
        
        # Получаем информацию о лимитах
        from db import get_time_until_limit_reset
        limits_info = get_user_limits_info(user_id)
        
        # Вычисляем время до сброса лимита
        reset_time = get_time_until_limit_reset(user_id, 'movie')
        hours = reset_time // 3600
        minutes = (reset_time % 3600) // 60
        
        if hours > 0:
            time_text = f"{hours} ч. {minutes} мин."
        else:
            time_text = f"{minutes} мин."
        
        # Формируем текст сообщения
        text = (
            f"<b>🚫 ЛИМИТ НА КОНТЕНТ В ДЕНЬ!</b>\n\n"
            f"⏱️ Лимит будет снят через: <b>{time_text}</b>\n\n"
            f"Обычные пользователи без премиум статуса могут просматривать лишь <b>{DAILY_CONTENT_LIMIT} фильмов за 24 часа</b>.\n\n"
            f"Что бы получить премиум статус, нужно пригласить всего 2 друга или купить за звёзды: /ref"
        )
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="ref_system")],
            [InlineKeyboardButton(text="🔄 Обновить время", callback_data="refresh_content_limit")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu")]
        ])
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        
        await callback.answer()
        return
    
    # Обработчик кнопки "Реферальная система"
    if data == "ref_system":
        user_id = callback.from_user.id
        
        # Сохраняем пользователя в БД
        save_user(
            user_id=user_id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            language_code=callback.from_user.language_code
        )
        
        # Получаем количество рефералов
        referrals_count = get_referrals_count(user_id)
        
        # Создаем реферальную ссылку
        bot_username = BOT_USERNAME.replace("@", "")
        referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        
        # Формируем текст сообщения
        text = (
            f"<b><i>Привет, это реферальная система.</i></b>\n\n"
            f"Вам нужно пригласить как минимум 2 человек, что бы приобрести так называемый <b>премиум-статус на 7 дней🤑</b>\n\n"
            f"<b><i>Премиум-статус даёт:</i></b>\n"
            f"<b>• Возможность добавлять фильмы, серии в избранное;\n"
            f"• Доступ к кнопке \"Случайный фильм\" и \"Случайная серия\" вашего любимого сериала;\n"
            f"• Безлимитный просмотр фильмов и сериалов</b>\n\n"
            f"<b>Ваша реферальная ссылка:</b> <code>{referral_link}</code>\n"
            f"Вы пригласили людей: {referrals_count}/2\n\n"
            f"<b><i>Скопируй ссылку выше и отправь ее друзьям для получения бонусов!</i></b>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>💎 Или купите премиум прямо сейчас:</b>\n"
            f"• <b>50 ⭐</b> — Премиум на 2 месяца\n"
            f"• <b>200 ⭐</b> — Премиум на год"
        )
        
        # Создаем клавиатуру с кнопками покупки
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить за 50⭐ на 2 месяца", callback_data="buy_premium_2months")],
            [InlineKeyboardButton(text="💎 Купить за 200⭐ на год", callback_data="buy_premium_1year")],
            [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
        ])
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await bot.send_message(
                chat_id=callback.message.chat.id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        await callback.answer()
        return
    
    # Обработчик кнопки "Купить премиум на 2 месяца"
    if data == "buy_premium_2months":
        user_id = callback.from_user.id
        
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title="Премиум на 2 месяца",
                description="• Безлимитный просмотр фильмов и сериалов\n• Избранное\n• Случайные фильмы и серии",
                payload="premium_2months",
                provider_token="",  # Пустая строка для Telegram Stars
                currency="XTR",  # Telegram Stars
                prices=[LabeledPrice(label="Премиум на 2 месяца", amount=50)],
                max_tip_amount=0,
                suggested_tip_amounts=[]
            )
            await callback.answer("Счет на оплату отправлен! ✨", show_alert=False)
        except Exception as e:
            await callback.answer(f"Ошибка при создании счета: {e}", show_alert=True)
        return
    
    # Обработчик кнопки "Купить премиум на год"
    if data == "buy_premium_1year":
        user_id = callback.from_user.id
        
        try:
            await bot.send_invoice(
                chat_id=user_id,
                title="Премиум на год",
                description="• Безлимитный просмотр фильмов и сериалов\n• Избранное\n• Случайные фильмы и серии",
                payload="premium_1year",
                provider_token="",  # Пустая строка для Telegram Stars
                currency="XTR",  # Telegram Stars
                prices=[LabeledPrice(label="Премиум на год", amount=200)],
                max_tip_amount=0,
                suggested_tip_amounts=[]
            )
            await callback.answer("Счет на оплату отправлен! ✨", show_alert=False)
        except Exception as e:
            await callback.answer(f"Ошибка при создании счета: {e}", show_alert=True)
        return
    
    # Обработчик кнопки "Премиум пользователи"
    if data == "premium_users":
        premium_users = get_premium_users()
        
        if not premium_users:
            text = "🍬 <b>Премиум пользователи</b>\n\nПока что никто не достиг премиум-статуса.\nСтаньте первым, пригласив 2+ друзей!"
        else:
            text = "🍬 <b>Премиум пользователи</b>\n\nПользователи, которые пригласили 2+ друзей:\n\n"
            
            for i, user in enumerate(premium_users, 1):
                username = user['username']
                first_name = user['first_name'] or "Пользователь"
                referrals_count = user['referrals_count']
                
                if username:
                    user_display = f"@{username}"
                else:
                    user_display = first_name
                
                text += f"{i}. {user_display} — {referrals_count} рефералов\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
        ])
        
        await bot.send_message(callback.from_user.id, text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
        return
    
    # Мастер /addfilm: подтверждение/отмена
    if data == "addfilm_cancel":
        addfilm_state.pop(callback.from_user.id, None)
        await callback.answer("Отменено")
        try:
            await callback.message.edit_text("Добавление фильма отменено.")
        except Exception:
            pass
        return
    if data == "addfilm_cancel_step":
        addfilm_state.pop(callback.from_user.id, None)
        await callback.answer("Отменено")
        try:
            await callback.message.edit_text("Добавление фильма отменено.")
        except Exception:
            pass
        return
    if data == "addfilm_confirm":
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Нет доступа")
            return
        state = addfilm_state.pop(callback.from_user.id, None)
        if not state or state.get("step") != "confirm":
            await callback.answer("Нечего сохранять", show_alert=True)
            return
        d = state.get("data", {})
        key = d.get("key")
        title = d.get("title")
        file_id = d.get("file_id")
        aliases = d.get("aliases") or []
        poster_url = d.get("poster_url")
        try:
            from db import bulk_upsert_movies
            from storage import _load_to_memory
            
            # Сохраняем в БД (thumb_url = poster_url, share_query = title)
            bulk_upsert_movies([
                (key, title, file_id, 'video', poster_url, poster_url, aliases, title)
            ])
            
            # Обновляем кэш в памяти для загрузки новых данных
            _load_to_memory()
            
            keywords_text = ", ".join(aliases[:5]) + ("..." if len(aliases) > 5 else "")
            
            logging.info(f"[addfilm] Фильм '{title}' с ключом '{key}' добавлен в базу и поиск")
            
            await callback.message.edit_text(
                f"✅ Фильм <b>{title}</b> добавлен в базу и поиск!\n\n"
                f"🔑 Ключ: <code>{key}</code>\n"
                f"🏷 Ключевые слова: {keywords_text}\n\n"
                f"🔄 Кэш автоматически обновлен", 
                parse_mode="HTML"
            )
            await callback.answer("Сохранено")
        except Exception as e:
            await callback.answer("Ошибка", show_alert=True)
            try:
                await callback.message.edit_text(f"❌ Ошибка сохранения: {e}")
            except Exception:
                pass
        return

    # Мастер /addserial: подтверждение/отмена
    if data == "addserial_cancel":
        addserial_state.pop(callback.from_user.id, None)
        await callback.answer("Отменено")
        try:
            await callback.message.edit_text("Добавление сериала отменено.")
        except Exception:
            pass
        return
    if data == "addserial_cancel_step":
        addserial_state.pop(callback.from_user.id, None)
        await callback.answer("Отменено")
        try:
            await callback.message.edit_text("Добавление сериала отменено.")
        except Exception:
            pass
        return
    if data == "addserial_confirm":
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Нет доступа")
            return
        state = addserial_state.pop(callback.from_user.id, None)
        if not state or state.get("step") != "confirm":
            await callback.answer("Нечего сохранять", show_alert=True)
            return
        d = state.get("data", {})
        key = d.get("key")
        title = d.get("title")
        aliases = d.get("aliases") or []
        poster_url = d.get("poster_url")
        try:
            from db import bulk_upsert_series
            from storage import SERIES_POSTERS, _load_to_memory
            
            # Сохраняем в БД (series таблица для метаданных сериалов)
            bulk_upsert_series([
                (key, title, poster_url, poster_url, aliases, title)
            ])
            
            # Добавляем сериал в поиск - создаем пустые структуры данных
            # Все сериалы теперь в базе данных - storage больше не нужен для серий
            
            # Обновляем кэш в памяти для загрузки новых данных
            _load_to_memory()
            
            # Добавляем постер сериала если есть
            if poster_url and key not in SERIES_POSTERS:
                SERIES_POSTERS[key] = {'show': poster_url}
            
            keywords_text = ", ".join(aliases[:5]) + ("..." if len(aliases) > 5 else "")
            
            logging.info(f"[addserial] Сериал '{title}' с ключом '{key}' добавлен в базу и поиск")
            
            await callback.message.edit_text(
                f"✅ Сериал <b>{title}</b> добавлен в базу и поиск!\n\n"
                f"🔑 Ключ: <code>{key}</code>\n"
                f"🏷 Ключевые слова: {keywords_text}\n"
                f"📺 Теперь можно добавлять эпизоды командой:\n"
                f"<code>/addepisode {key} 1 1 &lt;file_id&gt;</code>\n\n"
                f"🔄 Кэш автоматически обновлен", 
                parse_mode="HTML"
            )
            await callback.answer("Сохранено")
        except Exception as e:
            logging.exception(f"[addserial] Ошибка при добавлении сериала: {e}")
            await callback.answer("Ошибка", show_alert=True)
            try:
                await callback.message.edit_text(f"❌ Ошибка сохранения: {e}")
            except Exception:
                pass
        return

    # Старт общения с админом
    if data == "contact_admin_start":
        waiting_for_admin_message[callback.from_user.id] = True
        tech_support_state[callback.from_user.id] = True  # Включаем режим тех.поддержки
        if callback.message:
            await callback.message.answer(
                "✍️ Напишите одно сообщение для администратора.\n"
                "После отправки мы передадим его и вернём вам подтверждение."
            )
        else:
            # Если callback.message is None (inline сообщение), отправляем через bot
            await bot.send_message(
                callback.from_user.id,
                "✍️ Напишите одно сообщение для администратора.\n"
                "После отправки мы передадим его и вернём вам подтверждение."
            )
        await callback.answer()
        return
    # Обновление статистики по кнопке
    if data == "stats_refresh":
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("Нет доступа", show_alert=False)
            return
        text = _build_stats_text()
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_stats_keyboard())
        except TelegramBadRequest:
            try:
                # Если текст не изменился, всё равно обновим клавиатуру
                await callback.message.edit_reply_markup(reply_markup=_stats_keyboard())
            except Exception:
                pass
        await callback.answer("Обновлено")
        return
    
    # === Обработчики для динамических сериалов ===
    if data.startswith("dynamic_season_"):
        # dynamic_season_homes_1
        try:
            # Убираем префикс dynamic_season_
            remaining = data[15:]  # len("dynamic_season_") = 15
            # Последняя часть после последнего _ - это номер сезона
            parts = remaining.rsplit("_", 1)
            if len(parts) == 2:
                series_key = parts[0]
                season = int(parts[1])
            else:
                # Если нет _, то весь remaining - это series_key, а season = 1
                series_key = remaining
                season = 1
        except (ValueError, IndexError) as e:
            logging.exception(f"[dynamic_season] Ошибка парсинга callback_data '{data}': {e}")
            await callback.answer("Ошибка обработки сезона", show_alert=True)
            return
        
        from keyboards import get_dynamic_episodes_keyboard
        from storage import DYNAMIC_SERIES
        
        logging.info(f"[dynamic_season] series_key='{series_key}', season={season}")
        
        # Получаем название сериала
        series_title = series_key.upper()
        try:
            from db import load_all_series
            all_series = load_all_series()
            for series in all_series:
                if series['key'] == series_key:
                    series_title = series['title']
                    break
        except Exception:
            pass
        
        text = f"<b>{series_title} — Сезон {season}</b>\nВыберите серию:"
        keyboard = get_dynamic_episodes_keyboard(series_key, season)
        
        try:
            if callback.message:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
                await callback.answer()
            else:
                # Если нет сообщения, отправляем новое
                await callback.bot.send_message(
                    chat_id=callback.from_user.id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                await callback.answer()
        except Exception as e:
            logging.exception(f"[dynamic_season] Ошибка редактирования сообщения: {e}")
            await callback.answer("Ошибка при загрузке эпизодов", show_alert=True)
        return
    
    if data.startswith("dynamic_back_to_seasons_"):
        # dynamic_back_to_seasons_homes
        series_key = data.replace("dynamic_back_to_seasons_", "")
        
        from keyboards import get_dynamic_seasons_keyboard
        
        # Получаем название сериала
        series_title = series_key.upper()
        try:
            from db import load_all_series
            all_series = load_all_series()
            for series in all_series:
                if series['key'] == series_key:
                    series_title = series['title']
                    break
        except Exception:
            pass
        
        text = f"<b>{series_title}</b>\nВыберите сезон:"
        keyboard = get_dynamic_seasons_keyboard(series_key)
        
        try:
            if callback.message:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
                await callback.answer()
            else:
                # Если нет сообщения, отправляем новое
                await callback.bot.send_message(
                    chat_id=callback.from_user.id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                await callback.answer()
        except Exception as e:
            logging.exception(f"[dynamic_back_to_seasons] Ошибка редактирования сообщения: {e}")
            await callback.answer("Ошибка при загрузке сезонов", show_alert=True)
        return
    
    if data.startswith("dynamic_episode_"):
        # dynamic_episode_homes_1_1
        parts = data.split("_")
        if len(parts) >= 4:
            series_key = "_".join(parts[2:-2]) if len(parts) > 4 else parts[2]
            season = int(parts[-2])
            episode = int(parts[-1])
            
            # Получаем сериал из БД
            from db import load_all_series, load_all_episodes
            try:
                all_series = load_all_series()
                series_data = None
                for series in all_series:
                    if series['key'] == series_key:
                        series_data = series
                        break
                if series_data:
                    await show_series_navigation(callback, series_key, season=season, episode=episode)
                else:
                    await callback.answer("Сериал не найден", show_alert=True)
            except Exception as e:
                print(f"[dynamic_episode] Ошибка при отправке эпизода: {e}")
                await callback.answer("Ошибка при загрузке эпизода", show_alert=True)
        return

    if data.startswith("series_watch_"):
        series_key = data.replace("series_watch_", "")
        logging.info(f"[SERIES_WATCH] Запрос на просмотр сериала: {series_key}, user: {user_id}")
        
        # Добавляем просмотр сериала в статистику
        try:
            from db import add_content_view
            add_content_view(user_id, 'series', series_key)
            logging.info(f"[SERIES_WATCH] Просмотр сериала {series_key} добавлен в статистику")
        except Exception as e:
            logging.error(f"[SERIES_WATCH] Ошибка при добавлении просмотра сериала {series_key}: {e}")
        
        await show_series_navigation(callback, series_key)
        return

    if data.startswith("series_nav_"):
        prefix = "series_nav_"
        rest = data[len(prefix):]
        idx = rest.rfind("_")
        if idx == -1:
            logging.exception(f"[series_nav] Некорректный формат (нет _): data={data}")
            await callback.answer("Ошибка формата навигации сезона", show_alert=True)
            return
        series_key = rest[:idx]
        season_str = rest[idx+1:]
        if not season_str.isdigit():
            logging.exception(f"[series_nav] Некорректное значение для сезона: '{season_str}', rest={rest}, data={data}")
            await callback.answer("Ошибка в номере сезона кнопки", show_alert=True)
            return
        season = int(season_str)
        print(f"[series_nav] Переключение сезона: {series_key}, сезон {season}")
        await show_series_navigation(callback, series_key, season=season)
        return
    elif data == "phf_favorites":
        # Избранные серии Финес и Ферб
        favs = stats.get("phf_favorites", {}).get(user_id, [])
        if not favs:
            await callback.message.answer("У вас нет избранных серий Финеса и Ферба.")
            return
        text = "<b>⭐️ Ваши избранные серии Финеса и Ферба:</b>\nВыбери серию для просмотра:" 
        buttons = []
        row = []
        for key in favs:
            try:
                _, season, episode = key.split("_")
                btn = InlineKeyboardButton(
                    text=f"Сезон {season}, Серия {episode}",
                    callback_data=f"dynamic_episode_{series_key}_{season}_{episode}"
                )
                row.append(btn)
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            except Exception:
                continue
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⬅️ Назад к сезонам", callback_data="choose_phf")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)
        return
    elif data == "lbsc_favorites":
        # Избранные серии Леди Баг и Супер Кот
        favs = stats.get("lbsc_favorites", {}).get(user_id, [])
        if not favs:
            await callback.message.answer("У вас нет избранных серий Леди Баг и Супер-Кот.")
            return
        text = "<b>⭐️ Ваши избранные серии Леди Баг и Супер-Кот:</b>\nВыбери серию для просмотра:" 
        buttons = []
        row = []
        for key in favs:
            try:
                _, season, episode = key.split("_")
                btn = InlineKeyboardButton(
                    text=f"Сезон {season}, Серия {episode}",
                    callback_data=f"dynamic_episode_{series_key}_{season}_{episode}"
                )
                row.append(btn)
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            except Exception:
                continue
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton(text="⬅️ Назад к сезонам", callback_data="choose_lbsc")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)
        return
    elif data == "my_playlists" or data == "create_playlist" or data.startswith("show_playlist_") or data.startswith("pladd_season_") or data.startswith("pladd_toggle_") or data == "pladd_back" or data == "pladd_save":
        await callback.message.answer("Создание и просмотр плейлистов отключены.")
    elif data == "choose_rnm":
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text="<b>Выбери сезон Рик и Морти:</b>",
                parse_mode="HTML",
                reply_markup=get_seasons_keyboard()
            )
        else:
            await callback.message.edit_text(
            "<b>Выбери сезон Рик и Морти:</b>",
            reply_markup=get_seasons_keyboard(),
            parse_mode="HTML"
        )
    elif data == "choose_phf":
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text="<b>Выбери сезон Финес и Ферб:</b>",
                parse_mode="HTML",
                reply_markup=get_phf_seasons_keyboard()
            )
        else:
            try:
                await callback.message.edit_text(
                    "<b>Выбери сезон Финес и Ферб:</b>",
                    reply_markup=get_phf_seasons_keyboard(),
                    parse_mode="HTML"
                )
            except Exception:
                await safe_send_message(
                    callback,
                    "<b>Выбери сезон Финес и Ферб:</b>",
                    reply_markup=get_phf_seasons_keyboard()
                )
        return
    elif data == "choose_irh":
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text="<b>Выбери сезон Железное сердце:</b>",
                parse_mode="HTML",
                reply_markup=get_irh_seasons_keyboard()
            )
        else:
            try:
                await callback.message.edit_text(
                    "<b>Выбери сезон Железное сердце:</b>",
                    reply_markup=get_irh_seasons_keyboard(),
                    parse_mode="HTML"
                )
            except Exception:
                await safe_send_message(
                    callback,
                    "<b>Выбери сезон Железное сердце:</b>",
                    reply_markup=get_irh_seasons_keyboard()
                )
        return
    elif data == "choose_wnd":
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text="<b>Выбери сезон Уэнсдэй (2022):</b>",
                parse_mode="HTML",
                reply_markup=get_wnd_seasons_keyboard()
            )
        else:
            try:
                await callback.message.edit_text(
                    "<b>Выбери сезон Уэнсдэй (2022):</b>",
                    reply_markup=get_wnd_seasons_keyboard(),
                    parse_mode="HTML"
                )
            except Exception:
                await safe_send_message(
                    callback,
                    "<b>Выбери сезон Уэнсдэй (2022):</b>",
                    reply_markup=get_wnd_seasons_keyboard()
                )
        return
    elif data == "choose_loki":
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text="<b>Выбери сезон Локи (2021):</b>",
                parse_mode="HTML",
                reply_markup=get_loki_seasons_keyboard()
            )
        else:
            try:
                await callback.message.edit_text(
                    "<b>Выбери сезон Локи (2021):</b>",
                    reply_markup=get_loki_seasons_keyboard(),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    callback.message.chat.id,
                    "<b>Выбери сезон Локи (2021):</b>",
                    reply_markup=get_loki_seasons_keyboard(),
                    parse_mode="HTML"
                )
        return
    elif data == "back_to_main_menu":
        # Очищаем состояние ожидания сообщения админу
        waiting_for_admin_message.pop(callback.from_user.id, None)
        
        # Проверяем премиум статус
        user_id_int = callback.from_user.id
        is_premium = is_premium_user(user_id_int)
        premium_status = "<b>Вы являетесь премиум пользователем</b>" if is_premium else "<b>Вы не являетесь премиум пользователем</b>"
        
        text = (
            "Привет!👋\n\n"
            "<i>Ты попал в кино-бот!</i> <b>У нас большая коллекция фильмов и сериалов на любой вкус!</b>🎥\n\n"
            f"{premium_status}\n\n"
            "<b><i>Что бы ознакомиться с ботом, нажми /help либо \"Помощь\".</i></b>\n\n"
            "Нажми на \"Начать поиск\" и приятного тебе <b>просмотра!</b>"
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            await bot.send_message(
                callback.message.chat.id,
                text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        return
    elif data == "choose_lbsc":
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text="<b>Выбери сезон Леди Баг и Супер-Кот:</b>",
                parse_mode="HTML",
                reply_markup=get_lbsc_seasons_keyboard()
            )
        else:
            try:
                await callback.message.edit_text(
                    "<b>Выбери сезон Леди Баг и Супер-Кот:</b>",
                    reply_markup=get_lbsc_seasons_keyboard(),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    callback.message.chat.id,
                    "<b>Выбери сезон Леди Баг и Супер-Кот:</b>",
                    reply_markup=get_lbsc_seasons_keyboard(),
                    parse_mode="HTML"
                )
        return
    elif data.startswith("lbsc_season_"):
        season = int(data.split("_")[2])
        
        # Специальное сообщение для 6 сезона
        if season == 6:
            text = (
                "<b>🐞 Леди Баг и Супер-Кот — Сезон 6</b>\n\n"
                "⚠️ <b>СЕРИАЛ ЕЩЕ ВЫХОДИТ</b>\n"
                "Следите за обновлениями!\n\n"
                "Выбери серию:"
            )
        else:
            text = f"<b>Леди Баг и Супер-Кот — Сезон {season}</b>\nВыбери серию:"
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_lbsc_episodes_keyboard(season)
            )
        else:
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=get_lbsc_episodes_keyboard(season),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    callback.message.chat.id,
                    text,
                    reply_markup=get_lbsc_episodes_keyboard(season),
                    parse_mode="HTML"
                )
        return
    elif data.startswith("phf_season_"):
        season = int(data.split("_")[2])
        text = f"<b>Финес и Ферб — Сезон {season}</b>\nВыбери серию:"
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_phf_episodes_keyboard(season)
            )
        else:
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=get_phf_episodes_keyboard(season),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    callback.message.chat.id,
                    text,
                    reply_markup=get_phf_episodes_keyboard(season),
                    parse_mode="HTML"
                )
        return
    elif data.startswith("irh_season_"):
        season = int(data.split("_")[2])
        text = f"<b>Железное сердце — Сезон {season}</b>\nВыбери серию:"
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_irh_episodes_keyboard(season)
            )
        else:
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=get_irh_episodes_keyboard(season),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    callback.message.chat.id,
                    text,
                    reply_markup=get_irh_episodes_keyboard(season),
                    parse_mode="HTML"
                )
        return
    elif data.startswith("wnd_season_"):
        season = int(data.split("_")[2])
        text = f"<b>Уэнсдэй (2022) — Сезон {season}</b>\nВыбери серию:"
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_wnd_episodes_keyboard(season)
            )
        else:
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=get_wnd_episodes_keyboard(season),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    callback.message.chat.id,
                    text,
                    reply_markup=get_wnd_episodes_keyboard(season),
                    parse_mode="HTML"
                )
        return
    elif data.startswith("loki_season_"):
        season = int(data.split("_")[2])
        text = f"<b>Локи (2021) — Сезон {season}</b>\nВыбери серию:"
        if getattr(callback, 'inline_message_id', None):
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=get_loki_episodes_keyboard(season)
            )
        else:
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=get_loki_episodes_keyboard(season),
                    parse_mode="HTML"
                )
            except Exception:
                await bot.send_message(
                    callback.message.chat.id,
                    text,
                    reply_markup=get_loki_episodes_keyboard(season),
                    parse_mode="HTML"
                )
        return
    elif data.startswith("phf_episode_"):
        # Перенаправляем на новую навигацию
        parts = data.split("_")
        season = int(parts[-2])
        episode = int(parts[-1])
        
        await show_series_navigation(callback, "phf", season=season, episode=episode)
        return
    elif data.startswith("loki_episode_"):
        # Перенаправляем на новую навигацию
        parts = data.split("_")
        season = int(parts[-2])
        episode = int(parts[-1])
        
        await show_series_navigation(callback, "loki", season=season, episode=episode)
        return
    elif data.startswith("wnd_episode_"):
        # Перенаправляем на новую навигацию
        parts = data.split("_")
        season = int(parts[-2])
        episode = int(parts[-1])
        
        await show_series_navigation(callback, "wnd", season=season, episode=episode)
        return
    elif data.startswith("irh_episode_"):
        # Перенаправляем на новую навигацию
        parts = data.split("_")
        season = int(parts[-2])
        episode = int(parts[-1])
        
        await show_series_navigation(callback, "irh", season=season, episode=episode)
        return
    elif data.startswith("lbsc_episode_"):
        # Перенаправляем на новую навигацию
        parts = data.split("_")
        season = int(parts[-2])
        episode = int(parts[-1])
        
        await show_series_navigation(callback, "lbsc", season=season, episode=episode)
        return
    elif data == "back_to_seasons":
        try:
            await callback.message.edit_text(
                "<b>Выбери сезон Рик и Морти:</b>",
                reply_markup=get_seasons_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            await safe_send_message(
                callback,
                "<b>Выбери сезон Рик и Морти:</b>",
                reply_markup=get_seasons_keyboard()
            )
        return
    elif callback.data == "contact_admin":
        waiting_for_admin_message[callback.from_user.id] = True
        tech_support_state[callback.from_user.id] = True  # Включаем режим тех.поддержки
        text = (
            "💬 <b>Связь с администратором</b>\n\n"
            "Напишите ваше сообщение, и я передам его администратору.\n"
            "Администратор ответит вам в этом же чате.\n\n"
            "<i>Для отмены нажмите /cancel</i>"
        )
        await bot.send_message(
            callback.from_user.id,
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_main_menu")]
            ])
        )
    elif callback.data == "random_movie":
        # Проверяем премиум статус (админ может все)
        user_id_int = int(user_id)
        if user_id_int not in ADMIN_IDS and not is_premium_user(user_id_int):
            await callback.answer("🔒 Функция доступна только для премиум пользователей! Пригласите 2 друзей.", show_alert=True)
            return
            
        from db import get_random_movie, is_in_favorites
        
        # Получаем случайный фильм из базы данных
        movie = get_random_movie()
        
        if not movie:
            await callback.answer("❌ Фильмы не найдены в базе данных!", show_alert=True)
            return
        movie_key = movie['key']
        
        # Проверяем, добавлен ли фильм в избранное
        is_favorited = is_in_favorites(user_id, 'movie', movie_key)
        
        # Создаем кнопку в зависимости от статуса избранного
        if is_favorited:
            fav_button = InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{movie_key}")
        else:
            fav_button = InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"fav_{movie_key}")
        
        # Отправляем случайный фильм
        caption = f"<b>{movie['title']}</b>\n\n🎲 <i>Случайный фильм</i>\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [fav_button],
            [InlineKeyboardButton(text="🎲 Ещё случайный", callback_data="random_movie")],
            [InlineKeyboardButton(text="⬅️ Назад в главное меню", callback_data="back_to_main_menu")]
        ])
        
        try:
            await bot.send_video(
                callback.from_user.id,
                video=movie['file_id'],
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
            # Добавляем просмотр в статистику
            try:
                from db import add_content_view
                add_content_view(user_id, 'movie', movie_key)
            except Exception as e:
                logging.error(f"Ошибка при добавлении просмотра случайного фильма {movie_key}: {e}")
            
            await callback.answer("🎲 Случайный фильм отправлен!")
        except Exception as e:
            await callback.answer(f"❌ Ошибка отправки фильма: {str(e)}", show_alert=True)
        return
    elif callback.data.startswith("random_episode_"):
        # Проверяем премиум статус (админ может все)
        if user_id not in ADMIN_IDS and not is_premium_user(user_id):
            await callback.answer("🔒 Функция доступна только для премиум пользователей! Пригласите 2 друзей.", show_alert=True)
            return
            
        series_key = callback.data.replace("random_episode_", "")
        
        from db import get_random_episode, get_series_title, is_in_favorites
        
        # Получаем случайную серию из указанного сериала
        episode = get_random_episode(series_key)
        
        if not episode:
            await callback.answer("❌ Серии не найдены для этого сериала!", show_alert=True)
            return
        
        user_id = callback.from_user.id
        season = episode['season']
        episode_num = episode['episode']
        
        # Определяем название сериала
        series_titles = {
            "rm": "Рик и Морти",
            "lbsc": "Леди Баг и Супер Кот", 
            "phf": "Финес и Ферб",
            "wnd": "Уэнсдэй (2022)",
            "irh": "Железное сердце",
            "loki": "Локи (2021)"
        }
        
        series_title = series_titles.get(series_key, get_series_title(series_key))
        
        # Формируем ключ для проверки избранного
        if series_key == "lbsc":
            check_key = f"lbsc_{season}_{episode_num}"
            content_type = "lbsc_series"
        else:
            check_key = f"{series_key}_{season}_{episode_num}"
            content_type = "series"
        
        # Проверяем, добавлена ли серия в избранное
        is_favorited = is_in_favorites(user_id, content_type, check_key)
        
        # Создаем кнопку в зависимости от статуса избранного
        if is_favorited:
            fav_button = InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{check_key}")
        else:
            fav_button = InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"{series_key}_fav_{season}_{episode_num}")
        
        # Отправляем случайную серию
        caption = f"<b>{series_title}</b>\nСезон {season} • Серия {episode_num}\n\n🎯 <i>Случайная серия</i>\n\n<b><i>🎬 Наш кино-бот: https://t.me/{BOT_USERNAME}</i></b>"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [fav_button],
            [InlineKeyboardButton(text="🎯 Ещё случайная серия", callback_data=f"random_episode_{series_key}")],
            [InlineKeyboardButton(text="📺 К сериалу", callback_data=f"series_{series_key}")],
            [InlineKeyboardButton(text="⬅️ Назад в главное меню", callback_data="back_to_main_menu")]
        ])
        
        try:
            # Отправляем серию (не как ответ, а как новое сообщение)
            if episode['type'] == 'video':
                await callback.message.answer_video(
                    video=episode['file_id'],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            else:
                await callback.message.answer_document(
                    document=episode['file_id'],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            
            # Добавляем просмотр случайной серии в статистику
            try:
                from db import add_content_view
                episode_key = f"{series_key}_{season}_{episode_num}"
                add_content_view(user_id, 'episode', episode_key)
                # Также добавляем просмотр сериала в целом
                add_content_view(user_id, 'series', series_key)
            except Exception as e:
                logging.error(f"Ошибка при добавлении просмотра случайной серии {series_key} S{season}E{episode_num}: {e}")
            
            await callback.answer("🎯 Случайная серия отправлена!")
        except Exception as e:
            await callback.answer(f"❌ Ошибка отправки серии: {str(e)}", show_alert=True)
        return
    elif callback.data.startswith("series_"):
        # Обработчик для кнопки "К сериалу"
        series_key = callback.data.replace("series_", "")
        
        # Показываем навигацию по сериалу
        success = await show_series_navigation(callback, series_key)
        if success:
            await callback.answer()
        return
    elif callback.data == "back_to_main_menu":
        # Очищаем состояние ожидания сообщения админу
        waiting_for_admin_message.pop(callback.from_user.id, None)
        
        # Проверяем премиум статус
        user_id_check = callback.from_user.id
        is_premium = is_premium_user(user_id_check)
        premium_status = "<b>Вы являетесь премиум пользователем</b>" if is_premium else "<b>Вы не являетесь премиум пользователем</b>"
        
        text = (
            "Привет!👋\n\n"
            "<i>Ты попал в кино-бот!</i> <b>У нас большая коллекция фильмов и сериалов на любой вкус!</b>🎥\n\n"
            f"{premium_status}\n\n"
            "<b><i>Что бы ознакомиться с ботом, нажми /help либо \"Помощь\".</i></b>\n\n"
            "Нажми на \"Начать поиск\" и приятного тебе <b>просмотра!</b>"
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            await bot.send_message(
                callback.message.chat.id,
                text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML"
            )
        return
    elif callback.data == "movies_menu":
        text = (
            "<b>🎬 Фильмы</b>\n\n"
            "Выберите подборку или начните поиск по названию."
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_movies_menu_keyboard(),
                parse_mode="HTML"
            )
        except Exception:
            await bot.send_message(
                callback.message.chat.id,
                text,
                reply_markup=get_movies_menu_keyboard(),
                parse_mode="HTML"
            )
        return
    elif callback.data == "choose_rnm":
        text = "<b>Выбери сезон Рик и Морти:</b>"
        try:
            await callback.message.edit_text(text, reply_markup=get_seasons_keyboard(), parse_mode="HTML")
        except Exception:
            if callback.message:
                await bot.send_message(callback.message.chat.id, text, reply_markup=get_seasons_keyboard(), parse_mode="HTML")
        return
    elif callback.data == "choose_phf":
        text = "<b>Финес и Ферб — выбери сезон:</b>"
        try:
            await callback.message.edit_text(text, reply_markup=get_phf_seasons_keyboard(), parse_mode="HTML")
        except Exception:
            if callback.message:
                await bot.send_message(callback.message.chat.id, text, reply_markup=get_phf_seasons_keyboard(), parse_mode="HTML")
        return
    elif callback.data == "choose_lbsc":
        text = "<b>Леди Баг и Супер‑Кот — выбери сезон:</b>"
        try:
            await callback.message.edit_text(text, reply_markup=get_lbsc_seasons_keyboard(), parse_mode="HTML")
        except Exception:
            if callback.message:
                await bot.send_message(callback.message.chat.id, text, reply_markup=get_lbsc_seasons_keyboard(), parse_mode="HTML")
        return
    elif callback.data.startswith("reply_user_"):
        user_id_to_reply = int(callback.data.split("_")[-1])
        waiting_admin_reply[callback.from_user.id] = user_id_to_reply
        await callback.message.answer(f"Введите ваш ответ для пользователя <code>{user_id_to_reply}</code> и он получит его первым сообщением!", parse_mode="HTML")
        await callback.answer("Введите ваш ответ сообщением ниже", show_alert=False)
        return
    # --- Меню рассылки ---
    if callback.data.startswith("broadcast_") and callback.from_user.id in ADMIN_IDS:
        state = broadcast_state.get(callback.from_user.id, {})
        
        if callback.data == "broadcast_cancel":
            broadcast_state.pop(callback.from_user.id, None)
            try:
                await callback.message.edit_text("❌ <b>Рассылка отменена</b>", parse_mode="HTML")
            except:
                await callback.message.answer("❌ <b>Рассылка отменена</b>", parse_mode="HTML")
            await callback.answer()
            return
            
        if callback.data == "broadcast_buttons":
            state["step"] = "buttons"
            await callback.message.edit_text(
                "🔘 <b>Настройка кнопок</b>\n\n"
                "Выберите готовые кнопки или создайте свои URL-кнопки:",
                parse_mode="HTML",
                reply_markup=get_broadcast_buttons_keyboard(state.get("selected_buttons", set()))
            )
            await callback.answer()
            return
        if callback.data == "broadcast_buttons_done":
            # Создаем предпросмотр рассылки
            await create_broadcast_preview(callback, state)
            await callback.answer()
            return
        if callback.data == "broadcast_buttons_clear":
            state["buttons"] = None
            state["selected_buttons"] = set()
            state["button_configs"] = []
            await callback.message.edit_reply_markup(
                reply_markup=get_broadcast_buttons_keyboard(set())
            )
            await callback.answer("Кнопки очищены", show_alert=False)
            return
        if callback.data == "broadcast_btn_custom":
            state["step"] = "custom_button"
            await callback.message.edit_text(
                "🔗 <b>Создание URL кнопки</b>\n\n"
                "Отправьте сообщение в формате:\n"
                "<code>Текст кнопки-https://example.com</code>\n\n"
                "📝 <b>Примеры:</b>\n"
                "• <code>Наш канал-https://t.me/yourchannel</code>\n"
                "• <code>Официальный сайт-https://example.com</code>\n"
                "• <code>Поддержка-https://t.me/support</code>\n\n"
                "💡 <i>Используйте дефис (-) для разделения текста и ссылки</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="broadcast_buttons")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
                ])
            )
            await callback.answer()
            return
        if callback.data.startswith("broadcast_btn_"):
            btn_type = callback.data.replace("broadcast_btn_", "")
            state.setdefault("selected_buttons", set())
            state.setdefault("button_configs", [])
            
            if btn_type == "search":
                if "search" in state["selected_buttons"]:
                    state["selected_buttons"].remove("search")
                    state["button_configs"] = [b for b in state["button_configs"] if b.get("type") != "search"]
                else:
                    state["selected_buttons"].add("search")
                    state["button_configs"].append({
                        "type": "search",
                        "text": "🔎 Начать поиск",
                        "switch_inline_query_current_chat": ""
                    })
            elif btn_type == "support":
                if "support" in state["selected_buttons"]:
                    state["selected_buttons"].remove("support")
                    state["button_configs"] = [b for b in state["button_configs"] if b.get("type") != "support"]
                else:
                    state["selected_buttons"].add("support")
                    state["button_configs"].append({
                        "type": "support",
                        "text": "📩 Тех.Поддержка",
                        "callback_data": "contact_admin_start"
                    })
            
            # Обновляем клавиатуру с галочками
            try:
                await callback.message.edit_reply_markup(
                    reply_markup=get_broadcast_buttons_keyboard(state["selected_buttons"])
                )
            except Exception:
                # Игнорируем ошибку если клавиатура не изменилась
                pass
            # Проверяем, что это не custom кнопка
            if btn_type != "custom":
                await callback.answer(f"Кнопка {'убрана' if btn_type not in state['selected_buttons'] else 'добавлена'}", show_alert=False)
            return
        if callback.data == "broadcast_buttons_back_to_selection":
            state["step"] = "buttons"
            await callback.message.edit_text(
                "<b>Выберите кнопки для добавления к сообщению:</b>\n\n"
                "Вы можете выбрать готовые кнопки или добавить пользовательскую ссылку.",
                parse_mode="HTML",
                reply_markup=get_broadcast_buttons_keyboard(state.get("selected_buttons", set()))
            )
            return
    
    # Обработка кнопки отправки рассылки (вынесено из блока broadcast_)
    if callback.data == "broadcast_send" and callback.from_user.id in ADMIN_IDS:
        await callback.answer("📤 Начинаю рассылку...")
        
        if callback.from_user.id not in broadcast_state:
            await callback.answer("❌ Сессия рассылки истекла. Начните заново с /broadcast", show_alert=True)
            return
            
        state = broadcast_state[callback.from_user.id]
        logging.info(f"[BROADCAST_SEND] Admin {callback.from_user.id} sending broadcast. Type: {state.get('type')}")
        
        # Получаем всех пользователей
        users = load_all_users()
        if not users:
            await callback.message.edit_text("❌ Нет пользователей для рассылки.")
            return
        
        content = state.get("content", {})
        content_type = state.get("type")
        button_configs = state.get("button_configs", [])
        
        # Создаем клавиатуру из кнопок
        final_buttons = None
        if button_configs:
            keyboard_rows = []
            current_row = []
            
            for config in button_configs:
                if "url" in config:
                    btn = InlineKeyboardButton(text=config["text"], url=config["url"])
                    current_row.append(btn)
                    
                    # По 2 кнопки в ряд
                    if len(current_row) == 2:
                        keyboard_rows.append(current_row)
                        current_row = []
            
            # Добавляем оставшиеся кнопки
            if current_row:
                keyboard_rows.append(current_row)
            
            if keyboard_rows:
                final_buttons = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        
        await callback.message.edit_text(f"📤 <b>Отправляю рассылку...</b>\n\n👥 Пользователей: {len(users)}", parse_mode="HTML")
        
        success_count = 0
        error_count = 0
        
        # Функция отправки для разных типов контента
        async def send_to_user(user_id):
            nonlocal success_count, error_count
            try:
                if content_type == "text":
                    await bot.send_message(user_id, content["text"], parse_mode="HTML", reply_markup=final_buttons)
                elif content_type == "photo":
                    await bot.send_photo(user_id, content["photo"], caption=content.get("caption", ""), parse_mode="HTML", reply_markup=final_buttons)
                elif content_type == "video":
                    await bot.send_video(user_id, content["video"], caption=content.get("caption", ""), parse_mode="HTML", reply_markup=final_buttons)
                elif content_type == "document":
                    await bot.send_document(user_id, content["document"], caption=content.get("caption", ""), parse_mode="HTML", reply_markup=final_buttons)
                elif content_type == "audio":
                    await bot.send_audio(user_id, content["audio"], caption=content.get("caption", ""), parse_mode="HTML", reply_markup=final_buttons)
                elif content_type == "voice":
                    await bot.send_voice(user_id, content["voice"], reply_markup=final_buttons)
                elif content_type == "video_note":
                    await bot.send_video_note(user_id, content["video_note"], reply_markup=final_buttons)
                elif content_type == "sticker":
                    await bot.send_sticker(user_id, content["sticker"], reply_markup=final_buttons)
                elif content_type == "animation":
                    await bot.send_animation(user_id, content["animation"], caption=content.get("caption", ""), parse_mode="HTML", reply_markup=final_buttons)
                elif content_type == "location":
                    await bot.send_location(user_id, content["latitude"], content["longitude"], reply_markup=final_buttons)
                elif content_type == "contact":
                    await bot.send_contact(user_id, content["phone_number"], content["first_name"], last_name=content.get("last_name"), reply_markup=final_buttons)
                elif content_type == "media_group":
                    # Отправляем медиагруппу
                    media_list = []
                    for media_item in state["media_group"]:
                        if media_item["type"] == "photo":
                            from aiogram.types import InputMediaPhoto
                            media = InputMediaPhoto(media=media_item["media"], caption=media_item.get("caption", ""))
                        elif media_item["type"] == "video":
                            from aiogram.types import InputMediaVideo
                            media = InputMediaVideo(media=media_item["media"], caption=media_item.get("caption", ""))
                        media_list.append(media)
                    
                    await bot.send_media_group(user_id, media_list)
                    
                    # Отправляем кнопки отдельным сообщением для медиагруппы
                    if final_buttons:
                        await bot.send_message(user_id, "👆", reply_markup=final_buttons)
                
                success_count += 1
            except Exception as e:
                logging.error(f"Error sending broadcast to {user_id}: {e}")
                error_count += 1
        
        # Отправляем рассылку с прогрессом
        for i, user_id in enumerate(users):
            await send_to_user(user_id)
            
            # Обновляем прогресс каждые 50 пользователей
            if (i + 1) % 50 == 0:
                progress = f"📤 <b>Отправляю рассылку...</b>\n\n👥 Прогресс: {i + 1}/{len(users)}\n✅ Успешно: {success_count}\n❌ Ошибок: {error_count}"
                try:
                    await callback.message.edit_text(progress, parse_mode="HTML")
                except:
                    pass
            
            # Небольшая задержка
            await asyncio.sleep(0.05)
        
        # Финальный отчет
        await callback.message.edit_text(
            f"🎉 <b>Рассылка завершена!</b>\n\n"
            f"👥 Всего пользователей: {len(users)}\n"
            f"✅ Успешно отправлено: {success_count}\n"
            f"❌ Ошибок: {error_count}\n\n"
            f"📊 Успешность: {round((success_count / len(users)) * 100, 1)}%",
            parse_mode="HTML"
        )
        
        # Очищаем состояние
        broadcast_state.pop(callback.from_user.id, None)
        return
    
    elif data.startswith("favorite_"):
        _, season, episode = data.split("_")
        season, episode = int(season), int(episode)
        key = f"{season}_{episode}"
        stats.setdefault("favorites", {})
        user_favs = stats["favorites"].get(user_id, [])
        if key not in user_favs:
            user_favs.append(key)
            stats["favorites"][user_id] = user_favs
            save_stats(stats)
        is_favorite = True
        await callback.message.edit_reply_markup(reply_markup=get_favorite_keyboard(season, episode, is_favorite))
        await callback.answer("Добавлено в избранное!", show_alert=False)
        return
    elif data.startswith("unfavorite_"):
        _, season, episode = data.split("_")
        season, episode = int(season), int(episode)
        key = f"{season}_{episode}"
        stats.setdefault("favorites", {})
        user_favs = stats["favorites"].get(user_id, [])
        if key in user_favs:
            user_favs.remove(key)
            stats["favorites"][user_id] = user_favs
            save_stats(stats)
        is_favorite = False
        await callback.message.edit_reply_markup(reply_markup=get_favorite_keyboard(season, episode, is_favorite))
        await callback.answer("Удалено из избранного!", show_alert=False)
        return
    elif data.startswith("lbsc_fav_"):
        _, _, season, episode = data.split("_")
        season, episode = int(season), int(episode)
        key = f"lbsc_{season}_{episode}"
        stats.setdefault("lbsc_favorites", {})
        user_favs = stats["lbsc_favorites"].get(user_id, [])
        if key not in user_favs:
            user_favs.append(key)
            stats["lbsc_favorites"][user_id] = user_favs
            save_stats(stats)
        await callback.answer("Добавлено в избранное!", show_alert=False)
        return
    
    # Обработчики для воспроизведения избранных фильмов
    elif data.startswith("play_fav_movie_"):
        movie_key = data.replace("play_fav_movie_", "")
        
        # Получаем данные фильма
        from storage import MOVIES
        movie_meta = MOVIES.get(movie_key)
        
        if not movie_meta:
            await callback.answer("❌ Фильм не найден!", show_alert=True)
            return
            
        # Проверяем, добавлен ли фильм в избранное
        from db import is_in_favorites
        is_favorited = is_in_favorites(user_id, 'movie', movie_key)
        
        # Создаем кнопку в зависимости от статуса избранного
        if is_favorited:
            fav_button = InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{movie_key}")
        else:
            fav_button = InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"fav_{movie_key}")
        
        # Отправляем видео фильма
        await callback.message.answer_video(
            video=movie_meta['file_id'],
            caption=f"🎬 <b>{movie_meta['title']}</b>\n\n{movie_meta.get('description', '')}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [fav_button],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu")]
            ]),
            parse_mode="HTML"
        )
        
        # Добавляем просмотр в статистику
        try:
            from db import add_content_view
            add_content_view(user_id, 'movie', movie_key)
        except Exception as e:
            logging.error(f"Ошибка при добавлении просмотра избранного фильма {movie_key}: {e}")
        
        await callback.answer("▶️ Воспроизведение фильма")
        return
    
    # Обработчики для воспроизведения избранных серий
    elif data.startswith("play_fav_series_"):
        episode_key = data.replace("play_fav_series_", "")
        parts = episode_key.split("_")
        
        if len(parts) < 3:
            await callback.answer("❌ Неверный формат серии!", show_alert=True)
            return
            
        series_name = parts[0]
        season = int(parts[1])
        episode = int(parts[2])
        
        # Получаем file_id серии из базы данных
        from db import get_episode_file_id
        file_id = get_episode_file_id(series_name, season, episode)
        
        if not file_id:
            await callback.answer("❌ Серия не найдена!", show_alert=True)
            return
            
        # Проверяем, добавлена ли серия в избранное
        from db import is_in_favorites
        
        # Формируем ключ для проверки
        if series_name == "lbsc":
            check_key = f"lbsc_{season}_{episode}"
            content_type = "lbsc_series"
        else:
            check_key = f"{series_name}_{season}_{episode}"
            content_type = "series"
        
        is_favorited = is_in_favorites(user_id, content_type, check_key)
        
        # Получаем отображаемое имя сериала из базы данных
        from db import get_series_info
        series_info = get_series_info(series_name)
        if series_info:
            series_display_name = series_info["title"]
        else:
            # Fallback на старые названия
            series_display_names = {
                "rickandmorty": "Рик и Морти",
                "phf": "Финес и Ферб", 
                "lbsc": "Леди Баг и Супер-Кот"
            }
            series_display_name = series_display_names.get(series_name, series_name)
        
        # Создаем кнопку в зависимости от статуса избранного
        if is_favorited:
            fav_button = InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{check_key}")
        else:
            fav_button = InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"{series_name}_fav_{season}_{episode}")
        
        # Отправляем видео серии
        await callback.message.answer_video(
            video=file_id,
            caption=f"📺 <b>{series_display_name}</b>\nСезон {season}, Серия {episode}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [fav_button],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu")]
            ]),
            parse_mode="HTML"
        )
        
        # Добавляем просмотр избранной серии в статистику
        try:
            from db import add_content_view
            episode_key = f"{series_name}_{season}_{episode}"
            add_content_view(user_id, 'episode', episode_key)
            # Также добавляем просмотр сериала в целом
            add_content_view(user_id, 'series', series_name)
        except Exception as e:
            logging.error(f"Ошибка при добавлении просмотра избранной серии {series_name} S{season}E{episode}: {e}")
        
        await callback.answer("▶️ Воспроизведение серии")
        return
    
    # Обработчики для кнопок "В избранное" фильмов
    elif data.startswith("fav_"):
        # Проверяем премиум статус (админ может все)
        if user_id not in ADMIN_IDS and not is_premium_user(user_id):
            await callback.answer("🔒 Функция доступна только для премиум пользователей! Пригласите 2 друзей.", show_alert=True)
            return
            
        movie_key = data.replace("fav_", "")
        from db import add_to_favorites
        
        # Добавляем фильм в избранное
        added = add_to_favorites(user_id, 'movie', movie_key)
        
        if added:
            # Обновляем кнопку на "Добавлено"
            try:
                current_keyboard = callback.message.reply_markup
                if current_keyboard and current_keyboard.inline_keyboard:
                    new_keyboard = []
                    for row in current_keyboard.inline_keyboard:
                        new_row = []
                        for button in row:
                            if button.callback_data == f"fav_{movie_key}":
                                new_row.append(InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{movie_key}"))
                            else:
                                new_row.append(button)
                        new_keyboard.append(new_row)
                    
                    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard))
            except Exception:
                pass  # Игнорируем ошибки редактирования
                
            await callback.answer("⭐️ Фильм добавлен в избранное!", show_alert=False)
        else:
            await callback.answer("⭐️ Фильм уже в избранном!", show_alert=False)
        return
    
    # Обработчики для кнопок "В избранное" серий (универсальные)
    elif "_fav_" in data and not data.startswith("already_fav_"):
        # Проверяем премиум статус (админ может все)
        if user_id not in ADMIN_IDS and not is_premium_user(user_id):
            await callback.answer("🔒 Функция доступна только для премиум пользователей! Пригласите 2 друзей.", show_alert=True)
            return
            
        parts = data.split("_fav_")
        series_key = parts[0]
        season_episode = parts[1].split("_")
        
        # Проверяем, что season и episode являются числами
        try:
            season, episode = int(season_episode[0]), int(season_episode[1])
        except (ValueError, IndexError):
            await callback.answer("❌ Неверный формат серии!", show_alert=True)
            return
        
        from db import add_to_favorites
        
        # Формируем ключ в зависимости от сериала
        if series_key == "lbsc":
            check_key = f"lbsc_{season}_{episode}"
            content_type = "lbsc_series"
        else:
            check_key = f"{series_key}_{season}_{episode}"
            content_type = "series"
        
        # Добавляем серию в избранное
        added = add_to_favorites(user_id, content_type, check_key)
        
        if added:
            # Обновляем кнопку на "Добавлено"
            try:
                current_keyboard = callback.message.reply_markup
                if current_keyboard and current_keyboard.inline_keyboard:
                    new_keyboard = []
                    for row in current_keyboard.inline_keyboard:
                        new_row = []
                        for button in row:
                            if button.callback_data == f"{series_key}_fav_{season}_{episode}":
                                new_row.append(InlineKeyboardButton(text="⭐️ Добавлено", callback_data=f"already_fav_{check_key}"))
                            else:
                                new_row.append(button)
                        new_keyboard.append(new_row)
                    
                    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard))
            except Exception:
                pass  # Игнорируем ошибки редактирования
                
            await callback.answer("⭐️ Серия добавлена в избранное!", show_alert=False)
        else:
            await callback.answer("⭐️ Серия уже в избранном!", show_alert=False)
        return
    

    # Обработчик для кнопок "Добавлено" - удаление из избранного
    elif data.startswith("already_fav_"):
        # Проверяем премиум статус (админ может все) 
        if user_id not in ADMIN_IDS and not is_premium_user(user_id):
            await callback.answer("🔒 Функция доступна только для премиум пользователей!", show_alert=True)
            return
            
        item_key = data.replace("already_fav_", "")
        from db import remove_from_favorites
        
        # Добавляем логирование для отладки
        logging.info(f"Trying to remove from favorites: user_id={user_id}, item_key={item_key}")
        
        # Определяем тип контента и удаляем из соответствующего списка
        removed = False
        content_type = "movie"  # По умолчанию
        
        # Проверяем, это фильм или серия по формату ключа
        # Серии имеют формат: series_season_episode (например: rm_1_2, gf_1_1, wnd_1_1)
        # Фильмы имеют другие форматы (например: avatar_2, tran_7, p_parni2)
        
        # Проверяем по количеству подчеркиваний и известным префиксам серий
        parts = item_key.split("_")
        
        if (len(parts) >= 3 or 
            item_key.startswith("rm_") or 
            item_key.startswith("gf_") or 
            item_key.startswith("sp_") or 
            item_key.startswith("fg_") or
            item_key.startswith("wnd_") or
            item_key.startswith("homes_") or
            item_key.startswith("lbsc_") or
            item_key.startswith("phf_")):
            # Это серия
            content_type = "series"
            logging.info(f"Removing series: {item_key}")
            removed = remove_from_favorites(user_id, "series", item_key)
        else:
            # Это фильм
            content_type = "movie"
            logging.info(f"Removing movie: {item_key}")
            removed = remove_from_favorites(user_id, "movie", item_key)
        
        logging.info(f"Removal result: {removed}")
        
        if removed:
            # Обновляем кнопку обратно на "В избранное"
            try:
                current_keyboard = callback.message.reply_markup
                if current_keyboard and current_keyboard.inline_keyboard:
                    new_keyboard = []
                    for row in current_keyboard.inline_keyboard:
                        new_row = []
                        for button in row:
                            if button.callback_data == f"already_fav_{item_key}":
                                if content_type == "movie":
                                    new_row.append(InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"fav_{item_key}"))
                                else:
                                    # For series, need to reconstruct the original callback
                                    parts = item_key.split("_")
                                    if len(parts) >= 3:
                                        series_key, season, episode = parts[0], parts[1], parts[2]
                                        new_row.append(InlineKeyboardButton(text="⭐️ В избранное", callback_data=f"{series_key}_fav_{season}_{episode}"))
                                    else:
                                        new_row.append(button)  # Fallback
                            else:
                                new_row.append(button)
                        new_keyboard.append(new_row)
                    
                    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard))
            except Exception:
                pass  # Игнорируем ошибки редактирования
                
            content_name = "фильм" if content_type == "movie" else "серия"
            await callback.answer(f"❌ {content_name.capitalize()} удален из избранного!", show_alert=False)
        else:
            await callback.answer("❌ Контент не найден в избранном!", show_alert=True)
        return
    
    # Обработчики для меню избранного
    elif data == "favorites_movies":
        # Проверяем премиум статус (админ может все)
        if user_id not in ADMIN_IDS and not is_premium_user(user_id):
            await callback.answer("🔒 Функция доступна только для премиум пользователей!", show_alert=True)
            return
            
        from db import get_user_favorites
        user_favs = get_user_favorites(user_id, 'movie')
        
        if not user_favs:
            text = "🎬 <b>Избранные фильмы</b>\n\nУ вас пока нет избранных фильмов."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к избранному", callback_data="back_to_saved")],
                [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
            ])
        else:
            from storage import MOVIES
            text = "🎬 <b>Избранные фильмы</b>\n\n"
            buttons = []
            
            for fav in user_favs:
                movie_key = fav['content_key']
                movie_meta = MOVIES.get(movie_key)
                if movie_meta:
                    movie_title = movie_meta.get('title', movie_key)
                    buttons.append([InlineKeyboardButton(text=f"🎬 {movie_title}", callback_data=f"play_fav_movie_{movie_key}")])
            
            # Добавляем навигационные кнопки
            buttons.extend([
                [InlineKeyboardButton(text="⬅️ Назад к избранному", callback_data="back_to_saved")],
                [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        return
    elif data == "favorites_series":
        # Проверяем премиум статус
        if user_id not in ADMIN_IDS and not is_premium_user(user_id):
            await callback.answer("🔒 Функция доступна только для премиум пользователей!", show_alert=True)
            return
            
        from db import get_user_favorites
        user_lbsc_favs = get_user_favorites(user_id, 'lbsc_series')
        user_series_favs = get_user_favorites(user_id, 'series')
        
        if not user_lbsc_favs and not user_series_favs:
            text = "📺 <b>Избранные серии</b>\n\nУ вас пока нет избранных серий."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад к избранному", callback_data="back_to_saved")],
                [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
            ])
        else:
            from db import get_series_title
            text = "📺 <b>Избранные серии</b>\n\n"
            buttons = []
            
            # Добавляем LBSC серии
            for fav in user_lbsc_favs:
                series_key = fav['content_key']
                # Парсим ключ: lbsc_season_episode
                parts = series_key.split("_")
                if len(parts) >= 3:
                    series_name = parts[0]
                    season = parts[1]
                    episode = parts[2]
                    series_title = get_series_title(series_name)
                    buttons.append([InlineKeyboardButton(text=f"📺 {series_title} S{season}E{episode}", callback_data=f"play_fav_series_{series_key}")])
            
            # Добавляем другие серии
            for fav in user_series_favs:
                series_key = fav['content_key']
                # Парсим ключ: series_season_episode
                parts = series_key.split("_")
                if len(parts) >= 3:
                    series_name = parts[0]
                    season = parts[1]
                    episode = parts[2]
                    series_title = get_series_title(series_name)
                    buttons.append([InlineKeyboardButton(text=f"📺 {series_title} S{season}E{episode}", callback_data=f"play_fav_series_{series_key}")])
            
            # Добавляем навигационные кнопки
            buttons.extend([
                [InlineKeyboardButton(text="⬅️ Назад к избранному", callback_data="back_to_saved")],
                [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        return
    elif data == "back_to_saved":
        # Проверяем премиум статус
        if user_id not in ADMIN_IDS and not is_premium_user(user_id):
            await callback.answer("🔒 Функция доступна только для премиум пользователей!", show_alert=True)
            return
            
        from db import get_favorites_count
        
        # Подсчитываем количество избранных фильмов и серий
        movies_count = get_favorites_count(user_id, 'movie')
        lbsc_series_count = get_favorites_count(user_id, 'lbsc_series')
        other_series_count = get_favorites_count(user_id, 'series')
        series_count = lbsc_series_count + other_series_count
        
        text = (
            "<b><i>⭐️Ваши избранные серии:</i></b>\n\n"
            f"Вы добавили фильмов: {movies_count}\n"
            f"<b>Вы добавили серий: {series_count}</b>\n\n"
            "<b><i>Нажмите, в какой раздел хотите зайти:</i></b>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎬 Фильмы", callback_data="favorites_movies"),
                InlineKeyboardButton(text="📺 Серии", callback_data="favorites_series")
            ],
            [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
        ])
        
        await bot.send_message(callback.from_user.id, text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        return
       # Возврат в главное меню
    elif data == "back_to_main_menu":
        # Выключаем режим тех.поддержки при возврате в главное меню
        if callback.from_user.id in tech_support_state:
            del tech_support_state[callback.from_user.id]
        if callback.from_user.id in waiting_for_admin_message:
            del waiting_for_admin_message[callback.from_user.id]
            
        # Возврат в главное меню - используем тот же текст что и в /start
        text = (
            "Привет!👋\n\n"
            "<i>Ты попал в кино-бот!</i> <b>У нас большая коллекция фильмов и сериалов на любой вкус!</b>🎥\n\n"
            "<b><i>Что бы ознакомиться с ботом, нажми /help либо \"Помощь\".</i></b>\n\n"
            "Нажми на \"Начать поиск\" и приятного тебе <b>просмотра!</b>"
        )
        await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
        await callback.answer()
        return
    elif data == "help_menu":
        # Показать помощь - отправляем новое сообщение
        text = (
            "Привет! В этом сообщении я научу тебя пользоваться ботом!\n"
            "😊 И отвечу на самые задаваемые вопросы! ❤️\n\n"
            "Для того, что бы, посмотреть фильм и/или сериал вам нужно "
            "нажать на /start→ \"Начать поиск\" после чего вы пишите, что "
            f"хотите посмотреть. Пример: @{BOT_USERNAME} tor canorax\n\n"
            "Коллекция фильмов постоянно пополняется. С каждым днем. С каждой минутой. "
            "С каждой секундой. Если вашего любимого фильма нет, не стоит унывать! "
            "Вы можете предложить его нажав на /start и \"Связаться с админом\". "
            "Не бойтесь писать! Админ вас не укусит!"
        )
        await bot.send_message(callback.from_user.id, text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
        await callback.answer()
        return
    
    # Обработчик кнопки "Реферальная система"
    elif data == "ref_system":
        user_id = callback.from_user.id
        
        # Сохраняем пользователя в БД
        save_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
            callback.from_user.last_name,
            callback.from_user.language_code,
            callback.from_user.is_bot
        )
        
        # Получаем количество рефералов
        referrals_count = get_referrals_count(user_id)
        
        # Создаем реферальную ссылку
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        
        # Определяем статус пользователя
        if is_premium_user(user_id) or user_id in ADMIN_IDS:
            status = "🍬 Премиум пользователь"
        else:
            status = "👤 Обычный пользователь"
        
        text = (
            f"Привет, это реферальная система.\n\n"
            f"Вам нужно пригласить как минимум 2 человек, что бы приобрести так называемый премиум-статус на 7 дней🤑\n\n"
            f"Премиум-статус даёт:\n"
            f"• Безлимитный просмотр фильмов и сериалов\n\n"
            f"Ваша реферальная ссылка: {ref_link}\n"
            f"Вы пригласили людей: {referrals_count}/2\n\n"
            f"Скопируй ссылку выше и отправь ее друзьям для получения бонусов!\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💎 Или купите премиум прямо сейчас:\n"
            f"• 50 ⭐️ — Премиум на 2 месяца\n"
            f"• 200 ⭐️ — Премиум на год"
        )
        
        ref_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu")]
        ])
        
        await bot.send_message(callback.from_user.id, text, reply_markup=ref_keyboard, parse_mode="HTML")
        await callback.answer("💰 Открыта реферальная система")
        return
    
    elif data == "premium_users":
        # Для обычных пользователей отправляем новое сообщение со списком премиум пользователей
        premium_users = get_premium_users()
        
        if not premium_users:
            text = "🍬 <b>Премиум пользователи</b>\n\nПока что никто не достиг премиум-статуса.\nСтаньте первым, пригласив 2+ друзей!"
        else:
            text = "🍬 <b>Премиум пользователи</b>\n\nПользователи, которые пригласили 2+ друзей:\n\n"
            
            for i, user in enumerate(premium_users, 1):
                username = user['username']
                first_name = user['first_name'] or "Пользователь"
                referrals_count = user['referrals_count']
                
                if username:
                    text += f"{i}. @{username} ({first_name}) - {referrals_count} рефералов\n"
                else:
                    text += f"{i}. {first_name} - {referrals_count} рефералов\n"
        
        premium_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Реферальная система", callback_data="ref_system")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu")]
        ])
        
        await bot.send_message(callback.from_user.id, text, reply_markup=premium_keyboard, parse_mode="HTML")
        await callback.answer("🍬 Открыт список премиум пользователей")
        return
    
    
    elif data == "back_to_saved":
        # Для обычных пользователей отправляем новое сообщение с избранным
        # Проверяем премиум статус
        user_id_int = int(user_id)
        if user_id_int not in ADMIN_IDS and not is_premium_user(user_id_int):
            await callback.answer("🔒 Функция доступна только для премиум пользователей!", show_alert=True)
            return
        
        text = (
            "⭐️ <b>Избранное</b>\n\n"
            "Выберите категорию:"
        )
        
        favorites_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎬 Фильмы", callback_data="saved_movies")],
            [InlineKeyboardButton(text="📺 Сериалы", callback_data="saved_series")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main_menu")]
        ])
        
        await bot.send_message(callback.from_user.id, text, reply_markup=favorites_keyboard, parse_mode="HTML")
        await callback.answer("⭐️ Открыто избранное")
        return
# === Обработчик специальных кодов фильмов (ДОЛЖЕН БЫТЬ ВЫШЕ ОБЩЕГО ОБРАБОТЧИКА) ===
@router.message(F.text.startswith("/movie_"))
async def handle_movie_code(message: Message):
    """Обработчик специальных кодов фильмов из инлайн поиска"""
    logging.info(f"[handle_movie_code] Processing movie code: {message.text}")
    
    
    movie_key = message.text.split("/movie_", 1)[1]
    meta = MOVIES.get(movie_key)
    if not meta:
        await message.reply("❌ Фильм не найден")
        return
    
    caption = f"<b>{meta['title']}</b>"
    
    try:
        poster_url = meta.get('poster_url') or meta.get('thumb_url')
        
        # Создаем простую клавиатуру без кнопки качества (качество выбирается в самом видео)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Смотреть в боте", callback_data=f"movie_play_{movie_key}")],
            [InlineKeyboardButton(text="🔎 Начать поиск", switch_inline_query_current_chat="")]
        ])
        if poster_url:
            await message.answer_photo(
                photo=poster_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                text=caption,
                parse_mode="HTML", 
                reply_markup=keyboard
            )
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        await message.reply("❌ Не удалось отправить информацию о фильме")
        logging.error(f"Error sending movie info {movie_key}: {e}")

# === Обработчик специальных кодов сериалов ===
@router.message(F.text.startswith("/series_"))
async def handle_series_code(message: Message):
    """Обработчик специальных кодов сериалов из инлайн поиска"""
    logging.info(f"[handle_series_code] Processing series code: {message.text}")
    
    
    series_key = message.text.split("/series_", 1)[1]
    
    # Получаем информацию о сериале
    all_series = get_all_available_series()
    series_info = None
    for s in all_series:
        if s["key"] == series_key:
            series_info = s
            break
    
    if not series_info:
        await message.reply("❌ Сериал не найден")
        return
    
    title = series_info["title"]
    caption = f"<b>{title}</b>"
    
    try:
        # Получаем постер сериала
        poster_url = None
        if series_key in SERIES_POSTERS:
            poster_data = SERIES_POSTERS[series_key]
            if isinstance(poster_data, dict):
                poster_url = poster_data.get('show') or poster_data.get(max(poster_data.keys()) if poster_data else None)
            else:
                poster_url = poster_data
        
        # Создаем меню с основными кнопками
        main_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Смотреть в боте", callback_data=f"series_watch_{series_key}")],
            [InlineKeyboardButton(text="🔎 Начать поиск", switch_inline_query_current_chat="")]
        ])
        
        # Отправляем первое сообщение с постером и основными кнопками
        if poster_url:
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=poster_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=main_keyboard
            )
        else:
            await bot.send_message(
                chat_id=message.chat.id,
                text=caption,
                parse_mode="HTML", 
                reply_markup=main_keyboard
            )
        
            
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        await message.reply("❌ Не удалось отправить информацию о сериале")
        logging.error(f"Error sending series info {series_key}: {e}")


# === Vibix: открыть мини‑приложение для фильма ===
@router.message(F.text.startswith("/vibix_movie_"))
async def handle_vibix_movie(message: Message):
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    code = message.text.split("/vibix_movie_", 1)[1]
    from vibix_api import vibix_api
    iframe = None
    data = None
    
    # Пытаемся получить данные о фильме по KP/IMDB/ID
    try:
        if code.startswith("tt"):
            data = await vibix_api.get_by_imdb(code)
        elif code.isdigit():
            data = await vibix_api.get_by_kp(int(code))
            if not data:
                # возможно это внутренний id, найдём его в списке
                page = await vibix_api.list_links(limit=50)
                if page and page.get('data'):
                    for item in page['data']:
                        if str(item.get('id')) == code:
                            data = item
                            break
        if data and data.get('iframe_url'):
            iframe = data['iframe_url']
    except Exception:
        iframe = None

    # Получаем информацию о фильме для красивого отображения
    title = "Неизвестный фильм"
    poster_url = None
    
    if data:
        title = data.get('name_rus') or data.get('name') or title
        poster_url = data.get('poster_url')
        # logging.info(f"[VIBIX_MOVIE] Данные от Vibix API: title='{title}', poster_url='{poster_url}'")
        # logging.info(f"[VIBIX_MOVIE] Все поля data: {list(data.keys()) if data else 'None'}")
    
    # Получаем дополнительную информацию (рейтинги и жанры) из Vibix API
    movie_info = {}
    if data:
        # Используем данные напрямую из Vibix API
        movie_info = {
            'rating_kp': data.get('kp_rating'),
            'rating_imdb': data.get('imdb_rating'),
            'genres': data.get('genre', []),
            'year': data.get('year'),
            'description': data.get('description') or data.get('description_short'),
            'quality': data.get('quality'),
            'country': data.get('country', []),
            'duration': data.get('duration')
        }
        # logging.info(f"[VIBIX_MOVIE] Информация из Vibix API для {title}: {movie_info}")
    
    # Добавляем просмотр в статистику (засчитываем при открытии меню)
    # Это нужно делать ДО проверки лимита, чтобы счетчик увеличился
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS and not is_premium_user(user_id):
        try:
            from db import add_content_view
            movie_key = f"vibix_{code}"
            add_content_view(user_id, 'movie', movie_key)
            logging.info(f"[VIBIX_MOVIE] Просмотр фильма {movie_key} добавлен в статистику для пользователя {user_id}")
        except Exception as e:
            logging.error(f"Ошибка при добавлении просмотра фильма {movie_key}: {e}")
    
    # Генерируем безопасную ссылку для мини-приложения
    # Передаем iframe_url и данные о фильме
    enhanced_movie_data = data.copy() if data else {}
    
    # Добавляем постер если есть
    if poster_url:
        enhanced_movie_data['poster_url'] = poster_url
    
    # Добавляем информацию из movie_info_api
    if movie_info:
        # Рейтинги
        if movie_info.get('rating_kp'):
            enhanced_movie_data['kp_rating'] = movie_info['rating_kp']
        if movie_info.get('rating_imdb'):
            enhanced_movie_data['imdb_rating'] = movie_info['rating_imdb']
        
        # Жанры
        if movie_info.get('genres'):
            enhanced_movie_data['genres'] = movie_info['genres']
        
        # Год
        if movie_info.get('year'):
            enhanced_movie_data['year'] = movie_info['year']
        
        # Описание
        if movie_info.get('description'):
            enhanced_movie_data['description'] = movie_info['description']
        
        # Дополнительная информация
        if movie_info.get('quality'):
            enhanced_movie_data['quality'] = movie_info['quality']
        if movie_info.get('country'):
            enhanced_movie_data['country'] = movie_info['country']
        if movie_info.get('duration'):
            enhanced_movie_data['duration'] = movie_info['duration']
    
    secure_url = await generate_secure_miniapp_url(
        message.from_user.id, 
        'movie', 
        code, 
        iframe_url=enhanced_movie_data.get('iframe_url'),
        movie_data=enhanced_movie_data
    )
    
    # Создаем красивое меню с кнопками
    if secure_url:
        buttons = [
            [InlineKeyboardButton(text="▶️ Смотреть", web_app=WebAppInfo(url=secure_url))],
            [InlineKeyboardButton(text="🔎 Начать поиск", switch_inline_query_current_chat="")]
        ]
    else:
        # Лимит превышен - показываем информацию о лимитах
        limits_info = get_user_limits_info(message.from_user.id)
        buttons = [
            [InlineKeyboardButton(text=f"🚫 Лимит превышен ({limits_info['daily_used']}/{limits_info['daily_limit']})", callback_data="show_limits")],
            [InlineKeyboardButton(text="💎 Получить премиум", callback_data="ref_system")],
            [InlineKeyboardButton(text="🔎 Начать поиск", switch_inline_query_current_chat="")]
        ]
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # Формируем красивое описание с дополнительными данными
    text_parts = [f"🎬 <b>{title}</b>"]
    
    # Добавляем рейтинги
    ratings = []
    if movie_info.get('rating_kp'):
        try:
            kp_rating = float(movie_info['rating_kp'])
            if kp_rating > 0:
                ratings.append(f"КП: {kp_rating}")
        except (ValueError, TypeError):
            pass
    
    if movie_info.get('rating_imdb'):
        try:
            imdb_rating = float(movie_info['rating_imdb'])
            if imdb_rating > 0:
                ratings.append(f"IMDb: {imdb_rating}")
        except (ValueError, TypeError):
            pass
    
    if ratings:
        text_parts.append(f"⭐ {' | '.join(ratings)}")
    
    # Добавляем год и жанры
    details = []
    if movie_info.get('year'):
        details.append(str(movie_info['year']))
    
    if movie_info.get('genres') and isinstance(movie_info['genres'], list):
        genres_text = ', '.join(movie_info['genres'][:3])  # Первые 3 жанра
        details.append(genres_text)
    
    if details:
        text_parts.append(f"📅 {' | '.join(details)}")
    
    # Добавляем страну и качество
    extra_info = []
    if movie_info.get('country') and isinstance(movie_info['country'], list):
        countries = ', '.join(movie_info['country'][:2])  # Первые 2 страны
        extra_info.append(f"🌍 {countries}")
    
    if movie_info.get('quality'):
        extra_info.append(f"📺 {movie_info['quality']}")
    
    if movie_info.get('duration'):
        extra_info.append(f"⏱️ {movie_info['duration']} мин")
    
    if extra_info:
        text_parts.append(' | '.join(extra_info))
    
    # Добавляем описание
    if movie_info.get('description'):
        description = movie_info['description']
        # Ограничиваем длину описания
        if len(description) > 300:
            description = description[:297] + "..."
        text_parts.append(f"\n📖 {description}")
    
    text_parts.append("\nВыберите действие:")
    text = '\n'.join(text_parts)
    
    if poster_url:
        try:
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=poster_url,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception:
            # Если не удалось отправить фото, отправляем текст
            await bot.send_message(
                chat_id=message.chat.id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )


# === Vibix: открыть мини‑приложение для сериала ===
@router.message(F.text.startswith("/vibix_series_"))
async def handle_vibix_series(message: Message):
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    code = message.text.split("/vibix_series_", 1)[1]
    from vibix_api import vibix_api
    iframe = None
    data = None
    
    # Пытаемся получить данные о сериале по KP/IMDB/ID
    try:
        if code.startswith("tt"):
            data = await vibix_api.get_by_imdb(code)
        elif code.isdigit():
            data = await vibix_api.get_by_kp(int(code))
            if not data:
                page = await vibix_api.list_links(type_='serial', limit=50)
                if page and page.get('data'):
                    for item in page['data']:
                        if str(item.get('id')) == code:
                            data = item
                            break
        if data and data.get('iframe_url'):
            iframe = data['iframe_url']
    except Exception:
        iframe = None

    # Получаем информацию о сериале для красивого отображения
    title = "Неизвестный сериал"
    poster_url = None
    
    if data:
        title = data.get('name_rus') or data.get('name') or title
        poster_url = data.get('poster_url')
        # logging.info(f"[VIBIX_SERIES] Данные от Vibix API: title='{title}', poster_url='{poster_url}'")
        # logging.info(f"[VIBIX_SERIES] Все поля data: {list(data.keys()) if data else 'None'}")
    
    # Получаем дополнительную информацию (рейтинги и жанры) из Vibix API
    movie_info = {}
    if data:
        # Используем данные напрямую из Vibix API
        movie_info = {
            'rating_kp': data.get('kp_rating'),
            'rating_imdb': data.get('imdb_rating'),
            'genres': data.get('genre', []),
            'year': data.get('year'),
            'description': data.get('description') or data.get('description_short'),
            'quality': data.get('quality'),
            'country': data.get('country', []),
            'duration': data.get('duration')
        }
        # logging.info(f"[VIBIX_SERIES] Информация из Vibix API для {title}: {movie_info}")
    
    # Генерируем безопасную ссылку для мини-приложения
    enhanced_movie_data = data.copy() if data else {}
    
    # Добавляем постер если есть
    if poster_url:
        enhanced_movie_data['poster_url'] = poster_url
    
    # Добавляем информацию из movie_info_api
    if movie_info:
        # Рейтинги
        if movie_info.get('rating_kp'):
            enhanced_movie_data['kp_rating'] = movie_info['rating_kp']
        if movie_info.get('rating_imdb'):
            enhanced_movie_data['imdb_rating'] = movie_info['rating_imdb']
        
        # Жанры
        if movie_info.get('genres'):
            enhanced_movie_data['genres'] = movie_info['genres']
        
        # Год
        if movie_info.get('year'):
            enhanced_movie_data['year'] = movie_info['year']
        
        # Описание
        if movie_info.get('description'):
            enhanced_movie_data['description'] = movie_info['description']
        
        # Дополнительная информация
        if movie_info.get('quality'):
            enhanced_movie_data['quality'] = movie_info['quality']
        if movie_info.get('country'):
            enhanced_movie_data['country'] = movie_info['country']
        if movie_info.get('duration'):
            enhanced_movie_data['duration'] = movie_info['duration']
    
    secure_url = await generate_secure_miniapp_url(
        message.from_user.id, 
        'episode', 
        code, 
        iframe_url=iframe,  # Передаем правильный iframe_url
        movie_data=enhanced_movie_data
    )
    
    # Создаем красивое меню с кнопками
    if secure_url:
        buttons = [
            [InlineKeyboardButton(text="▶️ Смотреть", web_app=WebAppInfo(url=secure_url))],
            [InlineKeyboardButton(text="🔎 Начать поиск", switch_inline_query_current_chat="")]
        ]
    else:
        # Лимит превышен - показываем информацию о лимитах
        limits_info = get_user_limits_info(message.from_user.id)
        buttons = [
            [InlineKeyboardButton(text=f"🚫 Лимит превышен ({limits_info['daily_used']}/{limits_info['daily_limit']})", callback_data="show_limits")],
            [InlineKeyboardButton(text="💎 Получить премиум", callback_data="ref_system")],
            [InlineKeyboardButton(text="🔎 Начать поиск", switch_inline_query_current_chat="")]
        ]
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # Формируем красивое описание с дополнительными данными
    text_parts = [f"📺 <b>{title}</b>"]
    
    # Добавляем рейтинги
    ratings = []
    if movie_info.get('rating_kp'):
        try:
            kp_rating = float(movie_info['rating_kp'])
            if kp_rating > 0:
                ratings.append(f"КП: {kp_rating}")
        except (ValueError, TypeError):
            pass
    
    if movie_info.get('rating_imdb'):
        try:
            imdb_rating = float(movie_info['rating_imdb'])
            if imdb_rating > 0:
                ratings.append(f"IMDb: {imdb_rating}")
        except (ValueError, TypeError):
            pass
    
    if ratings:
        text_parts.append(f"⭐ {' | '.join(ratings)}")
    
    # Добавляем год и жанры
    details = []
    if movie_info.get('year'):
        details.append(str(movie_info['year']))
    
    if movie_info.get('genres') and isinstance(movie_info['genres'], list):
        genres_text = ', '.join(movie_info['genres'][:3])  # Первые 3 жанра
        details.append(genres_text)
    
    if details:
        text_parts.append(f"📅 {' | '.join(details)}")
    
    # Добавляем страну и качество
    extra_info = []
    if movie_info.get('country') and isinstance(movie_info['country'], list):
        countries = ', '.join(movie_info['country'][:2])  # Первые 2 страны
        extra_info.append(f"🌍 {countries}")
    
    if movie_info.get('quality'):
        extra_info.append(f"📺 {movie_info['quality']}")
    
    if extra_info:
        text_parts.append(' | '.join(extra_info))
    
    # Добавляем описание
    if movie_info.get('description'):
        description = movie_info['description']
        # Ограничиваем длину описания
        if len(description) > 300:
            description = description[:297] + "..."
        text_parts.append(f"\n📖 {description}")
    
    text_parts.append("\nВыберите действие:")
    text = '\n'.join(text_parts)
    
    if poster_url:
        try:
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=poster_url,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception:
            # Если не удалось отправить фото, отправляем текст
            await bot.send_message(
                chat_id=message.chat.id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )

@router.message(~F.text.startswith('/'))
async def handle_messages(message: Message):
    
    # Сохраняем информацию о пользователе
    from db import save_user
    user = message.from_user
    if user:
        save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
            is_bot=user.is_bot
        )
    
    if not message.text:
        return
    
    # Обработка поиска контента для закрепа
    user_id = message.from_user.id
    if (user_id in pin_manager_states and 
        pin_manager_states[user_id].get('step') == 'waiting_search' and
        user_id in ADMIN_IDS):
        
        state = pin_manager_states[user_id]
        content_type = state['content_type']
        search_query = message.text.strip()
        
        if len(search_query) < 2:
            await message.reply("❌ Запрос слишком короткий. Введите минимум 2 символа.")
            return
        
        try:
            # Ищем контент
            results = await search_content_by_key(content_type, search_query, limit=10)
            
            if not results:
                type_name = "фильмов" if content_type == "movie" else "сериалов"
                await message.reply(
                    f"❌ По запросу '<b>{search_query}</b>' {type_name} не найдено.\n"
                    f"Попробуйте другой запрос.",
                    parse_mode="HTML"
                )
                return
            
            # Показываем результаты
            type_name = "фильмов" if content_type == "movie" else "сериалов"
            text = (
                f"🔍 <b>Результаты поиска {type_name}</b>\n"
                f"По запросу: <b>{search_query}</b>\n\n"
                f"Найдено: {len(results)} результат(ов)\n"
                f"Выберите контент для добавления в закреп:"
            )
            
            keyboard = get_search_results_keyboard(results, content_type)
            await message.reply(text, parse_mode="HTML", reply_markup=keyboard)
            
            # Очищаем состояние
            del pin_manager_states[user_id]
            return
            
        except Exception as e:
            await message.reply(f"❌ Ошибка поиска: {e}")
            del pin_manager_states[user_id]
            return
    
    # Проверяем, является ли это ответом админа пользователю
    if message.from_user and message.from_user.id in ADMIN_IDS and any(waiting_admin_reply.get(admin_id) for admin_id in ADMIN_IDS):
        target_id = None
        admin_reply_id = None
        for admin_id in ADMIN_IDS:
            if waiting_admin_reply.get(admin_id):
                target_id = waiting_admin_reply.pop(admin_id, None)
                admin_reply_id = admin_id
                break
        if target_id:
            try:
                if message.text:
                    await bot.send_message(target_id, f"📩 <b>Ответ от администратора:</b>\n\n{message.text}", parse_mode="HTML")
                    await message.reply("✅ Ваш ответ отправлен пользователю!")
                    logging.info(f"[ADMIN_REPLY] Admin {admin_reply_id} replied to user {target_id}: {message.text[:50]}...")
                    return
            except Exception as e:
                await message.reply(f"❌ Ошибка отправки ответа: {e}")
                logging.error(f"[ADMIN_REPLY_ERROR] Failed to send admin reply: {e}")
                return
    
    # === Обработка состояний рассылки ===
    if message.from_user.id in broadcast_state and broadcast_state[message.from_user.id].get("step") in ["content", "custom_button"]:
        state = broadcast_state[message.from_user.id]
        
        if state["step"] == "content":
            # Универсальная обработка любого типа контента
            content_saved = False
            
            if message.text:
                logging.info(f"Admin {message.from_user.id} sending text broadcast: {message.text[:50]}...")
                state["type"] = "text"
                state["content"] = {"text": message.text}
                content_saved = True
                
            elif message.photo:
                logging.info(f"Admin {message.from_user.id} sending photo broadcast.")
                # Проверяем, является ли это частью медиагруппы
                if message.media_group_id:
                    # Добавляем в медиагруппу
                    media_item = {
                        "type": "photo",
                        "media": message.photo[-1].file_id,
                        "caption": message.caption or ""
                    }
                    state["media_group"].append(media_item)
                    state["type"] = "media_group"
                    state["media_group_id"] = message.media_group_id
                    
                    # Ждем остальные медиафайлы из группы
                    await message.reply("📸 Фото добавлено в альбом. Отправьте остальные медиафайлы или подождите 3 секунды...")
                    
                    # Запускаем таймер для завершения медиагруппы
                    asyncio.create_task(finish_media_group_after_delay(message.from_user.id, message.media_group_id))
                    return
                else:
                    # Одиночное фото
                    state["type"] = "photo"
                    state["content"] = {
                        "photo": message.photo[-1].file_id,
                        "caption": message.caption or ""
                    }
                    content_saved = True
                    
            elif message.video:
                logging.info(f"Admin {message.from_user.id} sending video broadcast.")
                if message.media_group_id:
                    # Добавляем в медиагруппу
                    media_item = {
                        "type": "video",
                        "media": message.video.file_id,
                        "caption": message.caption or ""
                    }
                    state["media_group"].append(media_item)
                    state["type"] = "media_group"
                    state["media_group_id"] = message.media_group_id
                    
                    await message.reply("🎥 Видео добавлено в альбом. Отправьте остальные медиафайлы или подождите 3 секунды...")
                    
                    # Запускаем таймер для завершения медиагруппы
                    asyncio.create_task(finish_media_group_after_delay(message.from_user.id, message.media_group_id))
                    return
                else:
                    # Одиночное видео
                    state["type"] = "video"
                    state["content"] = {
                        "video": message.video.file_id,
                        "caption": message.caption or ""
                    }
                    content_saved = True
                    
            elif message.document:
                logging.info(f"Admin {message.from_user.id} sending document broadcast.")
                state["type"] = "document"
                state["content"] = {
                    "document": message.document.file_id,
                    "caption": message.caption or ""
                }
                content_saved = True
                
            elif message.audio:
                logging.info(f"Admin {message.from_user.id} sending audio broadcast.")
                state["type"] = "audio"
                state["content"] = {
                    "audio": message.audio.file_id,
                    "caption": message.caption or ""
                }
                content_saved = True
                
            elif message.voice:
                logging.info(f"Admin {message.from_user.id} sending voice broadcast.")
                state["type"] = "voice"
                state["content"] = {
                    "voice": message.voice.file_id,
                    "caption": message.caption or ""
                }
                content_saved = True
                
            elif message.video_note:
                logging.info(f"Admin {message.from_user.id} sending video_note broadcast.")
                state["type"] = "video_note"
                state["content"] = {
                    "video_note": message.video_note.file_id
                }
                content_saved = True
                
            elif message.sticker:
                logging.info(f"Admin {message.from_user.id} sending sticker broadcast.")
                state["type"] = "sticker"
                state["content"] = {
                    "sticker": message.sticker.file_id
                }
                content_saved = True
                
            elif message.animation:
                logging.info(f"Admin {message.from_user.id} sending animation broadcast.")
                state["type"] = "animation"
                state["content"] = {
                    "animation": message.animation.file_id,
                    "caption": message.caption or ""
                }
                content_saved = True
                
            elif message.location:
                logging.info(f"Admin {message.from_user.id} sending location broadcast.")
                state["type"] = "location"
                state["content"] = {
                    "latitude": message.location.latitude,
                    "longitude": message.location.longitude
                }
                content_saved = True
                
            elif message.contact:
                logging.info(f"Admin {message.from_user.id} sending contact broadcast.")
                state["type"] = "contact"
                state["content"] = {
                    "phone_number": message.contact.phone_number,
                    "first_name": message.contact.first_name,
                    "last_name": message.contact.last_name,
                    "user_id": message.contact.user_id
                }
                content_saved = True
                
            else:
                await message.reply(
                    "❌ Неподдерживаемый тип контента.\n\n"
                    "Поддерживаются: текст, фото, видео, документы, аудио, голосовые, стикеры, GIF, геолокация, контакты."
                )
                return
            
            if content_saved:
                # Переходим к выбору кнопок
                state["step"] = "buttons"
                await message.reply(
                    "✅ <b>Контент сохранен!</b>\n\n"
                    "Теперь выберите кнопки для добавления к сообщению или нажмите 'Готово' для предпросмотра:",
                    parse_mode="HTML",
                    reply_markup=get_broadcast_buttons_keyboard(state["selected_buttons"])
                )
            return
            
        elif state["step"] == "custom_button" and message.text:
            # Обработка пользовательской кнопки
            try:
                if "-" not in message.text:
                    await message.reply(
                        "❌ <b>Неверный формат кнопки</b>\n\n"
                        "Используйте формат:\n"
                        "<code>Текст кнопки-https://example.com</code>\n\n"
                        "Примеры:\n"
                        "<code>Наш сайт-https://example.com</code>\n"
                        "<code>Подписаться-https://t.me/channel</code>",
                        parse_mode="HTML"
                    )
                    return
                
                # Разделяем по последнему дефису
                parts = message.text.rsplit("-", 1)
                if len(parts) != 2:
                    await message.reply(
                        "❌ <b>Неверный формат кнопки</b>\n\n"
                        "Используйте формат:\n"
                        "<code>Текст кнопки-https://example.com</code>",
                        parse_mode="HTML"
                    )
                    return
                
                text, url = parts
                text = text.strip()
                url = url.strip()
                
                if not text or not url:
                    await message.reply("❌ Текст кнопки и ссылка не могут быть пустыми.")
                    return
                
                if not (url.startswith("http://") or url.startswith("https://")):
                    await message.reply("❌ Ссылка должна начинаться с http:// или https://")
                    return
                
                # Добавляем кнопку в конфигурацию
                state["button_configs"].append({
                    "text": text,
                    "url": url
                })
                
                state["step"] = "buttons"
                await message.reply(
                    f"✅ <b>Кнопка создана!</b>\n\n"
                    f"📝 Текст: {text}\n"
                    f"🔗 Ссылка: {url}\n\n"
                    "Выберите еще кнопки или нажмите 'Готово':",
                    parse_mode="HTML",
                    reply_markup=get_broadcast_buttons_keyboard(state["selected_buttons"])
                )
                return
                
            except Exception as e:
                logging.error(f"Error creating custom button: {e}")
                await message.reply("❌ Ошибка при создании кнопки. Попробуйте еще раз.")
                return
        return
    
    # === Обработка состояний добавления сериалов и фильмов ===
    if message.from_user.id in addserial_state:
        await handle_addserial_state(message)
        return
    
    if message.from_user.id in addfilm_state:
        await handle_addfilm_state(message)
        return

    # Если сообщение не текстовое, обрабатываем медиа для рассылок
    if not message.text:
        # Проверяем состояние рассылки для медиа
        if message.from_user.id in broadcast_state and broadcast_state[message.from_user.id].get("step") == "content":
            # Логика уже обработана выше
            pass
        return
    
    logging.info(f"[universal_handler] Received message from {message.from_user.id}. Text: {message.text[:50]}...")
    args = ''
    # Проверка на наличие аргументов в сообщении
    if message.text and len(message.text.split()) > 1:
        args = message.text.split()[1]
    if not args and message.text and message.text.startswith('/start '):
        args = message.text[len('/start '):].strip()
    if args.startswith("episode_"):
        try:
            _, season, episode = args.split("_")
            season = int(season)
            episode = int(episode)
            fake_callback = type('obj', (object,), {
                'data': f'episode_{season}_{episode}',
                'from_user': message.from_user,
                'message': message,
                'answer': lambda *a, **k: None,
                'chat': message.chat
            })
            await handle_callback(fake_callback)
            return
        except Exception as e:
            await message.reply(f"Ошибка при переходе по ссылке: {e}")
            return
    elif args.startswith("lbsc_episode_"):
        try:
            _, season, episode = args.split("_")
            season = int(season)
            episode = int(episode)
            fake_callback = type('obj', (object,), {
                'data': f'lbsc_episode_{season}_{episode}',
                'from_user': message.from_user,
                'message': message,
                'answer': lambda *a, **k: None,
                'chat': message.chat
            })
            await handle_callback(fake_callback)
            return
        except Exception as e:
            await message.reply(f"Ошибка при переходе по ссылке: {e}")
            return
    elif args.startswith("phf_episode_"):
        try:
            _, season, episode = args.split("_")
            season = int(season)
            episode = int(episode)
            fake_callback = type('obj', (object,), {
                'data': f'phf_episode_{season}_{episode}',
                'from_user': message.from_user,
                'message': message,
                'answer': lambda *a, **k: None,
                'chat': message.chat
            })
            await handle_callback(fake_callback)
            return
        except Exception as e:
            await message.reply(f"Ошибка при переходе по ссылке: {e}")
            return
    # Обработка сообщений для связи с админом
    if waiting_for_admin_message.get(message.from_user.id):
        waiting_for_admin_message.pop(message.from_user.id, None)
        # НЕ удаляем tech_support_state здесь - пользователь остается в режиме ожидания ответа
        header = (
            "📥 Новое сообщение для админа\n\n"
            f"От: <b>{message.from_user.first_name or ''}</b> (@{message.from_user.username or '—'})\n"
            f"ID: <code>{message.from_user.id}</code>\n\n"
            "Сообщение:" 
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Ответить пользователю", callback_data=f"reply_user_{message.from_user.id}")]])
        
        # Отправляем всем админам
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, header, parse_mode="HTML", reply_markup=kb)
                # Переслать/скопировать само сообщение (включая медиа)
                await bot.copy_message(chat_id=admin_id, from_chat_id=message.chat.id, message_id=message.message_id)
            except Exception as e:
                logging.error(f"Error sending message to admin {admin_id}: {e}")
        
        try:
            await message.answer("✅ Сообщение отправлено администратору! Ожидайте ответа здесь.")
        except Exception:
            pass
        return
    # --- Старый способ ответа по reply_to_message (оставляю на всякий случай) ---
    if message.reply_to_message and message.from_user.id == 7850455999:
        match = re.search(r"ID:</b> <code>(\d+)</code>", message.reply_to_message.text or "")
        if match:
            target_id = int(match.group(1))
            # Выключаем режим тех.поддержки у пользователя после получения ответа от админа
            if target_id in tech_support_state:
                del tech_support_state[target_id]
            await bot.send_message(target_id, f"<b>Ответ администратора:</b>\n{message.text}", parse_mode="HTML")
            await message.reply("Ответ отправлен пользователю.")
        return
    if message.video:
        if message.from_user.id in ADMIN_IDS:
            await message.reply(f"file_id для вставки в код:\n'{message.video.file_id}'\nТип: video")
    elif message.photo:
        if message.from_user.id in ADMIN_IDS:
            fid = message.photo[-1].file_id
            await message.reply(f"file_id для вставки в код:\n'{fid}'\nТип: photo")
    elif message.document:
        if message.from_user.id in ADMIN_IDS:
            await message.reply(f"file_id для вставки в код:\n'{message.document.file_id}'\nТип: document")
    # --- Логика рассылки ---
    if message.from_user.id in ADMIN_IDS and broadcast_state.get(message.from_user.id):
        logging.info(f"Admin {message.from_user.id} in broadcast state. Current step: {broadcast_state[message.from_user.id].get('step')}")
        state = broadcast_state[message.from_user.id]
        if state["step"] == "photo" and message.photo:
            logging.info(f"Admin {message.from_user.id} sending photo broadcast.")
            state["type"] = "photo"
            file_id = message.photo[-1].file_id
            state["preview"] = {
                "photo": file_id,
                "caption": message.caption or ""
            }
            state["step"] = "confirm"
            await bot.send_photo(
                message.from_user.id,
                file_id,
                caption=f"<b>Предпросмотр рассылки:</b>\n\n{message.caption or ''}",
                parse_mode="HTML",
                reply_markup=get_broadcast_confirm_keyboard()
            )
            return
        if state["step"] == "document" and message.document:
            file_id = message.document.file_id
            caption = message.caption or ""
            state["type"] = "document"
            state["preview"] = {"document": file_id, "caption": caption}
            state["step"] = "confirm"
            await bot.send_document(
                message.from_user.id,
                file_id,
                caption=f"<b>Предпросмотр рассылки:</b>\n\n{caption}",
                parse_mode="HTML",
                reply_markup=get_broadcast_confirm_keyboard()
            )
            return
        if state["step"] == "custom_button" and message.text:
            # Обработка пользовательской кнопки
            try:
                if "|" not in message.text:
                    await message.reply(
                        "❌ Неверный формат. Используйте:\n"
                        "<code>Текст кнопки | https://example.com</code>",
                        parse_mode="HTML"
                    )
                    return
                
                text, url = message.text.split("|", 1)
                text = text.strip()
                url = url.strip()
                
                if not text or not url:
                    await message.reply(
                        "❌ Текст кнопки и URL не могут быть пустыми.",
                        parse_mode="HTML"
                    )
                    return
                
                if not url.startswith(("http://", "https://")):
                    await message.reply(
                        "❌ URL должен начинаться с http:// или https://",
                        parse_mode="HTML"
                    )
                    return
                
                # Создаем кнопку
                custom_button = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=text, url=url)]
                ])
                state["buttons"] = custom_button
                
                await message.reply(
                    f"✅ Кнопка создана: {text}\n\n"
                    "Теперь вы можете вернуться к предпросмотру.",
                    parse_mode="HTML",
                    reply_markup=get_broadcast_custom_button_keyboard()
                )
                return
                
            except Exception as e:
                await message.reply(
                    "❌ Ошибка при создании кнопки. Проверьте формат.",
                    parse_mode="HTML"
                )
                return
        if state["step"] in ("photo", "document") and not (message.photo or message.document):
            await message.reply("Пожалуйста, отправьте файл (фото или документ) с подписью.")
            return
    # --- Если это неизвестная команда, можно вернуть help или ничего не делать ---
    # Добавляем поддержку Леди Баг и Супер Кот в статистику пользователей
    user_id = message.from_user.id
    if user_id not in stats.get("lbsc_votes", {}):
        stats.setdefault("lbsc_votes", {})
        stats["lbsc_votes"][user_id] = {}


# === НОВАЯ СИСТЕМА УПРАВЛЕНИЯ ЗАКРЕПЛЕННЫМ КОНТЕНТОМ ===
# Добавим простые команды для управления закрепом
@router.message(Command("pin"))
async def pin_content_simple(message: Message):
    """Простая команда для закрепления контента"""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.reply(
            "📌 <b>Закрепление контента</b>\n\n"
            "<b>Формат:</b> <code>/pin &lt;movie|series&gt; &lt;ключ&gt; [порядок]</code>\n\n"
            "<b>Примеры:</b>\n"
            "• <code>/pin series phf 1</code> - закрепить Финес и Ферб первым\n"
            "• <code>/pin series lbsc 2</code> - закрепить Леди Баг вторым\n"
            "• <code>/pin movie avatar 3</code> - закрепить фильм Аватар третьим",
            parse_mode="HTML"
        )
        return
    
    content_type = args[1].lower()
    content_key = args[2]
    pin_order = int(args[3]) if len(args) > 3 else 0
    
    if content_type not in ['movie', 'series']:
        await message.reply("❌ Тип контента должен быть 'movie' или 'series'")
        return
    
    try:
        from db import add_pinned_content, is_content_pinned
        
        # Проверяем, не закреплен ли уже
        if is_content_pinned(content_type, content_key):
            await message.reply("⚠️ Этот контент уже закреплен")
            return
        
        # Добавляем в закреп
        success = add_pinned_content(content_type, content_key, pin_order)
        
        if success:
            await message.reply(
                f"✅ <b>Контент закреплен!</b>\n\n"
                f"🔑 Ключ: <code>{content_key}</code>\n"
                f"🗂 Тип: {content_type}\n"
                f"📊 Порядок: {pin_order}",
                parse_mode="HTML"
            )
        else:
            await message.reply("❌ Ошибка при закреплении контента")
            
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")

@router.message(Command("unpin"))
async def unpin_content_simple(message: Message):
    """Простая команда для открепления контента"""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    args = message.text.split()
    if len(args) != 3:
        await message.reply(
            "📌 <b>Открепление контента</b>\n\n"
            "<b>Формат:</b> <code>/unpin &lt;movie|series&gt; &lt;ключ&gt;</code>\n\n"
            "<b>Примеры:</b>\n"
            "• <code>/unpin series phf</code> - открепить Финес и Ферб\n"
            "• <code>/unpin movie avatar</code> - открепить фильм Аватар",
            parse_mode="HTML"
        )
        return
    
    content_type = args[1].lower()
    content_key = args[2]
    
    if content_type not in ['movie', 'series']:
        await message.reply("❌ Тип контента должен быть 'movie' или 'series'")
        return
    
    try:
        from db import remove_pinned_content, is_content_pinned
        
        # Проверяем, закреплен ли контент
        if not is_content_pinned(content_type, content_key):
            await message.reply(f"❌ Контент '{content_key}' не закреплен")
            return
        
        # Удаляем из закрепа
        success = remove_pinned_content(content_type, content_key)
        
        if success:
            await message.reply(
                f"✅ <b>Контент откреплен!</b>\n\n"
                f"🔑 Ключ: <code>{content_key}</code>\n"
                f"🗂 Тип: {content_type}",
                parse_mode="HTML"
            )
        else:
            await message.reply("❌ Ошибка при откреплении контента")
            
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")

@router.message(Command("newss"))
async def send_new_series_news(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ У вас нет доступа к этой команде.")
        return
    args = message.text.split()
    if len(args) != 3:
        await message.reply("Используйте: /newss (сезон) (серия)")
        return
    try:
        season = int(args[1])
        episode = int(args[2])
    except ValueError:
        await message.reply("Неверный формат. Пример: /newss 8 3")
        return
    text = f"🎉 Вышла новая серия!\nСезон {season}, Серия {episode}!\nСмотри прямо сейчас в боте!"
    count = 0
    # Удаляю переменные и функции, связанные с подпиской
    # for user_id in subscribers: # subscribers is removed
    #     try:
    #         await bot.send_message(user_id, text)
    #         count += 1
    #     except Exception:
    #         pass
    await message.reply(f"Уведомление отправлено {count} подписчикам.")

# --- Утилита: перезалив фильма с миниатюрой, чтобы inline-поиск показывал постер ---
@router.message(Command("setmoviepreview"))
async def set_movie_preview(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Формат: /setmoviepreview <movie_key> <video_file_id> <poster_file_id>
    # Пример: /setmoviepreview deadpool_wolverine BAACAg... AgACAg...
    args = message.text.split()
    if len(args) != 4:
        await message.reply("Формат: /setmoviepreview <movie_key> <video_file_id> <poster_file_id>")
        return
    _, movie_key, video_fid, poster_fid = args
    from storage import MOVIES
    meta = MOVIES.get(movie_key)
    if not meta:
        await message.reply("Неизвестный movie_key")
        return
    title = meta.get('title', movie_key)

    await message.reply(f"Готовлю перезалив: <b>{title}</b>\nЭто может занять до 1-2 минут...", parse_mode="HTML")
    try:
        # Получаем прямые URL для видео и постера
        vfile = await bot.get_file(video_fid)
        pfile = await bot.get_file(poster_fid)
        video_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{vfile.file_path}"
        poster_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{pfile.file_path}"

        # Скачиваем оба файла
        async with aiohttp.ClientSession() as session:
            async with session.get(video_url) as vr:
                video_bytes = await vr.read()
            async with session.get(poster_url) as pr:
                poster_bytes = await pr.read()

        video_input = BufferedInputFile(video_bytes, filename="movie.mp4")
        poster_input = BufferedInputFile(poster_bytes, filename="poster.jpg")

        # Отправляем видео с миниатюрой администратору, читаем новый file_id
        sent = await bot.send_video(
            chat_id=message.chat.id,
            video=video_input,
            thumbnail=poster_input,
            caption=f"<b>{title}</b> (перезалито с постером)",
            parse_mode="HTML"
        )
        new_file_id = sent.video.file_id if sent.video else None
        if not new_file_id:
            await message.reply("Не удалось получить новый file_id у видео")
            return

        # Обновляем запись в БД и кэше storage
        try:
            from db import bulk_upsert_movies
            from storage import MOVIES as MOVIES_CACHE
            # persist
            bulk_upsert_movies([(
                movie_key,
                title,
                new_file_id,
                meta.get('type', 'video'),
                meta.get('poster_url'),
                meta.get('thumb_url') or meta.get('poster_url'),
                meta.get('aliases'),
                meta.get('share_query')
            )])
            # update in-memory mirror
            MOVIES_CACHE.setdefault(movie_key, {
                'title': title,
                'file_id': new_file_id,
                'type': meta.get('type', 'video'),
                'poster_url': meta.get('poster_url'),
                'thumb_url': meta.get('thumb_url') or meta.get('poster_url'),
                'aliases': meta.get('aliases') or [],
                'share_query': meta.get('share_query')
            })
            MOVIES_CACHE[movie_key]['file_id'] = new_file_id
        except Exception:
            # fallback: just mutate meta so current process sees the new file_id
            meta['file_id'] = new_file_id

        await message.reply(
            f"✅ Готово! Новый file_id сохранён. Теперь inline-поиск будет показывать постер рядом с названием и отправлять фильм сразу по клику.\n<code>{new_file_id}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.reply(f"Ошибка перезалива: {e}")


# === НОВАЯ СИСТЕМА УПРАВЛЕНИЯ ЗАКРЕПЛЕННЫМ КОНТЕНТОМ ===

# Словарь для хранения состояний пользователей при работе с закрепом
pin_manager_states = {}

def get_pin_manager_keyboard():
    """Главное меню управления закрепом"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Просмотр закрепа", callback_data="pin_view")],
        [InlineKeyboardButton(text="➕ Добавить в закреп", callback_data="pin_add")],
        [InlineKeyboardButton(text="🔍 Поиск контента", callback_data="pin_search")],
        [InlineKeyboardButton(text="🔄 Обновить порядок", callback_data="pin_reorder")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="pin_close")]
    ])
    return keyboard

def get_content_type_keyboard():
    """Клавиатура выбора типа контента"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Фильмы", callback_data="pin_type_movie")],
        [InlineKeyboardButton(text="📺 Сериалы", callback_data="pin_type_series")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="pin_back_main")]
    ])
    return keyboard

def get_pinned_content_keyboard(pinned_items):
    """Клавиатура с закрепленным контентом для управления"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    buttons = []
    for item in pinned_items:
        content_type = item['content_type']
        content_key = item['content_key']
        pin_order = item['pin_order']
        
        # Получаем название
        if content_type == 'movie':
            from storage import MOVIES
            title = MOVIES.get(content_key, {}).get('title', content_key)
            icon = "🎬"
        else:
            from db import load_all_series
            db_series = load_all_series()
            series_info = next((s for s in db_series if s['key'] == content_key), None)
            title = series_info['title'] if series_info else content_key
            icon = "📺"
        
        button_text = f"{icon} {title} (#{pin_order})"
        callback_data = f"pin_manage_{content_type}_{content_key}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="pin_back_main")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_content_action_keyboard(content_type, content_key):
    """Клавиатура действий с конкретным контентом"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ Удалить из закрепа", callback_data=f"pin_remove_{content_type}_{content_key}")],
        [InlineKeyboardButton(text="📊 Изменить порядок", callback_data=f"pin_change_order_{content_type}_{content_key}")],
        [InlineKeyboardButton(text="↩️ Назад к списку", callback_data="pin_view")]
    ])
    return keyboard

@router.message(Command("help"))
async def help_command(message: Message):
    """Команда помощи"""
    from config import BOT_USERNAME
    
    text = (
        "Привет! В этом сообщении я научу тебя пользоваться ботом!\n"
        "😊 И отвечу на самые задаваемые вопросы! ❤️\n\n"
        "Для того, что бы, посмотреть фильм и/или сериал вам нужно "
        "нажать на /start→ \"Начать поиск\" после чего вы пишите, что "
        f"хотите посмотреть. Пример: @{BOT_USERNAME} tor canorax\n\n"
        "Коллекция фильмов постоянно пополняется. С каждым днем. С каждой минутой. "
        "С каждой секундой. Если вашего любимого фильма нет, не стоит унывать! "
        "Вы можете предложить его нажав на /start и \"Связаться с админом\". "
        "Не бойтесь писать! Админ вас не укусит!"
    )
    
    await message.reply(text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())

@router.message(Command("quickpin"))
async def quick_pin_command(message: Message):
    """Команда быстрого добавления популярного контента в закреп"""
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔️ Команда только для админа")
        return
    
    # Популярный контент для быстрого добавления
    popular_content = [
        {'type': 'series', 'key': 'phf', 'name': 'Финес и Ферб'},
        {'type': 'series', 'key': 'lbsc', 'name': 'Леди Баг и Супер-Кот'},
        {'type': 'series', 'key': 'rm', 'name': 'Рик и Морти'},
        {'type': 'series', 'key': 'wnd', 'name': 'Уэнсдей'},
        {'type': 'series', 'key': 'loki', 'name': 'Локи'},
    ]
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    buttons = []
    for content in popular_content:
        icon = "🎬" if content['type'] == 'movie' else "📺"
        button_text = f"{icon} {content['name']}"
        callback_data = f"quickpin_{content['type']}_{content['key']}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    buttons.append([InlineKeyboardButton(text="📌 Открыть менеджер", callback_data="open_pin_manager")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="pin_close")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    text = (
        "⚡ <b>Быстрое добавление в закреп</b>\n\n"
        "Выберите популярный контент для быстрого добавления в закреп:"
    )
    
    await message.reply(text, parse_mode="HTML", reply_markup=keyboard)

async def search_content_by_key(content_type: str, search_query: str, limit: int = 10):
    """Поиск контента по ключу или названию"""
    results = []
    try:
        from vibix_api import vibix_api
        page = await vibix_api.list_links(limit=100)
        if page and page.get('data'):
            q = (search_query or '').lower()
            for item in page['data']:
                title = (item.get('name_rus') or item.get('name') or '')
                if q and q not in title.lower():
                    continue
                if content_type == 'movie' and item.get('type') != 'movie':
                    continue
                if content_type != 'movie' and item.get('type') != 'serial':
                    continue
                key = str(item.get('kp_id') or item.get('imdb_id') or item.get('id'))
                results.append({'key': key, 'title': title, 'type': item.get('type')})
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results

def get_search_results_keyboard(results, content_type):
    """Клавиатура с результатами поиска"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    buttons = []
    for result in results:
        title = result['title']
        key = result['key']
        icon = "🎬" if content_type == 'movie' else "📺"
        
        button_text = f"{icon} {title}"
        callback_data = f"pin_add_confirm_{content_type}_{key}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="pin_add")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Обработчики callback-запросов для системы закрепа
@router.callback_query(lambda c: c.data.startswith("pin_"))
async def handle_pin_callbacks(callback: CallbackQuery):
    """Обработчик всех callback-запросов системы закрепа"""
    data = callback.data
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer("⛔️ Доступ запрещен", show_alert=True)
        return
    
    # Главное меню
    if data == "pin_back_main":
        text = (
            "📌 <b>Менеджер закрепленного контента</b>\n\n"
            "Здесь вы можете управлять контентом, который отображается "
            "в начале инлайн поиска.\n\n"
            "Выберите действие:"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_pin_manager_keyboard())
        await callback.answer()
    
    # Просмотр закрепленного контента
    elif data == "pin_view":
        try:
            from db import get_pinned_content
            pinned = get_pinned_content()
            
            if not pinned:
                text = "📌 <b>Закрепленный контент</b>\n\n❌ Закрепленного контента нет"
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="↩️ Назад", callback_data="pin_back_main")]
                ])
            else:
                text = "📌 <b>Закрепленный контент</b>\n\nВыберите элемент для управления:"
                keyboard = get_pinned_content_keyboard(pinned)
            
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer()
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    
    # Добавление в закреп - выбор типа
    elif data == "pin_add":
        text = "➕ <b>Добавить в закреп</b>\n\nВыберите тип контента:"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_content_type_keyboard())
        await callback.answer()
    
    # Выбор типа контента для добавления
    elif data.startswith("pin_type_"):
        content_type = data.split("_")[2]  # movie или series
        pin_manager_states[user_id] = {
            'action': 'add',
            'content_type': content_type,
            'step': 'waiting_search'
        }
        
        type_name = "фильмов" if content_type == "movie" else "сериалов"
        text = (
            f"🔍 <b>Поиск {type_name}</b>\n\n"
            f"Введите ключ или название для поиска {type_name}.\n"
            f"Например: <code>avatar</code> или <code>Аватар</code>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Назад", callback_data="pin_add")]
        ])
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    # Подтверждение добавления контента
    elif data.startswith("pin_add_confirm_"):
        parts = data.split("_", 3)
        content_type = parts[2]
        content_key = parts[3]
        
        try:
            from db import add_pinned_content, get_pinned_content, is_content_pinned
            
            # Проверяем, не закреплен ли уже
            if is_content_pinned(content_type, content_key):
                await callback.answer("⚠️ Этот контент уже закреплен", show_alert=True)
                return
            
            # Определяем следующий порядок
            pinned = get_pinned_content()
            next_order = max([item['pin_order'] for item in pinned], default=0) + 1
            
            # Добавляем в закреп
            success = add_pinned_content(content_type, content_key, next_order)
            
            if success:
                # Получаем название для отображения
                if content_type == 'movie':
                    from storage import MOVIES
                    title = MOVIES.get(content_key, {}).get('title', content_key)
                else:
                    from db import load_all_series
                    db_series = load_all_series()
                    series_info = next((s for s in db_series if s['key'] == content_key), None)
                    title = series_info['title'] if series_info else content_key
                
                type_name = "Фильм" if content_type == "movie" else "Сериал"
                text = (
                    f"✅ <b>Контент добавлен в закреп!</b>\n\n"
                    f"📌 {type_name}: <b>{title}</b>\n"
                    f"🔑 Ключ: <code>{content_key}</code>\n"
                    f"📊 Порядок: {next_order}"
                )
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📌 Просмотр закрепа", callback_data="pin_view")],
                    [InlineKeyboardButton(text="↩️ Главное меню", callback_data="pin_back_main")]
                ])
                
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
                await callback.answer("✅ Добавлено!")
            else:
                await callback.answer("❌ Ошибка при добавлении", show_alert=True)
                
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    
    # Управление конкретным контентом
    elif data.startswith("pin_manage_"):
        parts = data.split("_", 2)
        content_info = parts[2]  # "movie_key" или "series_key"
        content_type, content_key = content_info.split("_", 1)
        
        # Получаем информацию о контенте
        if content_type == 'movie':
            from storage import MOVIES
            title = MOVIES.get(content_key, {}).get('title', content_key)
            icon = "🎬"
        else:
            from db import load_all_series
            db_series = load_all_series()
            series_info = next((s for s in db_series if s['key'] == content_key), None)
            title = series_info['title'] if series_info else content_key
            icon = "📺"
        
        text = (
            f"{icon} <b>{title}</b>\n\n"
            f"🔑 Ключ: <code>{content_key}</code>\n"
            f"🗂 Тип: {content_type}\n\n"
            f"Выберите действие:"
        )
        
        await callback.message.edit_text(text, parse_mode="HTML", 
                                       reply_markup=get_content_action_keyboard(content_type, content_key))
        await callback.answer()
    
    # Удаление из закрепа
    elif data.startswith("pin_remove_"):
        parts = data.split("_", 2)
        content_info = parts[2]
        content_type, content_key = content_info.split("_", 1)
        
        try:
            from db import remove_pinned_content
            success = remove_pinned_content(content_type, content_key)
            
            if success:
                text = "✅ <b>Контент удален из закрепа!</b>"
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📌 Просмотр закрепа", callback_data="pin_view")],
                    [InlineKeyboardButton(text="↩️ Главное меню", callback_data="pin_back_main")]
                ])
                
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
                await callback.answer("✅ Удалено!")
            else:
                await callback.answer("❌ Ошибка при удалении", show_alert=True)
                
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    
    # Быстрое добавление популярного контента
    elif data.startswith("quickpin_"):
        parts = data.split("_", 2)
        content_type = parts[1]
        content_key = parts[2]
        
        try:
            from db import add_pinned_content, get_pinned_content, is_content_pinned
            
            # Проверяем, не закреплен ли уже
            if is_content_pinned(content_type, content_key):
                await callback.answer("⚠️ Этот контент уже закреплен", show_alert=True)
                return
            
            # Определяем следующий порядок
            pinned = get_pinned_content()
            next_order = max([item['pin_order'] for item in pinned], default=0) + 1
            
            # Добавляем в закреп
            success = add_pinned_content(content_type, content_key, next_order)
            
            if success:
                # Получаем название для отображения
                if content_type == 'movie':
                    from storage import MOVIES
                    title = MOVIES.get(content_key, {}).get('title', content_key)
                else:
                    from db import load_all_series
                    db_series = load_all_series()
                    series_info = next((s for s in db_series if s['key'] == content_key), None)
                    title = series_info['title'] if series_info else content_key
                
                await callback.answer(f"✅ {title} добавлен в закреп!")
                
                # Обновляем сообщение
                text = (
                    f"✅ <b>Контент добавлен в закреп!</b>\n\n"
                    f"📌 {title}\n"
                    f"🔑 Ключ: <code>{content_key}</code>\n"
                    f"📊 Порядок: {next_order}"
                )
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📌 Просмотр закрепа", callback_data="pin_view")],
                    [InlineKeyboardButton(text="⚡ Быстрое добавление", callback_data="quickpin_menu")],
                    [InlineKeyboardButton(text="↩️ Главное меню", callback_data="pin_back_main")]
                ])
                
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await callback.answer("❌ Ошибка при добавлении", show_alert=True)
                
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)
    
    # Открытие менеджера из быстрого меню
    elif data == "open_pin_manager":
        text = (
            "📌 <b>Менеджер закрепленного контента</b>\n\n"
            "Здесь вы можете управлять контентом, который отображается "
            "в начале инлайн поиска.\n\n"
            "Выберите действие:"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_pin_manager_keyboard())
        await callback.answer()
    
    # Возврат к быстрому меню
    elif data == "quickpin_menu":
        # Популярный контент для быстрого добавления
        popular_content = [
            {'type': 'series', 'key': 'phf', 'name': 'Финес и Ферб'},
            {'type': 'series', 'key': 'lbsc', 'name': 'Леди Баг и Супер-Кот'},
            {'type': 'series', 'key': 'rm', 'name': 'Рик и Морти'},
            {'type': 'series', 'key': 'wnd', 'name': 'Уэнсдей'},
            {'type': 'series', 'key': 'loki', 'name': 'Локи'},
        ]
        
        buttons = []
        for content in popular_content:
            icon = "🎬" if content['type'] == 'movie' else "📺"
            button_text = f"{icon} {content['name']}"
            callback_data = f"quickpin_{content['type']}_{content['key']}"
            buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
        
        buttons.append([InlineKeyboardButton(text="📌 Открыть менеджер", callback_data="open_pin_manager")])
        buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="pin_close")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        text = (
            "⚡ <b>Быстрое добавление в закреп</b>\n\n"
            "Выберите популярный контент для быстрого добавления в закреп:"
        )
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    # Поиск контента
    elif data == "pin_search":
        text = (
            "🔍 <b>Поиск контента</b>\n\n"
            "Эта функция в разработке.\n\n"
            "Используйте команды:\n"
            "• <code>/pin series ключ порядок</code>\n"
            "• <code>/pin movie ключ порядок</code>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Назад", callback_data="pin_back_main")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    # Обновить порядок
    elif data == "pin_reorder":
        text = (
            "🔄 <b>Обновить порядок</b>\n\n"
            "Эта функция в разработке.\n\n"
            "Используйте команды:\n"
            "• <code>/pin series ключ новый_порядок</code>\n"
            "• <code>/unpin series ключ</code>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Назад", callback_data="pin_back_main")]
        ])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    # Закрытие меню
    elif data == "pin_close":
        await callback.message.delete()
        await callback.answer()



# Helper functions for inline query processing
def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace('ё', 'е')
    for ch in [',', ';', '|', ':', '\\', '/', '\n', '\t', '(', ')', '[', ']', '"', "'", '—', '–', '-']:
        s = s.replace(ch, ' ')
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _tokens(s: str) -> list:
    return [t for t in _norm(s).split(' ') if t]

def _lev(a: str, b: str, max_d: int = 2) -> int:
    # Лёгкая оценка дистанции Левенштейна с ранним выходом
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_d:
        return max_d + 1
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        min_row = cur[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + cost)
            cur.append(v)
            if v < min_row:
                min_row = v
        if min_row > max_d:
            return max_d + 1
        prev = cur
    return prev[-1]

# Обработчик inline запросов для функции "Поделиться"
@dp.inline_query()
async def handle_inline_query(query: InlineQuery):
    
    # Сохраняем информацию о пользователе
    user = query.from_user
    if user:
        save_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
            is_bot=user.is_bot
        )
    
    # Проверка подписки (кроме админов и премиум пользователей)
    if user and user.id not in ADMIN_IDS and not is_premium_user(user.id):
        if not await check_subscription(user.id):
            # Показываем сообщение о необходимости подписки
            text, _ = get_subscription_message(user.id)
            
            results = [
                InlineQueryResultArticle(
                    id="subscription_required",
                    title="⚠️ Требуется подписка на канал",
                    description="Подпишитесь на наш канал, чтобы пользоваться ботом",
                    input_message_content=InputTextMessageContent(
                        message_text=text,
                        parse_mode="HTML"
                    ),
                    thumb_url="https://i.imgur.com/subscription.png"
                )
            ]
            
            await query.answer(results, cache_time=10, is_personal=True)
            return
    
    q = (query.query or '').strip()
    
    # Логируем поиск
    if q:
        username = f"@{user.username}" if user and user.username else f"ID:{user.id if user else 'Unknown'}"
        logging.info(f"🔍 Поиск: '{q}' | Пользователь: {username}")
    # logging.info(f"[INLINE_QUERY] ========== НАЧАЛО ОБРАБОТКИ ==========")
    # logging.info(f"[INLINE_QUERY] Запрос: '{q}' от пользователя {user.id if user else 'Unknown'}")
    # logging.info(f"[INLINE_QUERY] Пустой запрос: {not q}")
    
    # Пустой запрос: список из Vibix с пагинацией по 50
    if not q:
        results: list = []
        # В Telegram offset — строка. Будем использовать номер страницы.
        try:
            page = int(query.offset or "1")
            if page < 1:
                page = 1
        except Exception:
            page = 1

        from vibix_api import vibix_api
        vibix_page = await vibix_api.list_links(page=page, limit=50)
        data = (vibix_page or {}).get('data') or []
        
        # Разделяем результаты на группы для лучшей сортировки
        items_with_posters = []
        items_without_posters = []
        
        for i, item in enumerate(data):
            title = item.get('name_rus') or item.get('name') or 'Без названия'
            thumb_url = item.get('poster_url') or None
            key = str(item.get('kp_id') or item.get('imdb_id') or item.get('id'))
            is_serial = item.get('type') == 'serial'
            message_code = f"/vibix_series_{key}" if is_serial else f"/vibix_movie_{key}"
            
            # Формируем описание с рейтингами и жанрами
            description_parts = ['📺 сериал' if is_serial else '🎬 фильм']
            
            # Добавляем рейтинги и вычисляем максимальный рейтинг для сортировки
            kp_rating = item.get('kp_rating')
            imdb_rating = item.get('imdb_rating')
            max_rating = 0.0
            
            if kp_rating:
                try:
                    kp_float = float(kp_rating)
                    if kp_float > 0:
                        description_parts.append(f"КП: {kp_rating}")
                        max_rating = max(max_rating, kp_float)
                except (ValueError, TypeError):
                    pass
            
            if imdb_rating:
                try:
                    imdb_float = float(imdb_rating)
                    if imdb_float > 0:
                        description_parts.append(f"IMDb: {imdb_rating}")
                        max_rating = max(max_rating, imdb_float)
                except (ValueError, TypeError):
                    pass
            
            # Добавляем жанры
            genres = item.get('genre', [])
            if genres and isinstance(genres, list):
                genres_text = ', '.join(genres[:2])  # Первые 2 жанра
                description_parts.append(genres_text)
            
            # Добавляем год
            year = item.get('year')
            if year:
                description_parts.append(str(year))
            
            description = ' | '.join(description_parts)
            
            result_item = InlineQueryResultArticle(
                id=f"vibix_{item.get('type')}_{item.get('id')}",
                title=title,
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=message_code,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                ),
                thumb_url=thumb_url
            )
            
            # Сортируем по наличию постера
            if thumb_url:
                items_with_posters.append((result_item, is_serial, title, max_rating))
            else:
                items_without_posters.append((result_item, is_serial, title, max_rating))
        
        # Сортируем: сначала по рейтингу (убывание), потом фильмы перед сериалами, потом по алфавиту
        items_with_posters.sort(key=lambda x: (-x[3], x[1], x[2].lower()))  # -rating, is_serial, title
        items_without_posters.sort(key=lambda x: (-x[3], x[1], x[2].lower()))
        
        # Добавляем сначала элементы с постерами, потом без постеров
        for result_item, _, _, _ in items_with_posters:
            results.append(result_item)
        
        for result_item, _, _, _ in items_without_posters:
            results.append(result_item)
                
        # Пагинация: если есть ещё страницы — увеличиваем page
        next_offset = ""
        meta = (vibix_page or {}).get('meta') or {}
        current = meta.get('current_page')
        last = meta.get('last_page')
        if isinstance(current, int) and isinstance(last, int) and current < last:
            next_offset = str(current + 1)
        elif len(data) == 50:
            # запасной вариант, если мета не пришла
            next_offset = str(page + 1)

        try:
            await query.answer(results, cache_time=1, is_personal=True, next_offset=next_offset)
        except Exception:
            await query.answer([], cache_time=1, is_personal=True, next_offset=next_offset)
        return
    # --- Поиск по сериалам и фильмам в inline через Vibix ---
    text = q.lower()
    
    # logging.info(f"[INLINE_QUERY] ========== НАЧАЛО ПОИСКА ==========")
    # logging.info(f"[INLINE_QUERY] Нормализованный текст: '{text}'")
    # Валидация file_id до ответа Telegram (чтобы не падать на Bad Request)
    import re as _re_validate
    def _is_valid_file_id(fid: str) -> bool:
        if not isinstance(fid, str) or len(fid) < 20:
            return False
        if not _re_validate.match(r'^[A-Za-z0-9_-]+$', fid):
            return False
        return fid.startswith(('BAACAg', 'AgAD', 'CgAD', 'BQAD'))
    # Нормализация-разделителей
    for ch in [',', ';', '|', '-', ':']:
        text = text.replace(ch, ' ')
    text = text.replace('x', 'x')  # сохраняем x для формата 2x3
    parts = text.split()

    def detect_show(token: str) -> str:
        aliases = {
            'rm': 'rm', 'rick': 'rm', 'rickandmorty': 'rm', 'rick_and_morty': 'rm', 'рик': 'rm', 'рикморти': 'rm',
            'phf': 'phf', 'phineas': 'phf', 'phineasandferb': 'phf', 'phineas_and_ferb': 'phf', 'финес': 'phf', 'ферб': 'phf',
            'lb': 'lbsc', 'lbsc': 'lbsc', 'ladybug': 'lbsc', 'miraculous': 'lbsc', 'леди': 'lbsc', 'ледибаг': 'lbsc', 'кот': 'lbsc',
            'irh': 'irh', 'ironheart': 'irh', 'железное': 'irh', 'сердце': 'irh',
            'wnd': 'wnd', 'wednesday': 'wnd', 'уэнсдэй': 'wnd', 'уэнсдей': 'wnd',
            'loki': 'loki', 'локи': 'loki'
        }
        return aliases.get(token, '')

    show = ''
    season = None
    episode = None

    # Поиск сначала через локальный индекс, затем через Vibix API
    try:
        from vibix_api import ensure_index_loaded, search_index, build_full_index, _vibix_index, vibix_api
        
        # Сначала пытаемся найти в локальном индексе
        await ensure_index_loaded()
        vibix_items = search_index(q, limit=50)
        
        # Проверяем, есть ли рейтинги в результатах локального индекса
        has_ratings = vibix_items and any(item.get('kp_rating') or item.get('imdb_rating') for item in vibix_items[:5])
        
        # Если в индексе ничего не нашли ИЛИ нет рейтингов, делаем прямой поиск через API
        if not vibix_items or not has_ratings:
            if not vibix_items:
                logging.info(f"[INLINE_QUERY] Поиск через Vibix API: {q} (ничего не найдено в индексе)")
            else:
                logging.info(f"[INLINE_QUERY] Поиск через Vibix API: {q} (нет рейтингов в индексе)")
            # Прямой поиск через API по названию
            from vibix_api import search_by_title
            vibix_items = await search_by_title(q, max_results=50, max_pages=10, time_limit_sec=15.0)
        
        # Логируем результаты поиска
        logging.info(f"[INLINE_QUERY] Найдено через Vibix: {len(vibix_items)} элементов")
        if vibix_items:
            # Логируем первые несколько элементов для отладки
            for i, item in enumerate(vibix_items[:3]):
                logging.info(f"[INLINE_QUERY] Элемент {i+1}: {item.get('name_rus')} | КП: {item.get('kp_rating')} | IMDb: {item.get('imdb_rating')} | Жанры: {item.get('genre')}")
        else:
            logging.warning(f"[INLINE_QUERY] Поиск не дал результатов для запроса: '{q}'")
        series_results = []
        movie_results = []
        if vibix_items:
            for item in vibix_items:
                title = (item.get('name_rus') or item.get('name') or '').lower()
                entry = {
                    'key': str(item.get('kp_id') or item.get('imdb_id') or item.get('id')),
                    'title': item.get('name_rus') or item.get('name') or 'Без названия',
                    'poster_url': item.get('poster_url') or '',
                    'thumb_url': item.get('poster_url') or '',
                    'type': item.get('type'),
                    # Добавляем данные для рейтингов и жанров
                    'kp_rating': item.get('kp_rating'),
                    'imdb_rating': item.get('imdb_rating'),
                    'genre': item.get('genre'),
                    'year': item.get('year')
                }
                if item.get('type') == 'serial':
                    series_results.append(entry)
                else:
                    movie_results.append(entry)
        
        # Показываем результаты поиска с улучшенной сортировкой
        search_results = []
        results_with_posters = []
        results_without_posters = []
        
        # Обрабатываем сериалы
        if series_results:
            for series in series_results:
                series_key = series.get('key', '')
                title = series.get('title', 'Без названия')
                poster_url = series.get('poster_url', '')
                thumb_url = series.get('thumb_url', '') or poster_url
                
                # Fallback на SERIES_POSTERS если нет постера в БД
                if not thumb_url and series_key in SERIES_POSTERS:
                    poster_data = SERIES_POSTERS[series_key]
                    if isinstance(poster_data, dict):
                        thumb_url = poster_data.get('show') or poster_data.get(max(poster_data.keys()) if poster_data else None)
                    else:
                        thumb_url = poster_data
                
                # Формируем описание с рейтингами и жанрами
                description_parts = ['📺 сериал']
                
                # Используем данные прямо из entry
                kp_rating = series.get('kp_rating')
                imdb_rating = series.get('imdb_rating')
                genres = series.get('genre', [])
                year = series.get('year')
                
                # logging.info(f"[INLINE_SEARCH] Данные сериала {title}: КП={kp_rating}, IMDb={imdb_rating}, жанры={genres}, год={year}")
                
                # Добавляем рейтинги
                if kp_rating:
                    try:
                        if float(kp_rating) > 0:
                            description_parts.append(f"КП: {kp_rating}")
                    except (ValueError, TypeError):
                        pass
                
                if imdb_rating:
                    try:
                        if float(imdb_rating) > 0:
                            description_parts.append(f"IMDb: {imdb_rating}")
                    except (ValueError, TypeError):
                        pass
                
                # Добавляем жанры
                if genres and isinstance(genres, list):
                    genres_text = ', '.join(genres[:2])  # Первые 2 жанра
                    description_parts.append(genres_text)
                
                # Добавляем год
                if year:
                    description_parts.append(str(year))
                
                description = ' | '.join(description_parts)
                
                result_item = InlineQueryResultArticle(
                    id=f"series_search_{series_key}",
                    title=title,
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=f"/vibix_series_{series_key}",
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    ),
                    thumb_url=thumb_url if thumb_url else None
                )
                
                # Сортируем по наличию постера
                if thumb_url:
                    results_with_posters.append((result_item, title, 'series'))
                else:
                    results_without_posters.append((result_item, title, 'series'))
        
        # Обрабатываем фильмы
        if movie_results:
            for movie in movie_results:
                title = movie.get('title', 'Без названия')
                movie_key = movie.get('key', '')
                poster_url = movie.get('poster_url', '')
                thumb_url = movie.get('thumb_url', '') or poster_url
                
                # Fallback на MOVIES если нет постера в БД
                if not thumb_url and movie_key in MOVIES:
                    movie_data = MOVIES[movie_key]
                    thumb_url = movie_data.get('thumb_url') or movie_data.get('poster_url')
                
                # Формируем описание с рейтингами и жанрами
                description_parts = ['🎬 фильм']
                
                # Используем данные прямо из entry
                kp_rating = movie.get('kp_rating')
                imdb_rating = movie.get('imdb_rating')
                genres = movie.get('genre', [])
                year = movie.get('year')
                
                # logging.info(f"[INLINE_SEARCH] Данные фильма {title}: КП={kp_rating}, IMDb={imdb_rating}, жанры={genres}, год={year}")
                
                # Добавляем рейтинги
                if kp_rating:
                    try:
                        if float(kp_rating) > 0:
                            description_parts.append(f"КП: {kp_rating}")
                    except (ValueError, TypeError):
                        pass
                
                if imdb_rating:
                    try:
                        if float(imdb_rating) > 0:
                            description_parts.append(f"IMDb: {imdb_rating}")
                    except (ValueError, TypeError):
                        pass
                
                # Добавляем жанры
                if genres and isinstance(genres, list):
                    genres_text = ', '.join(genres[:2])  # Первые 2 жанра
                    description_parts.append(genres_text)
                
                # Добавляем год
                if year:
                    description_parts.append(str(year))
                
                description = ' | '.join(description_parts)
                
                result_item = InlineQueryResultArticle(
                    id=f"movie_search_{movie_key}",
                    title=title,
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=f"/vibix_movie_{movie_key}",
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    ),
                    thumb_url=thumb_url if thumb_url else None
                )
                
                # Сортируем по наличию постера
                if thumb_url:
                    results_with_posters.append((result_item, title, 'movie'))
                else:
                    results_without_posters.append((result_item, title, 'movie'))
        
        # Улучшенная функция для вычисления релевантности
        def calculate_relevance(title, query):
            title_lower = title.lower()
            query_lower = query.lower()
            
            # Точное совпадение - максимальный приоритет
            if query_lower == title_lower:
                return 1000
            
            # Точное совпадение в начале названия
            if title_lower.startswith(query_lower):
                return 900
            
            # Запрос содержится в названии как подстрока (раньше проверяем)
            if query_lower in title_lower:
                return 850
            
            # Все слова запроса есть в названии
            query_words = query_lower.split()
            title_words = title_lower.split()
            
            # Проверяем точное совпадение слов
            exact_word_matches = sum(1 for qw in query_words if qw in title_words)
            if exact_word_matches == len(query_words):
                return 800
            
            # Проверяем частичное совпадение слов (слово запроса содержится в слове названия)
            partial_matches = sum(1 for qw in query_words if any(qw in tw for tw in title_words))
            if partial_matches == len(query_words):
                return 750
            
            # Подсчитываем общий скор на основе совпадений
            score = exact_word_matches * 200 + (partial_matches - exact_word_matches) * 100
            
            # Бонус за совпадение в начале слов
            start_bonus = sum(50 for qw in query_words if any(tw.startswith(qw) for tw in title_words))
            
            return score + start_bonus
        
        # Функция для получения рейтинга для сортировки
        def get_rating_score(item_data):
            try:
                # Ищем данные элемента в исходных результатах
                title = item_data[1]
                item_type = item_data[2]
                
                # Ищем соответствующий элемент в результатах поиска
                source_list = series_results if item_type == 'series' else movie_results
                for source_item in source_list:
                    if source_item.get('title') == title:
                        kp_rating = source_item.get('kp_rating', 0)
                        imdb_rating = source_item.get('imdb_rating', 0)
                        
                        # Приоритет КиноПоиск рейтингу, затем IMDb
                        if kp_rating:
                            try:
                                return float(kp_rating)
                            except (ValueError, TypeError):
                                pass
                        if imdb_rating:
                            try:
                                return float(imdb_rating)
                            except (ValueError, TypeError):
                                pass
                        break
                return 0
            except:
                return 0
        
        # Улучшенная сортировка: релевантность → рейтинг → тип → название
        results_with_posters.sort(key=lambda x: (
            -calculate_relevance(x[1], q),  # Релевантность (убывание)
            -get_rating_score(x),           # Рейтинг (убывание)
            x[2] == 'series',               # Сначала фильмы, потом сериалы
            x[1].lower()                    # Алфавитный порядок
        ))
        
        results_without_posters.sort(key=lambda x: (
            -calculate_relevance(x[1], q),  # Релевантность (убывание)
            -get_rating_score(x),           # Рейтинг (убывание)
            x[2] == 'series',               # Сначала фильмы, потом сериалы
            x[1].lower()                    # Алфавитный порядок
        ))
        
        # Собираем финальный список: сначала с постерами, потом без постеров
        for result_item, _, _ in results_with_posters:
            search_results.append(result_item)
        
        for result_item, _, _ in results_without_posters:
            search_results.append(result_item)
        
        # Логируем финальные результаты
        # logging.info(f"[INLINE_QUERY] Финальных результатов для отправки: {len(search_results)}")
        # logging.info(f"[INLINE_QUERY] С постерами: {len(results_with_posters)}, без постеров: {len(results_without_posters)}")
        
        # Если есть результаты поиска, отправляем их
        if search_results:
            try:
                await query.answer(search_results, cache_time=1, is_personal=True)
            except Exception as e:
                logging.error(f"[INLINE_QUERY] Ошибка отправки результатов: {e}")
            return
        else:
            # Быстрый единичный ответ "ничего не найдено" и выходим, чтобы не уходить в старые ветки
            not_found = InlineQueryResultArticle(
                id="not_found",
                title="Ничего не найдено",
                description="Попробуйте другое название или уточните запрос",
                input_message_content=InputTextMessageContent(
                    message_text="Ничего не найдено",
                    parse_mode="HTML",
                )
            )
            try:
                await query.answer([not_found], cache_time=1, is_personal=True)
            except Exception as e:
                logging.error(f"[INLINE_QUERY] Ошибка отправки not_found: {e}")
                return
        
        # Если найден только один сериал, устанавливаем его для дальнейшей обработки
        if series_results and len(series_results) == 1:
            first_series = series_results[0]
            series_key = first_series.get('key', '')
            show = series_key
    except Exception as e:
        logging.error(f"[INLINE_QUERY] Ошибка поиска через Vibix: {e}")
        import traceback
        logging.error(f"[INLINE_QUERY] Трейсбек: {traceback.format_exc()}")
        
        # Если произошла ошибка, показываем сообщение об ошибке
        error_result = InlineQueryResultArticle(
            id="search_error",
            title="Ошибка поиска",
            description="Произошла ошибка при поиске. Попробуйте позже.",
            input_message_content=InputTextMessageContent(
                message_text="❌ Произошла ошибка при поиске. Попробуйте позже.",
                parse_mode="HTML"
            )
        )
        await query.answer([error_result], cache_time=1, is_personal=True)
        return

    # Парсим текст запроса для извлечения параметров
    text = q
    parts = text.split() if text else []

    # Если ничего не найдено, показываем сообщение
    if not search_results:
        if q:  # Если был введен поисковый запрос, но ничего не найдено
            not_found = InlineQueryResultArticle(
                id="not_found",
                title="Контент не найден",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"❌ <b>Контент не найден</b>\n\n"
                        f"К сожалению, фильм или сериал <b>\"{q}\"</b> не найден.\n\n"
                        f"Попробуйте изменить запрос или свяжитесь с администратором:\n"
                        f"👉 /start → 💬 Связаться с админом"
                    ),
                    parse_mode="HTML"
                ),
                description=f"Фильм/сериал \"{q}\" не найден",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Связаться с админом", callback_data="contact_admin_start")]
                ])
            )
            await query.answer([not_found], cache_time=1, is_personal=True)
        else:
            # Пустой запрос — показываем пустой результат
            await query.answer([], cache_time=1, is_personal=True)

    q_norm = _norm(text)
    q_tokens = _tokens(text)
    years_in_q = re.findall(r"\b(19|20)\d{2}\b", q_norm)

    # ОТКЛЮЧЕНО: поиск по локальной базе данных MOVIES
    # insertion_order = list(MOVIES.keys())
    # order_map = {k: i for i, k in enumerate(insertion_order)}

    # scored = []
    # for key, meta in MOVIES.items():
    
    # ОТКЛЮЧЕНО: весь поиск по локальной базе данных
    scored = []
    # Старый код поиска по MOVIES закомментирован
    #     title = str(meta.get('title', key))
    #     title_n = _norm(title)
    #     aliases_n = [_norm(a) for a in meta.get('aliases', [])]
    #     score = 0
    #     # ... весь код обработки локальной базы данных отключен

    # ОТКЛЮЧЕНО: обработка результатов поиска по локальной базе данных
    # if scored:
    #     scored.sort(reverse=True)
        #     # Если единственный сильный матч — открываем карточку фильма напрямую
        #     top_score, top_key = scored[0]
        #     if top_score >= 90 and (len(scored) == 1 or (len(scored) > 1 and top_score - scored[1][0] >= 20)):
        #         show = f"movie:{top_key}"
        #     else:
        #         # Показываем результаты поиска фильмов
        #         movie_cards = []
        #         for score, key in scored[:10]:  # Топ 10 результатов
        #             meta = MOVIES.get(key, {})
        #             title = meta.get('title', key)
        #             movie_code = f"/movie_{key}"
        #             movie_cards.append(InlineQueryResultArticle(
        #                 id=f"movie_search_{key}",
        #                 title=title,
        #                 description='фильм',
        #                 input_message_content=InputTextMessageContent(
        #                     message_text=movie_code,
        #                     parse_mode="HTML",
        #                     disable_web_page_preview=True
        #                 ),
        #                 thumb_url=meta.get('thumb_url') or meta.get('poster_url')
        #             ))
        #         try:
        #             await query.answer(movie_cards, cache_time=1, is_personal=True)
        #         except Exception:
        #             await query.answer([], cache_time=1, is_personal=True)
        #         return
    # Фолбэк по фильмам больше не нужен — используется скоринг выше

    # Извлечение season/episode (для сериалов)
    rest = parts[1:] if show else parts
    joined = ' '.join(rest)
    # Форматы: "2x3", "s2 e3", "2 3", "s2"
    import re as _re
    m = _re.search(r"(s|с)?\s*(\d+)\s*(e|с|x)?\s*(\d+)?", joined)
    if m:
        s_num = m.group(2)
        e_num = m.group(4)
        if s_num:
            season = int(s_num)
        if e_num:
            episode = int(e_num)
    # Фолбэк: если сезон не распознан, возьмём первые числа из всего запроса
    if season is None:
        nums = _re.findall(r"\d+", text)
        if nums:
            season = int(nums[0])
            if episode is None and len(nums) > 1:
                episode = int(nums[1])

    # Старые словари и загрузка из локальной БД отключены — используется Vibix
    # ОТКЛЮЧЕНО: Обработка фильмов из локальной базы данных
    if show and ':' in show and show.startswith('movie:'):
        movie_key = show.split(':', 1)[1]
        meta = MOVIES.get(movie_key)
        if meta and _is_valid_file_id(meta['file_id']):
            title = meta['title']
            caption = f"<b>{title}</b>"
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
            ])
            # Пытаемся сформировать прямые URL для видео и постера, чтобы показать превью
            video_url = None
            thumb_url = None
            try:
                vfile = await bot.get_file(meta['file_id'])
                video_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{vfile.file_path}"
                poster_id = meta.get('poster_id')
                if poster_id:
                    pfile = await bot.get_file(poster_id)
                    thumb_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{pfile.file_path}"
            except Exception:
                video_url = None
                thumb_url = None
            results_list = []
            # Единый пункт списка — кэшированное видео с подробным описанием; по клику медиа отправляется сразу
            # Составим description из мета, если есть
            year = str(meta.get('year', '')).strip()
            country = meta.get('country') or meta.get('countries') or ''
            if isinstance(country, list):
                country = ', '.join(country)
            genres = meta.get('genres', '')
            if isinstance(genres, list):
                genres = ', '.join(genres)
            kp = meta.get('kp') or meta.get('kinopoisk')
        imdb = meta.get('imdb')
        rating_parts = []
        if kp:
            rating_parts.append(f"kp:{kp}")
        if imdb:
            rating_parts.append(f"imdb:{imdb}")
        rating_line = ' | '.join(rating_parts)
        desc_parts = []
        if country:
            desc_parts.append(country)
            if year:
                desc_parts.append(year)
            if genres:
                desc_parts.append(genres)
            if rating_line:
                desc_parts.append(rating_line)
            description = ' | '.join([p for p in desc_parts if p])

            # Карточка Article с заголовком (виден в списке) и кнопкой Смотреть
            poster_url = meta.get('poster_url') or meta.get('thumb_url')
            thumb = meta.get('thumb_url') or meta.get('poster_url') or thumb_url or None
            # Текст для Article БЕЗ сырой ссылки
            article_lines = [f"<b>{title}</b>"]
            if description:
                article_lines.append(description)
            article_lines.append("\n" + get_watch_hint())
            article_text = "\n".join(article_lines)
            # Подпись под названием: фильм | остальная мета
            desc_under_title = "фильм" + (f" | {description}" if description else "")
            try:
                results_list.append(InlineQueryResultArticle(
                    id=f"movie_article_{movie_key}",
                    title=title,
                    description=desc_under_title,
                    input_message_content=InputTextMessageContent(message_text=f"/movie_{movie_key}", parse_mode="HTML", disable_web_page_preview=True),
                    thumb_url=thumb,
                ))
            except Exception:
                pass
            try:
                await query.answer(results_list, cache_time=1, is_personal=True)
            except Exception:
                await query.answer([], cache_time=1, is_personal=True)
            return

    results = []

    # Клавиатура под серией как в обычной отправке
    def _make_reply_markup(s_key: str, s: int, e: int):
        # Теперь используем динамическую навигацию из базы данных
        from season_keyboard_helper import get_dynamic_episodes_keyboard
        try:
            keyboard = get_dynamic_episodes_keyboard(s_key, s, e)
            return keyboard
        except Exception as e:
            logging.error(f"Ошибка создания клавиатуры для {s_key} {s}x{e}: {e}")
            # Fallback клавиатура
            return InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Назад в главное меню", callback_data="back_to_main_menu")]
            ])
    def add_result(s_key: str, s: int, e: int):
        # Теперь загружаем из базы данных
        from db import load_all_episodes
        try:
            episodes = load_all_episodes(s_key)
            episode_data = next((ep for ep in episodes if ep['season'] == s and ep['episode'] == e), None)
            if not episode_data or not episode_data.get('file_id') or episode_data.get('type') == 'stub' or not _is_valid_file_id(episode_data.get('file_id', '')):
                return
        except Exception as e:
            logging.error(f"Ошибка загрузки серии {s_key} {s}x{e}: {e}")
            return
            
        title_show = show_map[s_key]
        rid = f"{s_key}_{s}_{e}"
        title = f"{title_show} • сериал: Сезон {s}, Серия {e}"
        caption = f"<b>🎬 Серия {e}</b>\n<b>Сезон {s}</b>\n{title_show}"
        markup = _make_reply_markup(s_key, s, e)
        if episode_data.get('type') == 'video':
            results.append(InlineQueryResultCachedVideo(
                id=rid,
                video_file_id=episode_data['file_id'],
                title=title,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup
            ))
        else:
            results.append(InlineQueryResultCachedDocument(
                id=rid,
                document_file_id=episode_data['file_id'],
                title=title,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup
            ))

    # Если указаны шоу и сезон/серия
    if show and show in show_map and season:
        # Теперь загружаем из базы данных
        from db import load_all_episodes, load_all_seasons
        try:
            episodes = load_all_episodes(show)
            seasons = load_all_seasons(show)
            title_show = show_map[show]
            
            # Получаем максимальное количество серий в сезоне
            season_episodes = [ep for ep in episodes if ep['season'] == season]
            max_ep = len(season_episodes)
            
            if episode:
                # Ищем конкретную серию в базе данных
                episode_data = next((ep for ep in episodes if ep['season'] == season and ep['episode'] == episode), None)
                if episode_data and episode_data.get('file_id') and episode_data.get('type') != 'stub' and _is_valid_file_id(episode_data.get('file_id', '')):
                    rid = f"{show}_{season}_{episode}"
                    title = f"{title_show} • сериал: Сезон {season}, Серия {episode}"
                    caption = f"<b>🎬 Серия {episode}</b>\n<b>Сезон {season}</b>\n{title_show}"
                    markup = _make_reply_markup(show, season, episode)
                    if episode_data.get('type') == 'video':
                        res = InlineQueryResultCachedVideo(
                            id=rid,
                            video_file_id=episode_data['file_id'],
                            title=title,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=markup
                        )
                    else:
                        res = InlineQueryResultCachedDocument(
                            id=rid,
                            document_file_id=episode_data['file_id'],
                            title=title,
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=markup
                        )
                    try:
                        await query.answer([res], cache_time=1, is_personal=True)
                    except Exception:
                        # Молча не отдаём ничего, если file_id не подходит
                        await query.answer([], cache_time=1, is_personal=True)
                    return
            else:
                # Вывести доступные серии сезона как cached media (лимит 50)
                for ep_data in season_episodes[:50]:  # Лимит 50 результатов
                    e = ep_data['episode']
                    if not ep_data.get('file_id') or ep_data.get('type') == 'stub' or not _is_valid_file_id(ep_data.get('file_id', '')):
                        continue
                    rid = f"{show}_{season}_{e}"
                    title = f"{title_show} • сериал: Сезон {season}, Серия {e}"
                    caption = f"<b>🎬 Серия {e}</b>\n<b>Сезон {season}</b>\n{title_show}"
                    if ep_data.get('type') == 'video':
                        results.append(InlineQueryResultCachedVideo(
                            id=rid,
                            video_file_id=ep_data['file_id'],
                            title=title,
                            caption=caption,
                            parse_mode="HTML"
                        ))
                    else:
                        results.append(InlineQueryResultCachedDocument(
                            id=rid,
                            document_file_id=ep_data['file_id'],
                            title=title,
                            caption=caption,
                            parse_mode="HTML"
                        ))
                    if len(results) >= 50:
                        break
                try:
                    await query.answer(results, cache_time=1, is_personal=True)
                except Exception:
                    await query.answer([], cache_time=1, is_personal=True)
                return
        except Exception as e:
            logging.error(f"Ошибка при загрузке данных из базы для {show}: {e}")
            await query.answer([], cache_time=1, is_personal=True)
            return

    # Если задано только шоу без сезона — показать одну карточку с выбором сезонов (для RM/LBSC/PHF)
    if show and show in show_map and not season:
        if show == 'rm':
            text = "<b>Рик и Морти</b>\nВыберите сезон:"
            # Получаем постер из базы данных
            from db import load_all_seasons
            try:
                seasons = load_all_seasons('rm')
                max_season = max([s['season'] for s in seasons]) if seasons else 1
                thumb = SERIES_POSTERS.get('rm', {}).get(max_season)
            except:
                thumb = None
            art = InlineQueryResultArticle(
                id="rm_seasons",
                title="Рик и Морти — сезоны",
                input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
                reply_markup=get_seasons_keyboard(),
                description="Открыть список сезонов",
                thumb_url=thumb
            )
            await query.answer([art], cache_time=1, is_personal=True)
            return
        if show == 'lbsc':
            text = "<b>Леди Баг и Супер‑Кот</b>\nВыберите сезон:"
            thumb = SERIES_POSTERS.get('lbsc', {}).get('show')
            art = InlineQueryResultArticle(
                id="lbsc_seasons",
                title="Леди Баг и Супер‑Кот — сезоны",
                input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
                reply_markup=get_lbsc_seasons_keyboard(),
                description="Открыть список сезонов",
                thumb_url=thumb
            )
            await query.answer([art], cache_time=1, is_personal=True)
            return
        if show == 'phf':
            text = "<b>Финес и Ферб</b>\nВыберите сезон:"
            art = InlineQueryResultArticle(
                id="phf_seasons",
                title="Финес и Ферб — сезоны",
                input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
                reply_markup=get_phf_seasons_keyboard(),
                description="Открыть список сезонов"
            )
            await query.answer([art], cache_time=1, is_personal=True)
            return
        if show == 'loki':
            text = "<b>Локи (2021)</b>\nВыберите сезон:"
            thumb = SERIES_POSTERS.get('loki', {}).get('show')
            art = InlineQueryResultArticle(
                id="loki_seasons",
                title="Локи (2021) — сезоны",
                input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
                reply_markup=get_loki_seasons_keyboard(),
                description="Открыть список сезонов",
                thumb_url=thumb
            )
            await query.answer([art], cache_time=1, is_personal=True)
            return
        
        # Для других сериалов из базы данных - создаем динамическую клавиатуру
        if show in show_map:
            title = show_map[show]
            text = f"<b>{title}</b>\nВыберите сезон:"
            
            # Получаем постер из SERIES_POSTERS
            thumb = None
            if show in SERIES_POSTERS:
                poster_data = SERIES_POSTERS[show]
                if isinstance(poster_data, dict):
                    thumb = poster_data.get('show') or poster_data.get(max(poster_data.keys()) if poster_data else None)
                else:
                    thumb = poster_data
            
            try:
                from keyboards import get_dynamic_seasons_keyboard
                keyboard = get_dynamic_seasons_keyboard(show)
                art = InlineQueryResultArticle(
                    id=f"{show}_seasons",
                    title=f"{title} — сезоны",
                    input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"),
                    reply_markup=keyboard,
                    description="Открыть список сезонов",
                    thumb_url=thumb
                )
                await query.answer([art], cache_time=1, is_personal=True)
                return
            except Exception as e:
                logging.error(f"[INLINE_QUERY] Ошибка создания клавиатуры для {show}: {e}")

    # Непарсируемый запрос или пустой — показать подсказку и сообщение о том, что контент не найден
    if q:  # Если был введен поисковый запрос, но ничего не найдено
        not_found = InlineQueryResultArticle(
            id="not_found",
            title="Контент не найден",
            input_message_content=InputTextMessageContent(
                message_text=(
                    f"❌ <b>Контент не найден</b>\n\n"
                    f"К сожалению, фильм или сериал <b>\"{q}\"</b> не найден в нашей базе данных.\n\n"
                    f"Если вы хотите, чтобы мы добавили этот контент, свяжитесь с администратором:\n"
                    f"👉 /start → 💬 Связаться с админом"
                ),
                parse_mode="HTML"
            ),
            description=f"Фильм/сериал \"{q}\" отсутствует в базе",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Связаться с админом", callback_data="contact_admin_start")]
            ])
        )
        await query.answer([not_found], cache_time=1, is_personal=True)
    else:
        # Пустой запрос — показываем пустой результат
        await query.answer([], cache_time=1, is_personal=True)

def get_phf_episodes_keyboard(season):
    # Теперь используем базу данных вместо storage
    from db import load_all_episodes
    buttons = []
    row = []
    
    try:
        episodes = load_all_episodes("phf")
        season_episodes = [ep for ep in episodes if ep['season'] == season]
        season_episodes.sort(key=lambda x: x['episode'])
        
        for ep in season_episodes:
            episode = ep['episode']
            row.append(InlineKeyboardButton(text=f"🎬 Серия {episode}", callback_data=f"phf_episode_{season}_{episode}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
    except Exception as e:
        logging.error(f"Ошибка при загрузке серий PHF сезона {season}: {e}")
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад к сезонам", callback_data="choose_phf")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === Обработчики платежей Telegram Stars ===

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    """Обработчик pre-checkout запроса (обязательный для платежей)"""
    try:
        # Проверяем payload, чтобы понять, что покупают
        payload = pre_checkout_query.invoice_payload
        
        if payload in ["premium_2months", "premium_1year"]:
            # Подтверждаем заказ
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        else:
            # Отклоняем неизвестный заказ
            await bot.answer_pre_checkout_query(
                pre_checkout_query.id, 
                ok=False, 
                error_message="Неизвестный товар"
            )
    except Exception as e:
        logging.error(f"Error in pre_checkout_handler: {e}")
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id, 
            ok=False, 
            error_message="Ошибка обработки платежа"
        )


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    """Обработчик успешного платежа"""
    try:
        user_id = message.from_user.id
        payment = message.successful_payment
        payload = payment.invoice_payload
        payment_charge_id = payment.telegram_payment_charge_id
        
        # Определяем количество дней в зависимости от payload
        if payload == "premium_2months":
            days = 60
            period_text = "2 месяца"
        elif payload == "premium_1year":
            days = 365
            period_text = "1 год"
        else:
            await message.answer("❌ Ошибка: неизвестный тип премиума")
            return
        
        # Активируем премиум
        success = activate_premium(user_id, days, payment_charge_id)
        
        if success:
            await message.answer(
                f"✅ <b>Премиум активирован!</b>\n\n"
                f"Срок действия: <b>{period_text}</b>\n"
                f"Теперь вам доступны все функции:\n"
                f"• Безлимитный просмотр фильмов и сериалов\n"
                f"• Избранное\n"
                f"• Случайные фильмы и серии\n\n"
                f"Спасибо за покупку! 🎉",
                parse_mode="HTML"
            )
            logging.info(f"Premium activated for user {user_id} for {days} days (payment_id: {payment_charge_id})")
        else:
            await message.answer(
                "❌ Произошла ошибка при активации премиума. Пожалуйста, свяжитесь с поддержкой.",
                parse_mode="HTML"
            )
            logging.error(f"Failed to activate premium for user {user_id}")
            
    except Exception as e:
        logging.error(f"Error in successful_payment_handler: {e}")
        await message.answer(
            "❌ Произошла ошибка при обработке платежа. Пожалуйста, свяжитесь с поддержкой.",
            parse_mode="HTML"
        )

# === Обработчик показа file_id (перемещен в конец для правильного порядка) ===
@router.message(F.video | F.document | F.photo)
async def show_media_file_id(message: Message):
    """Авто-ответ с file_id на любое медиа от админа."""
    logging.info(f"[show_media_file_id] ⚠️ TRIGGERED! User {message.from_user.id} sent media")
    try:
        if message.from_user.id not in ADMIN_IDS:
            logging.info(f"[show_media_file_id] skip: sender is not ADMIN_ID ({message.from_user.id} not in {ADMIN_IDS})")
            return
    except Exception as e:
        logging.exception(f"[show_media_file_id] exception checking ADMIN_ID: {e}")
        return
    
    # Проверяем, не находится ли админ в процессе создания рассылки
    if message.from_user.id in broadcast_state:
        state = broadcast_state[message.from_user.id]
        if state.get("step") in ["content", "custom_button"]:
            logging.info(f"[show_media_file_id] skip: admin {message.from_user.id} is creating broadcast")
            return
    
    # Проверяем состояние техподдержки (только его пропускаем)
    if message.from_user.id in tech_support_state:
        logging.info(f"[show_media_file_id] skip: admin {message.from_user.id} is in tech support state")
        return
    
    fid = None
    media_type = None
    try:
        if message.video:
            fid = message.video.file_id
            media_type = 'video'
        elif message.document:
            fid = message.document.file_id
            media_type = 'document'
        elif message.photo:
            # Берём наибольшее превью
            fid = message.photo[-1].file_id
            media_type = 'photo'
    except Exception:
        fid = None
    if fid:
        await message.reply(f"Тип: <b>{media_type}</b>\nfile_id:\n<code>{fid}</code>", parse_mode="HTML") 