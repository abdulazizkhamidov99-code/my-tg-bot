import logging
import os
import uuid
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

session = AiohttpSession(timeout=600)
bot = Bot(token=TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
router = Router()

user_files = {}

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет! Я твой надежный загрузчик медиа 24/7!</b>\n\n"
        "• Отправь мне <u>обычное видео</u>, и я верну его тебе обратно.\n"
        "• Отправь мне <u>ссылку</u> из <b>YouTube, TikTok или Instagram</b>, и я моментально скачаю её!"
    )

@router.message(F.video)
async def handle_video(message: Message):
    video_id = message.video.file_id
    file_unique_id = str(uuid.uuid4())
    msg = await message.answer("⏳ Скачиваю видео...")
    
    file_info = await bot.get_file(video_id)
    input_video_path = f"downloads/{file_unique_id}.mp4"
    os.makedirs("downloads", exist_ok=True)
    
    await bot.download_file(file_info.file_path, destination=input_video_path)
    user_files[message.from_user.id] = input_video_path
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Вернуть видео обратно", callback_data="get_video")]
    ])
    await msg.edit_text("Файл успешно сохранен! Нажмите кнопку для выдачи:", reply_markup=keyboard)

@router.message(F.text.startswith("http"))
async def handle_links(message: Message):
    url = message.text
    user_id = message.from_user.id
    
    allowed_platforms = ["tiktok.com", "instagram.com", "youtube.com", "youtu.be"]
    if not any(platform in url for platform in allowed_platforms):
        await message.answer("❌ Отправьте ссылку на YouTube, TikTok или Instagram.")
        return
        
    msg = await message.answer("⏳ Подключаюсь к шлюзу загрузки...")
    file_unique_id = str(uuid.uuid4())
    os.makedirs("downloads", exist_ok=True)
    
    api_url = "https://wuk.sh"
    payload = {"url": url, "vQuality": "720"}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                result = await resp.json()
                download_url = result.get("url")
                
                if not download_url:
                    await msg.edit_text("❌ Не удалось найти файл. Возможно, видео приватное.")
                    return
                
                await msg.edit_text("⏳ Загружаю медиа на сервер...")
                actual_path = f"downloads/{file_unique_id}.mp4"
                
                async with session.get(download_url) as file_resp:
                    if file_resp.status == 200:
                        with open(actual_path, 'wb') as f:
                            f.write(await file_resp.read())
                
                if os.path.exists(actual_path) and os.path.getsize(actual_path) > 0:
                    user_files[user_id] = actual_path
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🎬 Скачать Видео", callback_data="get_video")],
                        [InlineKeyboardButton(text="🎵 Скачать только Звук (MP3)", callback_data="get_audio")]
                    ])
                    await msg.edit_text("Медиа успешно загружено! Выберите формат:", reply_markup=keyboard)
                else:
                    await msg.edit_text("❌ Ошибка сохранения файла.")
                    
    except Exception as e:
        logging.error(f"Ошибка API: {e}")
        await msg.edit_text("❌ Шлюз загрузки временно недоступен.")

@router.callback_query(F.data.in_(["get_audio", "get_video"]))
async def process_choice(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    choice = callback_query.data
    
    if user_id not in user_files:
        await callback_query.message.answer("Файл устарел. Отправьте ссылку заново.")
        return

    video_path = user_files[user_id]
    msg = callback_query.message
    
    if choice == "get_audio":
        await msg.edit_text("⏳ Извлекаю аудиодорожку...")
        audio_path = f"{video_path}.mp3"
        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', video_path, 
                '-vn', '-acodec', 'libmp3lame', '-q:a', '2', audio_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            await bot.send_audio(chat_id=user_id, audio=FSInputFile(audio_path), caption="🎵 Аудио готово!")
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"Ошибка аудио: {e}")
        finally:
            cleanup(video_path, audio_path)
            if user_id in user_files: del user_files[user_id]

    elif choice == "get_video":
        await msg.edit_text("⏳ Отправляю видеоролик...")
        try:
            await bot.send_video(chat_id=user_id, video=FSInputFile(video_path), caption="🎬 Ваше видео!")
            await msg.delete()
        except Exception as e:
            await msg.edit_text(f"Ошибка видео: {e}")
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
