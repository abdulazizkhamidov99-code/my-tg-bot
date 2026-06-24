import logging
import os
import uuid
import subprocess
import asyncio
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession
from yt_dlp import YoutubeDL
from shazamio import Shazam

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

# Таймаут 5 минут для загрузки тяжелых файлов
session = AiohttpSession(timeout=300)
bot = Bot(token=TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
router = Router()

user_files = {}

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет! Я продвинутый медиа-бот!</b>\n\n"
        "• Отправь мне <u>обычное видео</u>, и я извлеку звук + найду полный трек через Shazam!\n"
        "• Отправь мне <u>ссылку из TikTok или Instagram</u>, и я скачаю её!"
    )

# --- 1. Обработчик обычных видеофайлов ---
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
        [InlineKeyboardButton(text="🎬 Вернуть видео", callback_data="get_video")]
    ])
    await msg.edit_text("Что нужно сделать с видеофайлом?", reply_markup=keyboard)

# --- 2. Обработчик ссылок (TikTok, Instagram) ---
@router.message(F.text.startswith("http"))
async def handle_links(message: Message):
    url = message.text
    user_id = message.from_user.id
    
    if "tiktok.com" not in url and "instagram.com" not in url:
        await message.answer("❌ Я поддерживаю только ссылки из TikTok и Instagram.")
        return
        
    msg = await message.answer("⏳ Анализирую ссылку и загружаю контент...")
    file_unique_id = str(uuid.uuid4())
    os.makedirs("downloads", exist_ok=True)
    output_template = f"downloads/{file_unique_id}.%(ext)s"
    
    ydl_opts = {
        'outtmpl': output_template,
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        loop = asyncio.get_event_loop()
        with YoutubeDL(ydl_opts) as ydl:
            await loop.run_in_executor(None, lambda: ydl.download([url]))
            
        actual_path = f"downloads/{file_unique_id}.mp4"
        
        if os.path.exists(actual_path):
            user_files[user_id] = actual_path
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Скачать Видео", callback_data="get_video")],
                [InlineKeyboardButton(text="🎵 Скачать звук + Найти оригинал", callback_data="get_audio")]
            ])
            await msg.edit_text("Медиа успешно загружено! Что вы хотите получить?", reply_markup=keyboard)
        else:
            await msg.edit_text("❌ Не удалось сохранить файл. Попробуйте другую ссылку.")
            
    except Exception as e:
        logging.error(f"Ошибка yt-dlp: {e}")
        await msg.edit_text("❌ Ошибка при скачивании. Возможно, профиль автора закрыт или ссылка неверна.")

# --- Функция поиска полной песни по названию ---
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
    }
    
    try:
        loop = asyncio.get_event_loop()
        with YoutubeDL(ydl_opts) as ydl:
            # Ищем песню на YouTube по ключевым словам от Shazam
            await loop.run_in_executor(None, lambda: ydl.download([f"ytsearch1:{search_query}"]))
        
        final_mp3 = f"{output_path}.mp3"
        if os.path.exists(final_mp3):
            return final_mp3
    except Exception as e:
        logging.error(f"Ошибка скачивания полного трека: {e}")
    return None

# --- 3. Логика кнопок ---
@router.callback_query(F.data.in_(["get_audio", "get_video"]))
async def process_choice(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    choice = callback_query.data
    
    if user_id not in user_files:
        await callback_query.message.answer("Файл не найден. Отправьте медиа заново.")
        return

    video_path = user_files[user_id]
    msg = callback_query.message
    
    if choice == "get_audio":
        await msg.edit_text("⏳ Вырезаю звук и отправляю в Shazam...")
        audio_path = f"{video_path}.mp3"
        
        try:
            # 1. Вырезаем кусок звука
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, 
                '-vn', '-acodec', 'libmp3lame', '-q:a', '2', audio_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 2. Пытаемся распознать трек через Shazam
            shazam = Shazam()
            shazam_result = await shazam.recognize(audio_path)
            
            track_title = None
            track_artist = None
            
            if shazam_result and 'track' in shazam_result:
                track_title = shazam_result['track'].get('title')
                track_artist = shazam_result['track'].get('subtitle')
            
            # Отправляем сначала обычную дорожку из видео
            audio_file = FSInputFile(audio_path)
            await bot.send_audio(chat_id=user_id, audio=audio_file, caption="🎵 Звук из вашего видео готов!")
            
            # 3. Если Shazam нашел песню, ищем полную версию в интернете
            if track_title and track_artist:
                search_name = f"{track_artist} - {track_title}"
                await bot.send_message(chat_id=user_id, text=f"🔍 Shazam определил трек: <b>{search_name}</b>\n⏳ Ищу и скачиваю полную оригинальную песню...")
                
                full_audio_path = await download_full_track_by_name(search_name, user_id)
                
                if full_audio_path and os.path.exists(full_audio_path):
                    # Отправляем красивый полный оригинальный трек
                    full_audio_file = FSInputFile(full_audio_path)
                    await bot.send_audio(
                        chat_id=user_id, 
                        audio=full_audio_file, 
                        caption=f"🎧 <b>Полный оригинальный трек найден!</b>\n Название: {track_title}\n Исполнитель: {track_artist}"
                    )
                    cleanup(full_audio_path)
                else:
                    await bot.send_message(chat_id=user_id, text="❌ К сожалению, не удалось скачать полную версию трека.")
            else:
                await bot.send_message(chat_id=user_id, text="ℹ️ Shazam не смог распознать музыку из этого видео.")
                
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"Ошибка: {e}")
        finally:
            cleanup(video_path, audio_path)
            if user_id in user_files: del user_files[user_id]

    elif choice == "get_video":
        await msg.edit_text("⏳ Отправляю видеоролик...")
        try:
            video_file = FSInputFile(video_path)
            await bot.send_video(chat_id=user_id, video=video_file, caption="🎬 Ваше видео!")
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
