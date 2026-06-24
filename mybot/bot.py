import logging
import os
import uuid
import subprocess
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# === СЮДА ВСТАВЬТЕ ТОКЕН, КОТОРЫЙ ДАЛ BOTFATHER ===
TOKEN = "8893637979:AAFR9K6S2taPicBGO6_OQzDgOsKhk6hTWoo"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
router = Router()
user_videos = {}

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("👋 Привет! Отправь мне видеоролик, и я помогу забрать из него звук или вернуть видео обратно.")

@router.message(F.video)
async def handle_video(message: Message):
    video_id = message.video.file_id
    file_unique_id = str(uuid.uuid4())
    
    msg = await message.answer("⏳ Скачиваю видео из Telegram...")
    
    file_info = await bot.get_file(video_id)
    input_video_path = f"downloads/{file_unique_id}.mp4"
    os.makedirs("downloads", exist_ok=True)
    
    await bot.download_file(file_info.file_path, destination=input_video_path)
    user_videos[message.from_user.id] = input_video_path
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 Вырезать звук (MP3)", callback_data="get_audio")],
        [InlineKeyboardButton(text="🎬 Вернуть видео", callback_data="get_video")]
    ])
    
    await msg.edit_text("Что нужно сделать с видео?", reply_markup=keyboard)

@router.callback_query(F.data.in_(["get_audio", "get_video"]))
async def process_choice(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    choice = callback_query.data
    
    if user_id not in user_videos:
        await callback_query.message.answer("Файл не найден. Отправьте видео еще раз.")
        return

    video_path = user_videos[user_id]
    msg = callback_query.message
    
    if choice == "get_audio":
        await msg.edit_text("⏳ Извлекаю дорожку... Подождите...")
        audio_path = f"{video_path}.mp3"
        
        try:
            # Запуск ffmpeg.exe, который лежит в той же папке
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, 
                '-vn', '-acodec', 'libmp3lame', '-q:a', '2', audio_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            audio_file = FSInputFile(audio_path)
            await bot.send_audio(chat_id=user_id, audio=audio_file, caption="🎵 Готово!")
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"Произошла ошибка: {e}")
        finally:
            cleanup(video_path, audio_path)
            del user_videos[user_id]

    elif choice == "get_video":
        await msg.edit_text("⏳ Отправляю видео обратно...")
        video_file = FSInputFile(video_path)
        await bot.send_video(chat_id=user_id, video=video_file, caption="🎬 Ваше видео!")
        await msg.delete()
        cleanup(video_path)
        del user_videos[user_id]

def cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            os.remove(p)

async def main():
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
