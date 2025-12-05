import os
import asyncio
import logging
import sqlite3
import io
from typing import List, Tuple
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InputMediaPhoto
from aiogram.filters import Command
from aiogram.enums import ParseMode
from PIL import Image

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN", "8243631747:AAGG1oXJoyJbHGYsEswHqU3I6EUkphYnrQA")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1382280046"))

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
router = Router()

# База данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('/data/products.db', check_same_thread=False)
        self.init_db()
    
    def init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article TEXT NOT NULL,
                image_hash TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_article ON products(article)')
        self.conn.commit()
    
    def add_product(self, article: str, image_hash: str, file_id: str):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO products (article, image_hash, file_id) VALUES (?, ?, ?)',
            (article, image_hash, file_id)
        )
        self.conn.commit()
    
    def find_similar(self, image_hash: str, limit: int = 5) -> List[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT article, file_id, image_hash FROM products')
        all_products = cursor.fetchall()
        
        results = []
        for article, file_id, stored_hash in all_products:
            similarity = self.calculate_similarity(image_hash, stored_hash)
            if similarity > 0.7:
                results.append((article, file_id, similarity))
        
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:limit]
    
    def calculate_similarity(self, hash1: str, hash2: str) -> float:
        if len(hash1) != len(hash2):
            return 0.0
        matches = sum(1 for a, b in zip(hash1, hash2) if a == b)
        return matches / len(hash1)
    
    def get_all_articles(self) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT article FROM products')
        return [row[0] for row in cursor.fetchall()]
    
    def get_by_article(self, article: str) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT file_id FROM products WHERE article = ?', (article,))
        return [row[0] for row in cursor.fetchall()]

db = Database()

# Функции
def image_to_hash(image_bytes: bytes) -> str:
    """Конвертирует изображение в хэш-строку"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.resize((16, 16), Image.Resampling.LANCZOS).convert('L')
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        return ''.join(['1' if p > avg else '0' for p in pixels])
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}")
        return ""

# Хранилище для добавления товаров
temp_storage = {}

# Команды
@router.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "🛍️ Бот для поиска товаров по фото\n\n"
        "📌 Команды:\n"
        "/add - добавить товар\n"
        "/search - найти похожий\n"
        "/list - все артикулы\n"
        "/view АРТИКУЛ - товары по артикулу"
    )

@router.message(Command("add"))
async def add_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только для администратора")
        return
    await message.answer("📸 Отправьте фото товара, затем артикул")

@router.message(Command("search"))
async def search_cmd(message: Message):
    await message.answer("📸 Отправьте фото для поиска похожих товаров")

@router.message(Command("list"))
async def list_cmd(message: Message):
    articles = db.get_all_articles()
    if articles:
        await message.answer("📋 Артикулы:\n" + "\n".join(sorted(articles)))
    else:
        await message.answer("📭 База пуста")

# Обработка фото
@router.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    
    try:
        # Скачиваем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_data = file_bytes.read()
        
        # Конвертируем в хэш
        image_hash = image_to_hash(image_data)
        if not image_hash:
            await message.answer("❌ Ошибка обработки фото")
            return
        
        # Если админ - предполагаем добавление
        if user_id == ADMIN_ID:
            temp_storage[user_id] = {
                'file_id': photo.file_id,
                'image_hash': image_hash
            }
            await message.answer("✅ Фото получено. Отправьте артикул")
        else:
            # Поиск для всех
            results = db.find_similar(image_hash)
            
            if not results:
                await message.answer("❌ Похожих товаров не найдено")
                return
            
            # Показываем результаты
            response = ["🔍 Найдено:"]
            sent_articles = set()
            
            for i, (article, file_id, similarity) in enumerate(results[:5], 1):
                if article not in sent_articles:
                    response.append(f"{i}. {article} ({similarity:.1%})")
                    sent_articles.add(article)
                    
                    try:
                        await bot.send_photo(
                            message.chat.id,
                            file_id,
                            caption=f"Артикул: {article}"
                        )
                    except:
                        response.append(f"   (фото недоступно)")
            
            await message.answer("\n".join(response))
            
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка обработки")

# Обработка текста
@router.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Добавление товара
    if user_id in temp_storage:
        data = temp_storage.pop(user_id)
        db.add_product(text, data['image_hash'], data['file_id'])
        await message.answer(f"✅ Товар '{text}' добавлен!")
    
    # Просмотр по артикулу
    elif text.startswith('/view '):
        article = text[6:].strip()
        files = db.get_by_article(article)
        
        if not files:
            await message.answer(f"❌ Артикул '{article}' не найден")
            return
        
        # Отправляем фото
        media = [InputMediaPhoto(media=file_id) for file_id in files[:10]]
        await bot.send_media_group(message.chat.id, media)
        await message.answer(f"📦 Товары: {article}")
    
    elif text == '/list':
        articles = db.get_all_articles()
        if articles:
            await message.answer("📋 Артикулы:\n" + "\n".join(sorted(articles)))
        else:
            await message.answer("📭 База пуста")

# Запуск
async def main():
    dp = Dispatcher()
    dp.include_router(router)
    
    logger.info("🤖 Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
