import logging
import os
import uuid
import subprocess
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

# Увеличенный таймаут для загрузки тяжелых видео
session = AiohttpSession(timeout=600)
bot = Bot(token=TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
router = Router()

user_files = {}

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет! Я твой личный супер-загрузчик медиа!</b>\n\n"
        "• Отправь мне <u>обычное видео</u>, и я извлеку звук + распознаю трек как Shazam!\n"
        "• Отправь мне <u>ссылку</u> из <b>YouTube, Shorts, TikTok или Instagram</b>, и я скачаю её!"
    )

# --- 1. Обработчик обычных видеофайлов из Telegram ---
@router.message(F.video)
async def handle_video(message: Message):
    video_id = message.video.file_id
    file_unique_id = str(uuid.uuid4())
    
    msg = await message.answer("⏳ Скачиваю видео файл из Telegram...")
    
    file_info = await bot.get_file(video_id)
    input_video_path = f"downloads/{file_unique_id}.mp4"
    os.makedirs("downloads", exist_ok=True)
    
    await bot.download_file(file_info.file_path, destination=input_video_path)
    user_files[message.from_user.id] = input_video_path
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Вырезать звук + Найти оригинал", callback_data="get_audio")],
        [InlineKeyboardButton(text="🎬 Вернуть видео обратно", callback_data="get_video")]
    ])
    await msg.edit_text("Что нужно сделать с видеофайлом?", reply_markup=keyboard)

# --- 2. Облачный обработчик ссылок через бесплатное стабильное API ---
@router.message(F.text.startswith("http"))
async def handle_links(message: Message):
    url = message.text
    user_id = message.from_user.id
    
    allowed_platforms = ["tiktok.com", "instagram.com", "youtube.com", "youtu.be"]
    if not any(platform in url for platform in allowed_platforms):
        await message.answer("❌ Ссылка не поддерживается. Отправьте ссылку на YouTube, TikTok или Instagram.")
        return
        
    msg = await message.answer("⏳ Подключаюсь к облачному шлюзу загрузки...")
    file_unique_id = str(uuid.uuid4())
    os.makedirs("downloads", exist_ok=True)
    
    # Используем стабильное публичное API для обхода любых банов YouTube/Insta
    api_url = f"https://cobalt.tools"
    payload = {"url": url, "vQuality": "720"}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    await msg.edit_text("❌ Облачный сервер сейчас перегружен. Попробуйте позже.")
                    return
                
                result = await resp.json()
                download_url = result.get("url")
                
                if not download_url:
                    await msg.edit_text("❌ Не удалось найти видео по этой ссылке. Возможно, оно приватное.")
                    return
                
                await msg.edit_text("⏳ Скачиваю файл на сервер бота...")
                
                # Скачиваем готовый чистый файл по выданной ссылке
                actual_path = f"downloads/{file_unique_id}.mp4"
                async with session.get(download_url) as file_resp:
                    if file_resp.status == 200:
                        with open(actual_path, 'wb') as f:
                            f.write(await file_resp.read())
                
                if os.path.exists(actual_path) and os.path.getsize(actual_path) > 0:
                    user_files[user_id] = actual_path
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🎬 Скачать Видео", callback_data="get_video")],
                        [InlineKeyboardButton(text="🎵 Скачать звук + Найти оригинал", callback_data="get_audio")]
                    ])
                    await msg.edit_text("Медиа успешно загружено из сети! Что вы хотите получить?", reply_markup=keyboard)
                else:
                    await msg.edit_text("❌ Не удалось сохранить файл на сервере.")
                    
    except Exception as e:
        logging.error(f"Ошибка API скачивания: {e}")
        await msg.edit_text("❌ Ошибка при соединении с сервером загрузки.")

# --- Облачное распознавание музыки (Замена Shazam) ---
async def recognize_audio_cloud(audio_path):
    try:
        async with aiohttp.ClientSession() as session:
            with open(audio_path, 'rb') as f:
                audio_data = f.read(500000)
            async with session.post('https://audd.io', data={'file': audio_data}) as resp:
                result = await resp.json()
                if result and result.get('status') == 'success' and result.get('result'):
                    res = result['result']
                    return res.get('title'), res.get('artist')
    except Exception as e:
        logging.error(f"Ошибка распознавания: {e}")
    return None, None

# --- Поиск полной оригинальной песни на YouTube ---
async def download_full_track_by_name(search_query, user_id):
    file_unique_id = str(uuid.uuid4())
    output_path = f"downloads/full_{file_unique_id}"
    
    # Для поиска по названию используем то же надежное облачное API
    api_url = f"https://cobalt.tools"
    payload = {"url": f"ytsearch1:{search_query}", "audioOnly": True}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                result = await resp.json()
                download_url = result.get("url")
                if download_url:
                    final_mp3 = f"{output_path}.mp3"
                    async with session.get(download_url) as file_resp:
                        with open(final_mp3, 'wb') as f:
                            f.write(await file_resp.read())
                    return final_mp3
    except Exception as e:
        logging.error(f"Ошибка поиска полного трека: {e}")
    return None

# --- 3. Логика кнопок выдачи контента ---
@router.callback_query(F.data.in_(["get_audio", "get_video"]))
async def process_choice(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    choice = callback_query.data
    
    if user_id not in user_files:
        await callback_query.message.answer("Файл устарел. Отправьте медиа заново.")
        return

    video_path = user_files[user_id]
    msg = callback_query.message
    
    if choice == "get_audio":
        await msg.edit_text("⏳ Извлекаю аудио и сканирую дорожку...")
        audio_path = f"{video_path}.mp3"
        
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, 
                '-vn', '-acodec', 'libmp3lame', '-q:a', '2', audio_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            track_title, track_artist = await recognize_audio_cloud(audio_path)
            
            audio_file = FSInputFile(audio_path)
            await bot.send_audio(chat_id=user_id, audio=audio_file, caption="🎵 Звук из видео успешно извлечен!")
            
            if track_title and track_artist:
                search_name = f"{track_artist} - {track_title}"
                await bot.send_message(chat_id=user_id, text=f"🔍 Сканер определил трек: <b>{search_name}</b>\n⏳ Ищу полную оригинальную песню...")
                
                full_audio_path = await download_full_track_by_name(search_name, user_id)
                if full_audio_path and os.path.exists(full_audio_path):
                    full_audio_file = FSInputFile(full_audio_path)
                    await bot.send_audio(
                        chat_id=user_id, 
                        audio=full_audio_file, 
                        caption=f"🎧 <b>Полный оригинальный трек!</b>\n📌 Название: {track_title}\n👤 Исполнитель: {track_artist}"
                    )
                    cleanup(full_audio_path)
                else:
                    await bot.send_message(chat_id=user_id, text="❌ Не удалось скачать оригинальный трек целиком.")
            else:
                await bot.send_message(chat_id=user_id, text="ℹ️ Не удалось автоматически определить название песни.")
                
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"Ошибка обработки звука: {e}")
        finally:
            cleanup(video_path, audio_path)
            if user_id in user_files: del user_files[user_id]

    elif choice == "get_video":
        await msg.edit_text("⏳ Загружаю видеоролик в Telegram...")
        try:
            video_file = FSInputFile(video_path)
            await bot.send_video(chat_id=user_id, video=video_file, caption="🎬 Держите ваше видео!")
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"Ошибка отправки видео: {e}")
        finally:
            cleanup(video_path)
            if user_id in user_files: del user_files[user_id]

def cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try: os.remove(p)
            except: pass

async def main():
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
