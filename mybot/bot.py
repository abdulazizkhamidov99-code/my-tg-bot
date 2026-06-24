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
from yt_dlp import YoutubeDL

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
        "• Отправь мне <u>ссылку</u> из <b>YouTube, Shorts, TikTok, Instagram, VK или Pinterest</b>, и я скачаю её!"
    )

# --- 1. Обработчик видеофайлов ---
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

# --- 2. Универсальный обработчик ссылок ---
@router.message(F.text.startswith("http"))
async def handle_links(message: Message):
    url = message.text
    user_id = message.from_user.id
    
    allowed_platforms = ["tiktok.com", "instagram.com", "youtube.com", "youtu.be", "vk.com", "pinterest.com"]
    if not any(platform in url for platform in allowed_platforms):
        await message.answer("❌ Ссылка не поддерживается. Отправьте ссылку на YouTube, TikTok, Instagram, VK или Pinterest.")
        return
        
    msg = await message.answer("⏳ Подключаюсь к платформе и скачиваю контент...")
    file_unique_id = str(uuid.uuid4())
    os.makedirs("downloads", exist_ok=True)
    output_template = f"downloads/{file_unique_id}.%(ext)s"
    
       ydl_opts = {
        'outtmpl': output_template,
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        # УСИЛЕННЫЙ ОБХОД БЛОКИРОВОК YOUTUBE
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'no_color': True,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        }
    }
    
    try:
        loop = asyncio.get_event_loop()
        with YoutubeDL(ydl_opts) as ydl:
            await loop.run_in_executor(None, lambda: ydl.download([url]))
            
        actual_path = f"downloads/{file_unique_id}.mp4"
    # Автоматически находим правильное расширение скачанного файла
for ext in ['mp4', 'mkv', 'webm', '3gp']:
if os.path.exists(f"downloads/{file_unique_id}.{ext}"):
        actual_path = f"downloads/{file_unique_id}.{ext}"
        break
        if os.path.exists(actual_path):
            user_files[user_id] = actual_path
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Скачать Видео", callback_data="get_video")],
                [InlineKeyboardButton(text="🎵 Скачать звук + Найти оригинал", callback_data="get_audio")]
            ])
            await msg.edit_text("Медиа успешно загружено из сети! Что вы хотите получить?", reply_markup=keyboard)
        else:
            await msg.edit_text("❌ Сервер не смог сохранить файл. Возможно, видео скрыто приватностью.")
            
    except Exception as e:
        logging.error(f"Ошибка скачивания ссылки: {e}")
        await msg.edit_text("❌ Не удалось загрузить медиа по этой ссылке.")

# --- Облачное распознавание музыки (Замена тяжелого Shazam) ---
async def recognize_audio_cloud(audio_path):
    try:
        # Используем бесплатное открытое API для быстрого сканирования аудио слепков
        async with aiohttp.ClientSession() as session:
            # Отправляем только первые 500КБ аудио для мгновенного распознавания
            with open(audio_path, 'rb') as f:
                audio_data = f.read(500000)
            
            async with session.post('https://audd.io', data={'file': audio_data, 'return': 'apple_music'}) as resp:
                result = await resp.json()
                if result and result.get('status') == 'success' and result.get('result'):
                    res = result['result']
                    return res.get('title'), res.get('artist')
    except Exception as e:
        logging.error(f"Ошибка облачного распознавания: {e}")
    return None, None

# --- Поиск полной оригинальной песни ---
async def download_full_track_by_name(search_query, user_id):
    file_unique_id = str(uuid.uuid4())
    output_path = f"downloads/full_{file_unique_id}"
        ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path + '.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }
    }
    try:
        loop = asyncio.get_event_loop()
        with YoutubeDL(ydl_opts) as ydl:
            await loop.run_in_executor(None, lambda: ydl.download([f"ytsearch1:{search_query}"]))
        final_mp3 = f"{output_path}.mp3"
        if os.path.exists(final_mp3):
            return final_mp3
    except Exception as e:
        logging.error(f"Ошибка поиска трека: {e}")
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
            
            # Запускаем быстрое облачное распознавание трека
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
