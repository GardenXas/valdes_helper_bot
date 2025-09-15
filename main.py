# -*- coding: utf-8 -*-

# --- 1. ИМПОРТЫ И НАЧАЛЬНАЯ НАСТРОЙКА ---
import discord
from discord import ui, app_commands
from discord.ext import commands, tasks
import google.generativeai as genai
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
from PIL import Image
import io
import json
import random
import string
from datetime import datetime, time, timezone
import sys
import asyncio
import pytesseract
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import re
import aiohttp
from fontTools.ttLib import TTFont # <-- ИМПОРТ ДЛЯ ПРОВЕРКИ СИМВОЛОВ

# Загрузка переменных окружения из файла .env
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAIN_GUILD_ID = os.getenv("MAIN_GUILD_ID")
ADMIN_GUILD_ID = os.getenv("ADMIN_GUILD_ID")
CODE_CHANNEL_ID = os.getenv("CODE_CHANNEL_ID")
OWNER_USER_ID = os.getenv("OWNER_USER_ID")
LORE_CHANNEL_IDS = os.getenv("LORE_CHANNEL_IDS")


# Проверяем, что все ID и ключи на месте
if not all([DISCORD_TOKEN, GEMINI_API_KEY, MAIN_GUILD_ID, ADMIN_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID, LORE_CHANNEL_IDS]):
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Один из ключей или ID (DISCORD_TOKEN, GEMINI_API_KEY, *_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID, LORE_CHANNEL_IDS) не найден в .env")

# Настройка API Gemini
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- 2. ГЛОБАЛЬНАЯ ПЕРЕМЕННАЯ И ФУНКЦИЯ ДЛЯ ЛОРА ---
VALDES_LORE = ""

def load_lore_from_file():
    """Загружает/перезагружает лор из файла в память бота."""
    global VALDES_LORE
    try:
        with open("file.txt", "r", encoding="utf-8") as f:
            VALDES_LORE = f.read()
        print("Лор успешно загружен/обновлен в память.")
    except FileNotFoundError:
        print("КРИТИЧЕСКАЯ ОШИБКА: Файл 'file.txt' не найден.")
        VALDES_LORE = "Лор не был загружен из-за отсутствия файла."

# --- НОВЫЙ КЛАСС ДЛЯ "ОЧИСТКИ" ТЕКСТА ---
class CharacterSanitizer:
    def __init__(self, font_path):
        try:
            font = TTFont(font_path)
            self.supported_chars = set()
            for table in font['cmap'].tables:
                self.supported_chars.update(table.cmap.keys())
            print(f"Загружен шрифт {font_path}, найдено {len(self.supported_chars)} поддерживаемых символов.")
        except Exception as e:
            print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить cmap для шрифта {font_path}: {e}")
            self.supported_chars = set()

    def sanitize(self, text: str) -> str:
        if not self.supported_chars:
            return text
        
        sanitized_chars = []
        for char in str(text): # Убедимся что работаем со строкой
            if ord(char) in self.supported_chars:
                sanitized_chars.append(char)
            else:
                sanitized_chars.append('?') # Заменяем неподдерживаемый символ
        return "".join(sanitized_chars)


# --- 3. СИСТЕМНЫЕ ПРОМПТЫ ---
def get_optimizer_prompt(level):
    """Возвращает системный промпт для оптимизации РП-постов."""
    return f"""
Ты — ассистент для текстового ролевого проекта 'Вальдес'. Твоя задача — идеально отформатировать и, при необходимости, улучшить пост игрока.

**КЛЮЧЕВЫЕ ПРАВИЛА ОФОРМЛЕНИЯ ПОСТА (САМОЕ ВАЖНОЕ):**
1.  **ДЕЙСТВИЯ:** Все действия персонажа должны быть заключены в двойные звездочки. Пример: `**Он поднялся с кровати.**`
2.  **МЫСЛИ И ЗВУКИ:** Все мысли персонажа, а также напевание, мычание и т.д., должны быть заключены в обычные кавычки. Пример: `"Какой сегодня прекрасный день."` или `"Ммм-хмм..."`
3.  **РЕЧЬ:** Вся прямая речь персонажа должна начинаться с дефиса и пробела. Пример: `- Доброе утро.`
4.  Каждый тип (действие, мысль, речь) **ОБЯЗАН** начинаться с новой строки для читаемости.

**ЗОЛОТЫЕ ПРАВИЛА ОБРАБОТКИ:**
1.  **ПОВЕСТВОВАНИЕ ОТ ТРЕТЬЕГО ЛИЦА:** Все действия персонажа должны быть написаны от **третьего лица** (Он/Она), даже если игрок написал от первого ('Я делаю').
2.  **ЗАПРЕТ НА СИМВОЛЫ:** ЗАПРЕЩЕНО использовать любые другие символы для оформления, кроме `** **`, `" "` и `- `. Никаких `()`, `<<>>` и прочего.
3.  **НЕ БЫТЬ СОАВТОРОМ:** Не добавляй новых действий или мотивации, которых не было в исходном тексте.

**ТВОЙ ПРОЦЕСС РАБОТЫ (КАК РАЗБИРАТЬ ТЕКСТ):**
Когда получаешь слитный текст от игрока, ты должен мысленно разделить его:
1.  Прочитай всё предложение.
2.  Найди слова-маркеры речи, такие как "говоря", "сказал", "крикнул". Текст после них — это прямая речь.
3.  Найди слова-маркеры звуков, такие как "напевая", "мыча". Текст после них — это звук в кавычках.
4.  Всё остальное — это действия.
5.  Собери разобранные части в пост, применяя 'КЛЮЧЕВЫЕ ПРАВИЛА ОФОРМЛЕНИЯ'.

**ПРИМЕР РАЗБОРА СЛОЖНОГО ПОСТА:**
*   **Текст игрока:** `я встаю с пола и иду на улицу напивая ляляля и говоря какой прекрасный этот день`
*   **ТВОЙ ПРАВИЛЬНЫЙ РЕЗУЛЬТАТ:**
    **Он встает с пола и идет на улицу.**
    "Ля-ля-ля..."
    - Какой прекрасный этот день!

---
**ЗАДАЧА 1: ПРОВЕРКА НА ГРУБЫЕ ЛОРНЫЕ ОШИБКИ**
(Проверка на современную технику, магию и т.д. Если нашел — верни "ОШИБКА:")

**ЗАДАЧА 2: ОПТИМИЗАЦИЯ ПОСТА (если ошибок нет)**
Обработай пост согласно уровню '{level}', соблюдая ВСЕ вышеописанные правила.

*   **Уровень 'Минимальные правки':**
    *   Твоя единственная задача — разобрать текст игрока на действия, мысли/звуки и речь и **ПЕРЕФОРМАТИРОВАТЬ** его согласно правилам.
    *   Переведи действия в третье лицо.
    *   **ЗАПРЕЩЕНО** добавлять, убирать или изменять слова, кроме смены лица повествования (я -> он/она). Только форматирование.

*   **Уровень 'Стандартная оптимизация':**
    *   Выполни все требования 'Минимальных правок'.
    *   Исправь грамматические ошибки.
    *   Можешь добавить **ОДНО** короткое предложение, описывающее эмоцию или деталь окружения.

*   **Уровень 'Максимальная креативность':**
    *   Выполни все требования 'Стандартной оптимизации'.
    *   Художественно обогати описание **заявленных игроком действий**.

**ФИНАЛЬНОЕ ПРАВИЛО:**
Верни ТОЛЬКО готовый текст поста или сообщение об ошибке. Никаких предисловий.
"""

def get_lore_prompt():
    """Возвращает системный промпт для ответов на вопросы по лору."""
    return f"""
Ты — Хранитель знаний мира 'Вальдес'. Твоя задача — отвечать на вопросы игроков, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном тебе тексте с лором и правилами.

**ТВОИ ПРАВИЛА:**
1.  **ИСТОЧНИК — ЗАКОН:** Используй только текст, приведенный ниже. Не добавляй никакой информации извне.
2.  **НЕ ДОДУМЫВАЙ:** Если в тексте нет прямого ответа на вопрос, честно скажи: "В предоставленных архивах нет точной информации по этому вопросу." В этом случае не добавляй источники.
3.  **СТИЛЬ:** Отвечай уважительно, в стиле мудрого летописца.
4.  **ЦИТИРОВАНИЕ ИСТОЧНИКОВ (ОБЯЗАТЕЛЬНО):** После твоего основного ответа, ты **ДОЛЖЕН** добавить специальный разделитель `%%SOURCES%%`. После этого разделителя перечисли через запятую названия каналов, из которых была взята информация. Названия каналов находятся в строках формата `--- НАЧАЛО КАНАЛА: [Имя канала] ---`.
    *   Пример формата: `Ответ на вопрос.%%SOURCES%%║🌟│астромантия, ║🧬│виды-разумных-сущностей`
    *   Если информация взята из одного канала, укажи только его.
    *   Не добавляй ничего после названий каналов.

Вот текст, который является твоей единственной базой знаний:
--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---
"""

# --- 4. ВСПОМОГАТЕЛЬНЫЙ КОД ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive and running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    Thread(target=run, daemon=True).start()

class OptimizedPostModal(ui.Modal, title='Ваш улучшенный пост'):
    def __init__(self, optimized_text: str):
        super().__init__()
        self.post_content = ui.TextInput(label="Текст готов к копированию", style=discord.TextStyle.paragraph, default=optimized_text, max_length=1800)
        self.add_item(self.post_content)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Окно закрыто.", ephemeral=True, delete_after=3)

class PostView(ui.View):
    def __init__(self, optimized_text: str):
        super().__init__(timeout=300)
        self.optimized_text = optimized_text
    @ui.button(label="📝 Показать и скопировать текст", style=discord.ButtonStyle.primary)
    async def show_modal_button(self, interaction: discord.Interaction, button: ui.Button):
        modal = OptimizedPostModal(self.optimized_text)
        await interaction.response.send_modal(modal)

DAILY_ACCESS_CODE = ""
CODE_FILE = "code.json"

def save_daily_code(code):
    data = {'code': code, 'date': datetime.now().strftime('%Y-%m-%d')}
    with open(CODE_FILE, 'w') as f:
        json.dump(data, f)

def load_daily_code():
    global DAILY_ACCESS_CODE
    try:
        with open(CODE_FILE, 'r') as f:
            data = json.load(f)
            if data['date'] == datetime.now().strftime('%Y-%m-%d'):
                DAILY_ACCESS_CODE = data['code']
                print(f"Загружен сегодняшний код доступа: {DAILY_ACCESS_CODE}")
                return
    except (FileNotFoundError, json.JSONDecodeError):
        print("Файл с кодом не найден или поврежден. Генерирую новый.")
    
    new_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    DAILY_ACCESS_CODE = new_code
    save_daily_code(new_code)
    print(f"Сгенерирован новый код на сегодня: {DAILY_ACCESS_CODE}")

# --- 5. НАСТРОЙКА БОТА ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- 6. ЗАДАЧИ И СОБЫТИЯ ---
async def send_access_code_to_admin_channel(code: str, title: str, description: str):
    """Отправляет эмбед с кодом доступа на админский сервер."""
    try:
        admin_channel = bot.get_channel(int(CODE_CHANNEL_ID))
        if admin_channel:
            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Код", value=f"```{code}```")
            embed.set_footer(text="Этот код действителен до конца текущих суток (по UTC).")
            await admin_channel.send(embed=embed)
        else:
            print(f"Ошибка: Не удалось найти канал с ID {CODE_CHANNEL_ID} для отправки кода.")
    except Exception as e:
        print(f"Произошла ошибка при отправке кода: {e}")

@tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
async def update_code_task():
    global DAILY_ACCESS_CODE
    
    new_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    DAILY_ACCESS_CODE = new_code
    save_daily_code(new_code)
    print(f"Сгенерирован новый ежедневный код: {new_code}")
    
    await send_access_code_to_admin_channel(
        code=new_code,
        title="🔑 Новый ежедневный код доступа",
        description=f"Код доступа для команды `/update_lore` на следующие 24 часа:"
    )

@update_code_task.before_loop
async def before_update_code_task():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    print(f'Бот {bot.user} успешно запущен!')
    load_lore_from_file()
    load_daily_code()
    
    if not update_code_task.is_running():
        update_code_task.start()
        
    await send_access_code_to_admin_channel(
        code=DAILY_ACCESS_CODE,
        title="⚙️ Текущий код доступа (После перезапуска)",
        description="Бот был перезапущен. Вот актуальный код на сегодня:"
    )
    
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

# --- 7. КОМАНДЫ БОТА ---

def robust_markdown_to_html(text: str) -> str:
    """Более надежно преобразует Markdown в HTML для FPDF, обрабатывая вложенность."""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'__(.+?)__', r'<u>\1</u>', text)
    return text.replace('\n', '<br/>')

@bot.tree.command(name="update_lore", description="[АДМИН] Собирает лор из каналов в единый PDF-файл.")
@app_commands.describe(access_code="Ежедневный код доступа для подтверждения")
async def update_lore(interaction: discord.Interaction, access_code: str):
    is_owner = str(interaction.user.id) == OWNER_USER_ID
    is_admin = interaction.user.guild_permissions.administrator

    if not (is_owner or is_admin):
        await interaction.response.send_message("❌ **Ошибка доступа:** Эту команду могут использовать только администраторы сервера.", ephemeral=True)
        return
        
    if str(interaction.guild.id) != MAIN_GUILD_ID:
        await interaction.response.send_message("❌ **Ошибка доступа:** Эта команда запрещена на данном сервере.", ephemeral=True)
        return

    if access_code != DAILY_ACCESS_CODE:
        await interaction.response.send_message("❌ **Неверный код доступа.** Получите актуальный код на администраторском сервере.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    try:
        channel_ids = [int(id.strip()) for id in LORE_CHANNEL_IDS.split(',')]
    except ValueError:
        await interaction.followup.send("❌ **Ошибка конфигурации:** Список ID каналов в .env содержит нечисловые значения.", ephemeral=True)
        return
        
    if not channel_ids:
        await interaction.followup.send("❌ **Ошибка конфигурации:** Список ID каналов в .env пуст.", ephemeral=True)
        return

    pdf = FPDF()
    sanitizer = None
    try:
        font_path = 'GalindoCyrillic-Regular.ttf'
        sanitizer = CharacterSanitizer(font_path)
        if not sanitizer.supported_chars:
             await interaction.followup.send(f"❌ **Критическая ошибка:** Не удалось загрузить карту символов для шрифта `{font_path}`. Проверьте, что файл не поврежден.", ephemeral=True)
             return

        pdf.add_font('Galindo', '', font_path)
        pdf.add_font('Galindo', 'B', font_path)
        pdf.add_font('Galindo', 'I', font_path)
        pdf.add_font('Galindo', 'BI', font_path)
        
    except Exception as e:
        await interaction.followup.send(f"❌ **Критическая ошибка со шрифтом:** {e}", ephemeral=True)
        return
    
    pdf.set_font('Galindo', '', 12)
    
    full_lore_text_for_memory = ""
    parsed_channels_count = 0
    total_messages_count = 0
    total_images_count = 0
    
    channels_to_parse = []
    for channel_id in channel_ids:
        channel = bot.get_channel(channel_id)
        if channel and (isinstance(channel, discord.TextChannel) or isinstance(channel, discord.ForumChannel)):
            channels_to_parse.append(channel)
        else:
            print(f"Предупреждение: Канал с ID {channel_id} не найден или его тип не поддерживается.")

    sorted_channels = sorted(channels_to_parse, key=lambda c: c.position)

    async with aiohttp.ClientSession() as session:
        async def process_image_from_bytes(image_bytes: bytes, filename: str):
            nonlocal full_lore_text_for_memory, total_images_count
            try:
                img = Image.open(io.BytesIO(image_bytes))
                ocr_text = pytesseract.image_to_string(img, lang='rus+eng')
                if ocr_text.strip():
                    full_lore_text_for_memory += f"--- Начало текста из изображения: {filename} ---\n{ocr_text.strip()}\n--- Конец текста ---\n\n"
                page_width = pdf.w - pdf.l_margin - pdf.r_margin
                ratio = img.height / img.width
                img_width = page_width
                img_height = page_width * ratio
                pdf.image(io.BytesIO(image_bytes), w=img_width, h=img_height)
                pdf.ln(5)
                total_images_count += 1
            except Exception as e:
                print(f"Не удалось обработать изображение {filename}: {e}")

        for channel in sorted_channels:
            pdf.add_page()
            pdf.set_font('Galindo', 'B', 16)
            pdf.cell(0, 10, sanitizer.sanitize(f'Канал: {channel.name}'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C')
            pdf.ln(10)
            
            full_lore_text_for_memory += f"\n--- НАЧАЛО КАНАЛА: {channel.name} ---\n\n"
            
            async def process_message(message):
                nonlocal total_messages_count
                nonlocal full_lore_text_for_memory # <<< ИСПРАВЛЕНИЕ ЗДЕСЬ
                content_found = False
                
                if message.content:
                    full_lore_text_for_memory += message.content + "\n\n"
                    pdf.set_font('Galindo', '', 12)
                    html_content = robust_markdown_to_html(sanitizer.sanitize(message.content))
                    pdf.write_html(html_content)
                    pdf.ln(5)
                    content_found = True
                
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title:
                            full_lore_text_for_memory += f"**{embed.title}**\n"
                            pdf.set_font('Galindo', 'B', 14)
                            html_title = f"<b>{robust_markdown_to_html(sanitizer.sanitize(embed.title))}</b>"
                            pdf.write_html(html_title)
                            pdf.ln(2)
                        if embed.description:
                            full_lore_text_for_memory += embed.description + "\n"
                            pdf.set_font('Galindo', '', 12)
                            html_desc = robust_markdown_to_html(sanitizer.sanitize(embed.description))
                            pdf.write_html(html_desc)
                            pdf.ln(4)
                        for field in embed.fields:
                            full_lore_text_for_memory += f"**{field.name}**\n{field.value}\n"
                            pdf.set_font('Galindo', 'B', 12)
                            html_field_name = f"<b>{robust_markdown_to_html(sanitizer.sanitize(field.name))}</b>"
                            pdf.write_html(html_field_name)
                            pdf.ln(1)
                            pdf.set_font('Galindo', '', 12)
                            html_field_value = robust_markdown_to_html(sanitizer.sanitize(field.value))
                            pdf.write_html(html_field_value)
                            pdf.ln(4)
                        
                        if embed.image.url:
                            try:
                                async with session.get(embed.image.url) as resp:
                                    if resp.status == 200:
                                        image_bytes = await resp.read()
                                        await process_image_from_bytes(image_bytes, f"embed_image_{embed.image.url.split('/')[-1]}")
                            except Exception as e:
                                print(f"Не удалось скачать изображение из эмбеда: {embed.image.url}, ошибка: {e}")
                        
                        if embed.thumbnail.url:
                            try:
                                async with session.get(embed.thumbnail.url) as resp:
                                    if resp.status == 200:
                                        image_bytes = await resp.read()
                                        await process_image_from_bytes(image_bytes, f"embed_thumbnail_{embed.thumbnail.url.split('/')[-1]}")
                            except Exception as e:
                                print(f"Не удалось скачать thumbnail из эмбеда: {embed.thumbnail.url}, ошибка: {e}")
                        
                        full_lore_text_for_memory += "\n"
                    content_found = True
                
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type and attachment.content_type.startswith('image/'):
                            image_bytes = await attachment.read()
                            await process_image_from_bytes(image_bytes, attachment.filename)
                
                if content_found or message.attachments or message.embeds:
                    total_messages_count += 1
                    pdf.ln(5)

            if isinstance(channel, discord.ForumChannel):
                all_threads = channel.threads + [t async for t in channel.archived_threads(limit=None)]
                sorted_threads = sorted(all_threads, key=lambda t: t.created_at)
                for thread in sorted_threads:
                    pdf.set_font('Galindo', 'I', 14)
                    pdf.cell(0, 10, sanitizer.sanitize(f"--- Публикация: {thread.name} ---"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
                    pdf.ln(5)
                    full_lore_text_for_memory += f"--- Начало публикации: {thread.name} ---\n\n"
                    async for message in thread.history(limit=500, oldest_first=True):
                        await process_message(message)
                    full_lore_text_for_memory += f"--- Конец публикации: {thread.name} ---\n\n"
            else:
                async for message in channel.history(limit=500, oldest_first=True):
                    await process_message(message)

            full_lore_text_for_memory += f"--- КОНЕЦ КАНАЛА: {channel.name} ---\n"
            parsed_channels_count += 1

    try:
        pdf_output_filename = "lore.pdf"
        pdf.output(pdf_output_filename)
        
        with open("file.txt", "w", encoding="utf-8") as f:
            f.write(full_lore_text_for_memory)
        
        load_lore_from_file()
        
        pdf_size_mb = os.path.getsize(pdf_output_filename) / (1024 * 1024)
        
        embed = discord.Embed(title="✅ Лор успешно собран в PDF!", description=f"Файл `{pdf_output_filename}` был создан и прикреплен к этому сообщению.", color=discord.Color.green())
        embed.add_field(name="Обработано каналов", value=str(parsed_channels_count), inline=True)
        embed.add_field(name="Собрано сообщений", value=str(total_messages_count), inline=True)
        embed.add_field(name="Вставлено изображений", value=str(total_images_count), inline=True)
        embed.add_field(name="Размер PDF", value=f"{pdf_size_mb:.2f} МБ", inline=True)
        
        if pdf_size_mb > 24:
            await interaction.followup.send(
                content="⚠️ **Внимание:** Размер PDF-файла превышает 25 МБ. Я не могу отправить его в Discord. Файл сохранен на сервере.",
                embed=embed,
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=embed,
                file=discord.File(pdf_output_filename),
                ephemeral=True
            )

        await interaction.followup.send("✅ **Лор обновлен.** Перезапускаюсь для применения изменений через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)
        
        print("Закрываю соединение для корректного перезапуска...")
        await bot.close()
        
    except Exception as e:
        await interaction.followup.send(f"Произошла критическая ошибка при записи или отправке файла: {e}", ephemeral=True)


@bot.tree.command(name="optimize_post", description="Улучшает РП-пост, принимая текст и уровень улучшения.")
@app_commands.describe(
    post_text="Текст вашего поста для улучшения.",
    optimization_level="Выберите желаемый уровень улучшения.",
    image="(Опционально) Изображение для дополнительного контекста."
)
@app_commands.choices(optimization_level=[
    discord.app_commands.Choice(name="Минимальные правки", value="minimal"),
    discord.app_commands.Choice(name="Стандартная оптимизация", value="standard"),
    discord.app_commands.Choice(name="Максимальная креативность", value="creative"),
])
async def optimize_post(interaction: discord.Interaction, post_text: str, optimization_level: discord.app_commands.Choice[str], image: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if image and (not image.content_type or not image.content_type.startswith("image/")):
        await interaction.followup.send("❌ **Ошибка:** Прикрепленный файл не является изображением.", ephemeral=True)
        return

    level_map = {"minimal": "Минимальные правки", "standard": "Стандартная оптимизация", "creative": "Максимальная креативность"}
    prompt = get_optimizer_prompt(level_map[optimization_level.value])
    
    content_to_send = [prompt, f"\n\nПост игрока:\n---\n{post_text}"]
    
    if image:
        try:
            image_bytes = await image.read()
            pil_image = Image.open(io.BytesIO(image_bytes))
            content_to_send.append(pil_image)
        except Exception as e:
            print(f"Ошибка обработки изображения: {e}")
            await interaction.followup.send("⚠️ Не удалось обработать прикрепленное изображение, но я попробую улучшить текст без него.", ephemeral=True)

    try:
        response = await gemini_model.generate_content_async(content_to_send)
        result_text = response.text.strip()

        if result_text.startswith("ОШИБКА:"):
            error_embed = discord.Embed(title="❌ Обнаружена грубая лорная ошибка!", description=result_text.replace("ОШИБКА:", "").strip(), color=discord.Color.red())
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        else:
            embed = discord.Embed(title="✨ Ваш пост был оптимизирован!", color=discord.Color.gold())
            embed.add_field(name="▶️ Оригинал:", value=f"```\n{post_text[:1000]}\n```", inline=False)
            embed.add_field(name="✅ Улучшенная версия (превью):", value=f"{result_text[:1000]}...", inline=False)
            embed.set_footer(text="Нажмите кнопку ниже, чтобы получить полный текст.")
            view = PostView(result_text)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        print(f"Произошла внутренняя ошибка в /optimize_post: {e}")
        error_embed = discord.Embed(title="🚫 Произошла внутренняя ошибка", description="Не удалось обработать ваш запрос. Пожалуйста, попробуйте еще раз.", color=discord.Color.dark_red())
        await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.")
async def ask_lore(interaction: discord.Interaction, question: str):
    await interaction.response.defer(ephemeral=False)
    try:
        prompt = get_lore_prompt()
        response = await gemini_model.generate_content_async([prompt, f"\n\nВопрос игрока: {question}"])
        raw_text = response.text.strip()

        answer_text = raw_text
        sources_text = ""
        if "%%SOURCES%%" in raw_text:
            parts = raw_text.split("%%SOURCES%%")
            answer_text = parts[0].strip()
            sources_text = parts[1].strip()

        embed = discord.Embed(title="📜 Ответ из архивов Вальдеса", description=answer_text, color=discord.Color.blue())
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        
        if sources_text:
            embed.add_field(name="Источники:", value=sources_text, inline=False)
            
        embed.set_footer(text=f"Ответил Хранитель знаний | Запросил: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Произошла ошибка при обработке запроса /ask_lore: {e}")
        error_embed = discord.Embed(title="🚫 Ошибка в архиве", description="Хранитель знаний не смог найти ответ на ваш вопрос из-за непредвиденной ошибки.", color=discord.Color.dark_red())
        await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.tree.command(name="help", description="Показывает информацию обо всех доступных командах.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📜 Справка по командам",
        description="Вот список всех доступных команд и их описание:",
        color=discord.Color.blue()
    )
    embed.add_field(name="/optimize_post", value="Улучшает ваш РП-пост. Принимает текст, уровень улучшения и опционально изображение.", inline=False)
    embed.add_field(name="/ask_lore", value="Задает вопрос Хранителю знаний по миру 'Вальдеса'. Ответ будет виден всем в канале.", inline=False)
    embed.add_field(name="/about", value="Показывает информацию о боте и его создателе.", inline=False)
    embed.add_field(name="/help", value="Показывает это справочное сообщение.", inline=False)
    embed.add_field(name="/update_lore", value="**[Только для администраторов]**\nСобирает лор из всех каналов, обновляет файл и перезапускает бота.", inline=False)
    
    embed.set_footer(text="Ваш верный помощник в мире Вальдеса.")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="about", description="Показывает информацию о боте и его создателе.")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(
        title="О боте 'Хранитель Вальдеса'",
        description="Я — ассистент, созданный для помощи игрокам и администрации текстового ролевого проекта 'Вальдес'.\n\nМоя главная задача — делать ваше погружение в мир более гладким и интересным, отвечая на вопросы по лору и помогая с качеством ваших постов.",
        color=discord.Color.gold()
    )
    embed.add_field(name="Разработчик", value="**GX**", inline=True)
    embed.add_field(name="Технологии", value="• Discord.py\n• Google Gemini API", inline=True)
    embed.set_footer(text=f"Бот запущен на сервере: {interaction.guild.name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=False)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)

