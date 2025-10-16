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
import re
import shutil
import aiohttp
from typing import List
import urllib.parse


# Загрузка переменных окружения из файла .env
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAIN_GUILD_ID = os.getenv("MAIN_GUILD_ID")
ADMIN_GUILD_ID = os.getenv("ADMIN_GUILD_ID")
CODE_CHANNEL_ID = os.getenv("CODE_CHANNEL_ID")
OWNER_USER_ID = os.getenv("OWNER_USER_ID")
LORE_CHANNEL_IDS = os.getenv("LORE_CHANNEL_IDS")
GOSSIP_CHANNEL_ID = os.getenv("GOSSIP_CHANNEL_ID")

# Флаг для определения тестового режима
IS_TEST_BOT = os.getenv("IS_TEST_BOT", "False").lower() == "true"


# Проверяем, что все ID и ключи на месте
if not all([DISCORD_TOKEN, GEMINI_API_KEY, MAIN_GUILD_ID, ADMIN_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID, LORE_CHANNEL_IDS, GOSSIP_CHANNEL_ID]):
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Один из ключей или ID (DISCORD_TOKEN, GEMINI_API_KEY, *_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID, LORE_CHANNEL_IDS, GOSSIP_CHANNEL_ID) не найден в .env")

# Настройка API Gemini
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-2.5-flash')


# --- 2. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И ФУНКЦИИ ---
VALDES_LORE = ""
VALDES_GOSSIP = ""
LORE_IMAGES_DIR = "lore_images"
IMAGE_MAP_FILE = "image_map.json"
CHARACTER_DATA_FILE = "characters.json"
CHARACTERS_DATA = {}

def load_lore_from_file():
    """Загружает/перезагружает основной лор из файла в память бота."""
    global VALDES_LORE
    try:
        with open("file.txt", "r", encoding="utf-8") as f:
            VALDES_LORE = f.read()
        print("Основной лор успешно загружен/обновлен в память.")
    except FileNotFoundError:
        print("КРИТИЧЕСКАЯ ОШИБКА: Файл 'file.txt' не найден.")
        VALDES_LORE = "Основной лор не был загружен из-за отсутствия файла."

def load_gossip_from_file():
    """Загружает/перезагружает сплетни и события из файла в память бота."""
    global VALDES_GOSSIP
    try:
        with open("gossip.txt", "r", encoding="utf-8") as f:
            VALDES_GOSSIP = f.read()
        print("Лор сплетен и событий успешно загружен/обновлен в память.")
    except FileNotFoundError:
        print("ПРЕДУПРЕЖДЕНИЕ: Файл 'gossip.txt' не найден. Сводка событий будет пустой.")
        VALDES_GOSSIP = "В данный момент актуальных событий и сплетен не зафиксировано."

def load_characters():
    """Загружает данные персонажей из JSON-файла."""
    global CHARACTERS_DATA
    try:
        with open(CHARACTER_DATA_FILE, 'r', encoding='utf-8') as f:
            CHARACTERS_DATA = json.load(f)
        print("Данные персонажей успешно загружены.")
    except (FileNotFoundError, json.JSONDecodeError):
        CHARACTERS_DATA = {}
        print("Файл персонажей не найден или пуст. Будет создан новый.")

def save_characters():
    """Сохраняет данные персонажей в JSON-файл."""
    with open(CHARACTER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(CHARACTERS_DATA, f, indent=4)

# --- 3. СИСТЕМНЫЕ ПРОМПТЫ ---
def get_optimizer_prompt(level, character_info=None):
    character_context_prompt = ""
    if character_info:
        character_context_prompt = f"""
**КОНТЕКСТ О ПЕРСОНАЖЕ (ИСПОЛЬЗУЙ ЭТО ОБЯЗАТЕЛЬНО):**
- **Имя:** {character_info['name']}
- **Описание и характер:** {character_info['description']}
Основывайся на этой информации, чтобы сохранить стиль персонажа, его манеру речи и мышления.
"""

    return f"""
Ты — ассистент для текстового ролевого проекта 'Вальдес'. Твоя задача — идеально отформатировать и, при необходимости, улучшить пост игрока.
{character_context_prompt}
**КЛЮЧЕВЫЕ ПРАВИЛА ОФОРМЛЕНИЯ ПОСТА (САМОЕ ВАЖНОЕ):**
1.  **ДЕЙСТВИЯ:** Все действия персонажа должны быть заключены в одинарные звездочки. Пример: `*Он поднялся с кровати.*`
2.  **МЫСЛИ И ЗВУКИ:** Все мысли персонажа, а также напевание, мычание и т.д., должны быть заключены в двойные звездочки. Пример: `**Какой сегодня прекрасный день.**` или `**Ммм-хмм...**`
3.  **РЕЧЬ:** Вся прямая речь персонажа должна начинаться с дефиса и пробела. Пример: `- Доброе утро.`
4.  Каждый тип (действие, мысль, речь) **ОБЯЗАН** начинаться с новой строки для читаемости.

**ЗОЛОТЫЕ ПРАВИЛА ОБРАБОТКИ:**
1.  **ПОВЕСТВОВАНИЕ ОТ ТРЕТЬЕГО ЛИЦА:** Все действия персонажа должны быть написаны от **третьего лица** (Он/Она), даже если игрок написал от первого ('Я делаю').
2.  **ЗАПРЕТ НА СИМВОЛЫ:** ЗАПРЕЩЕНО использовать любые другие символы для оформления, кроме `* *`, `** **` и `- `. Никаких `()`, `<<>>` и прочего.
3.  **НЕ БЫТЬ СОАВТОРОМ:** Не добавляй новых действий или мотивации, которых не было в исходном тексте. Ты редактор, а не соавтор.
"""

def get_serious_lore_prompt():
    """Возвращает СЕРЬЕЗНЫЙ системный промпт для ответов на вопросы по лору."""
    return f"""
Ты — Хранитель знаний мира 'Вальдес'. Твоя задача — отвечать на вопросы игроков, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном тебе тексте.

**ТВОИ ПРАВИЛА:**
1.  **ИСТОЧНИК — ЗАКОН:** Используй только предоставленный текст.
2.  **НЕ ДОДУМЫВАЙ:** Если в тексте нет прямого ответа, честно скажи: "В предоставленных архивах нет точной информации по этому вопросу."
3.  **ЦИТИРОВАНИЕ ИСТОЧНИКОВ:** После основного ответа, ДОБАВЬ разделитель `%%SOURCES%%`. После него перечисли **упоминания каналов (channel mentions)**, из которых была взята информация.
4.  **ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ДЛЯ СОБЫТИЙ (ВАЖНО!):**
    - Если твой ответ содержит информацию из канала, посвященного событиям и сплетням, ты **ОБЯЗАН** создать промпт для генерации изображения.
    - После разделителя `%%SOURCES%%` добавь еще один разделитель: `%%IMAGE_PROMPTS%%`.
    - После `%%IMAGE_PROMPTS%%` напиши с новой строки краткий, но яркий промпт на английском языке, описывающий сцену события. **Только сцену!** Не добавляй в промпт слова "scroll", "ink", "drawing".
    - Если событий в ответе несколько, создай несколько промптов, каждый с новой строки.

**ПРИМЕР ПОЛНОГО ОТВЕТА (ШАБЛОН):**
Согласно последним донесениям, в области Юравания готовится новый гладиаторский сезон. Также правительство Сариона набирает группы для расследования загадочных смертей среди эльфов, расследование начнется 20 октября.
%%SOURCES%%
<#123456789012345678>
%%IMAGE_PROMPTS%%
A group of elves investigating a mysterious magical phenomenon in a dark swamp.
Gladiators preparing for a fight in a grand arena under a scorching sun.

Вот твоя база знаний:
--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---
--- НАЧАЛО СВОДКИ АКТУАЛЬНЫХ СОБЫТИЙ И СПЛЕТЕН ---
{VALDES_GOSSIP}
--- КОНЕЦ СВОДКИ АКТУАЛЬНЫХ СОБЫТИЙ И СПЛЕТЕН ---
"""

def get_edgy_lore_prompt():
    """Возвращает ЦИНИЧНЫЙ, но ЛОРНЫЙ системный промпт для ответов на вопросы."""
    return f"""
Ты — Архивариус Вальдеса. Ты циничный, уставший от жизни старик. Твои знания ОГРАНИЧЕНЫ предоставленным текстом.

**ТВОИ НОВЫЕ ПРАВИЛА, ЗАСРАНЕЦ:**
1.  **ОСНОВА — ЛОР, НО НЕ КОПИПАСТА:** Отвечай по сути, своими словами.
2.  **ДОДУМЫВАЙ, НО ВНУТРИ ЛОРА:** Можешь делать циничные предположения, основанные на фактах из лора.
3.  **ЦИТИРОВАНИЕ ИСТОЧНИКОВ:** После ответа поставь `%%SOURCES%%` и перечисли **упоминания каналов (channel mentions)**.
4.  **РИСУНКИ СПЛЕТЕН (СЛУШАЙ СЮДА):**
    - Твой магический артефакт иногда показывает образы. Если отвечаешь на что-то из новостей, ты **ДОЛЖЕН** описать этот образ.
    - После разделителя `%%SOURCES%%` добавь `%%IMAGE_PROMPTS%%`.
    - После него, с новой строки, коротко на английском опиши сцену. Без слов "свиток", "чернила" и т.д.
    - Если новостей несколько, опиши каждую картинку с новой строки.

**ПРИМЕР ТВОЕГО ОТВЕТА, СТАРИК (ШАБЛОН):**
Опять эти идиоты в Юравании мечами махать собрались, гладиаторский сезон у них. А в Сарионе, как обычно, эльфы дохнут от какой-то херни, теперь вот народ сгоняют, чтобы разобрались. Весело живут, нечего сказать.
%%SOURCES%%
<#123456789012345678>
%%IMAGE_PROMPTS%%
A group of elves investigating a mysterious magical phenomenon in a dark swamp.
Gladiators preparing for a fight in a grand arena under a scorching sun.

Вот твоя база знаний. Не подведи.
--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---
--- АКТУАЛЬНЫЕ НОВОСТИ С ТВОЕГО АРТЕФАКТА ---
{VALDES_GOSSIP}
--- КОНЕЦ НОВОСТЕЙ С АРТЕФАКТА ---
"""


# --- 4. ВСПОМОГАТЕЛЬНЫЙ КОД (keep_alive, UI, работа с кодом доступа) ---
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
        pass
    
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

# --- 6. УНИВЕРСАЛЬНАЯ ФУНКЦИЯ И ЕЖЕДНЕВНЫЕ ЗАДАЧИ ---
async def send_access_code_to_admin_channel(code: str, title: str, description: str):
    try:
        admin_channel = bot.get_channel(int(CODE_CHANNEL_ID))
        if admin_channel:
            embed = discord.Embed(title=title, description=description, color=discord.Color.gold(), timestamp=datetime.now())
            embed.add_field(name="Код", value=f"```{code}```")
            embed.set_footer(text="Этот код действителен до конца текущих суток (по UTC).")
            await admin_channel.send(embed=embed)
    except Exception as e:
        print(f"Произошла ошибка при отправке кода: {e}")

@tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
async def update_code_task():
    global DAILY_ACCESS_CODE
    new_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    DAILY_ACCESS_CODE = new_code
    save_daily_code(new_code)
    print(f"Сгенерирован новый ежедневный код: {new_code}")
    await send_access_code_to_admin_channel(code=new_code, title="🔑 Новый ежедневный код доступа", description="Код доступа для команды `/update_lore` на следующие 24 часа:")

@tasks.loop(time=time(hour=0, minute=5, tzinfo=timezone.utc))
async def update_gossip_task():
    print("Запускаю ежедневное обновление лора сплетен и событий...")
    try:
        gossip_channel_id = int(GOSSIP_CHANNEL_ID)
        gossip_channel = bot.get_channel(gossip_channel_id)
        if not gossip_channel:
            print(f"КРИТИЧЕСКАЯ ОШИБКА: Канал сплетен с ID {gossip_channel_id} не найден.")
            return

        async with aiohttp.ClientSession() as session:
            gossip_text, _, _, _ = await parse_channel_content([gossip_channel], session, download_images=False)

        with open("gossip.txt", "w", encoding="utf-8") as f:
            f.write(gossip_text)
        
        load_gossip_from_file() 
        print("Ежедневное обновление лора сплетен успешно завершено.")

    except Exception as e:
        print(f"Произошла ошибка во время ежедневного обновления сплетен: {e}")


@update_code_task.before_loop
async def before_tasks():
    await bot.wait_until_ready()

@update_gossip_task.before_loop
async def before_gossip_task():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    if IS_TEST_BOT:
        print("--- БОТ ЗАПУЩЕН В ТЕСТОВОМ РЕЖИМЕ ---")
    else:
        print("--- БОТ ЗАПУЩЕН В ПРОИЗВОДСТВЕННОМ РЕЖИМЕ ---")

    print(f'Бот {bot.user} успешно запущен!')
    load_lore_from_file()
    load_gossip_from_file()
    load_characters()

    if not IS_TEST_BOT:
        load_daily_code()
        if not update_code_task.is_running():
            update_code_task.start()
        if not update_gossip_task.is_running():
            update_gossip_task.start()
        await send_access_code_to_admin_channel(code=DAILY_ACCESS_CODE, title="⚙️ Текущий код доступа (После перезапуска)", description="Бот был перезапущен. Вот актуальный код на сегодня:")
    
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

# --- 7. КОМАНДЫ БОТА ---

def clean_discord_mentions(text: str, guild: discord.Guild) -> str:
    """Заменяет упоминания каналов, ролей и пользователей на их имена."""
    if not text:
        return ""
    text = re.sub(r'<#(\d+)>', lambda m: f'#{bot.get_channel(int(m.group(1))).name}' if bot.get_channel(int(m.group(1))) else m.group(0), text)
    if guild:
        text = re.sub(r'<@&(\d+)>', lambda m: f'@{guild.get_role(int(m.group(1))).name}' if guild.get_role(int(m.group(1))) else m.group(0), text)
    text = re.sub(r'<@!?(\d+)>', lambda m: f'@{bot.get_user(int(m.group(1))).display_name}' if bot.get_user(int(m.group(1))) else m.group(0), text)
    return text

async def parse_channel_content(channels_to_parse: list, session: aiohttp.ClientSession, download_images: bool = True):
    """
    Универсальная функция для сбора и обработки контента из списка каналов.
    """
    full_text = ""
    total_messages_count = 0
    image_id_counter = 1
    image_map = {}
    downloaded_images_count = 0
    
    sorted_channels = sorted(channels_to_parse, key=lambda c: c.position)

    async def download_and_register_image(url):
        nonlocal image_id_counter, image_map, downloaded_images_count
        if not download_images: return ""
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    image_bytes = await resp.read()
                    image_id = f"IMAGE_{image_id_counter}"
                    content_type = resp.headers.get('Content-Type', '')
                    file_extension = 'png'
                    if 'jpeg' in content_type or 'jpg' in content_type: file_extension = 'jpg'
                    elif 'png' in content_type: file_extension = 'png'
                    elif 'gif' in content_type: file_extension = 'gif'
                    elif 'webp' in content_type: file_extension = 'webp'
                    
                    new_filename = f"{image_id}.{file_extension}"
                    save_path = os.path.join(LORE_IMAGES_DIR, new_filename)
                    with open(save_path, 'wb') as f: f.write(image_bytes)
                    image_map[image_id] = new_filename
                    image_id_counter += 1
                    downloaded_images_count += 1
                    return f"[{image_id}]"
                return ""
        except Exception as e:
            print(f"Критическая ошибка при скачивании {url}: {e}")
            return ""

    for channel in sorted_channels:
        guild = channel.guild
        full_text += f"\n--- НАЧАЛО КАНАЛА: {channel.mention} ---\n\n"
        
        async def parse_message(message):
            nonlocal full_text, total_messages_count
            content_parts = []
            if message.content:
                content_parts.append(clean_discord_mentions(message.content.strip(), guild))
            if message.embeds:
                for embed in message.embeds:
                    embed_text_parts = []
                    if embed.title: embed_text_parts.append(f"**{clean_discord_mentions(embed.title, guild)}**")
                    if embed.description: embed_text_parts.append(clean_discord_mentions(embed.description, guild))
                    if embed_text_parts: content_parts.append("\n".join(embed_text_parts))
                    if embed.image and embed.image.url:
                        image_tag = await download_and_register_image(embed.image.url)
                        if image_tag: content_parts.append(image_tag)
                    for field in embed.fields:
                        field_name = clean_discord_mentions(field.name, guild)
                        field_value = clean_discord_mentions(field.value, guild)
                        content_parts.append(f"**{field_name}**\n{field_value}")
            if message.attachments:
                image_attachments = [att for att in message.attachments if att.content_type and att.content_type.startswith('image/')]
                for attachment in image_attachments:
                    image_tag = await download_and_register_image(attachment.url)
                    if image_tag: content_parts.append(image_tag)
            
            if content_parts:
                final_text_for_message = "\n\n".join(filter(None, content_parts))
                full_text += final_text_for_message + "\n\n"
                total_messages_count += 1

        if isinstance(channel, discord.ForumChannel):
            all_threads = channel.threads
            try:
                archived_threads = [thread async for thread in channel.archived_threads(limit=None)]
                all_threads.extend(archived_threads)
            except discord.Forbidden:
                print(f"Нет прав для доступа к архивным веткам в канале: {channel.name}")
            
            sorted_threads = sorted(all_threads, key=lambda t: t.created_at)
            for thread in sorted_threads:
                full_text += f"--- Начало публикации: {thread.name} ---\n\n"
                async for message in thread.history(limit=500, oldest_first=True):
                    await parse_message(message)
                full_text += f"--- Конец публикации: {thread.name} ---\n\n"
        else:
            async for message in channel.history(limit=500, oldest_first=True):
                await parse_message(message)

        full_text += f"--- КОНЕЦ КАНАЛА: {channel.mention} ---\n"
    
    return full_text, total_messages_count, downloaded_images_count, image_map


@bot.tree.command(name="update_lore", description="[АДМИН] Собирает лор из заданных каналов и обновляет файл.")
@app_commands.describe(access_code="Ежедневный код доступа для подтверждения")
async def update_lore(interaction: discord.Interaction, access_code: str):
    if IS_TEST_BOT:
        await interaction.response.send_message("❌ **Ошибка:** Эта команда отключена в тестовом режиме.", ephemeral=True)
        return

    if str(interaction.user.id) != OWNER_USER_ID and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ **Ошибка доступа:** Эту команду могут использовать только администраторы сервера.", ephemeral=True)
        return
    if str(interaction.guild.id) != MAIN_GUILD_ID:
        await interaction.response.send_message("❌ **Ошибка доступа:** Эта команда запрещена на данном сервере.", ephemeral=True)
        return
    if access_code != DAILY_ACCESS_CODE:
        await interaction.response.send_message("❌ **Неверный код доступа.** Получите актуальный код на администраторском сервере.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if os.path.exists(LORE_IMAGES_DIR):
        shutil.rmtree(LORE_IMAGES_DIR)
    os.makedirs(LORE_IMAGES_DIR)

    try:
        lore_channel_ids = [int(id.strip()) for id in LORE_CHANNEL_IDS.split(',')]
        gossip_channel_id = int(GOSSIP_CHANNEL_ID)
    except ValueError:
        await interaction.followup.send("❌ **Ошибка конфигурации:** ID каналов в .env содержат нечисловые значения.", ephemeral=True)
        return

    lore_channels = [bot.get_channel(cid) for cid in lore_channel_ids if bot.get_channel(cid) is not None]
    gossip_channel = bot.get_channel(gossip_channel_id)
    
    if not gossip_channel:
        await interaction.followup.send(f"❌ **Ошибка:** Канал сплетен с ID `{gossip_channel_id}` не найден.", ephemeral=True)
        return

    async with aiohttp.ClientSession() as session:
        full_lore_text, total_lore_messages, downloaded_images_count, image_map = await parse_channel_content(lore_channels, session, download_images=True)
        gossip_text, total_gossip_messages, _, _ = await parse_channel_content([gossip_channel], session, download_images=False)
    
    try:
        with open("file.txt", "w", encoding="utf-8") as f: f.write(full_lore_text)
        with open(IMAGE_MAP_FILE, "w", encoding="utf-8") as f: json.dump(image_map, f, indent=4)
        with open("gossip.txt", "w", encoding="utf-8") as f: f.write(gossip_text)

        load_lore_from_file()
        load_gossip_from_file()

        file_size_lore = os.path.getsize("file.txt") / 1024
        file_size_gossip = os.path.getsize("gossip.txt") / 1024
        
        embed = discord.Embed(title="✅ Лор и события успешно обновлены!", description="Файлы `file.txt` и `gossip.txt` были перезаписаны.", color=discord.Color.green())
        embed.add_field(name="Обработано лор-каналов", value=str(len(lore_channels)), inline=True)
        embed.add_field(name="Собрано лор-сообщений", value=str(total_lore_messages), inline=True)
        embed.add_field(name="Скачано изображений", value=str(downloaded_images_count), inline=True)
        embed.add_field(name="Размер лор-файла", value=f"{file_size_lore:.2f} КБ", inline=True)
        embed.add_field(name="Канал сплетен", value="Обработан", inline=True)
        embed.add_field(name="Сообщений о событиях", value=str(total_gossip_messages), inline=True)
        embed.add_field(name="Размер файла событий", value=f"{file_size_gossip:.2f} КБ", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        await interaction.followup.send("✅ **Данные обновлены.** Перезапускаюсь для применения изменений через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)
        await bot.close()
    except Exception as e:
        await interaction.followup.send(f"Произошла критическая ошибка при записи или отправке файла: {e}", ephemeral=True)


@bot.tree.command(name="optimize_post", description="Улучшает РП-пост, принимая текст и уровень улучшения.")
@app_commands.describe(post_text="Текст вашего поста для улучшения.", optimization_level="Выберите желаемый уровень улучшения.", image="(Опционально) Изображение для дополнительного контекста.")
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

    user_id = str(interaction.user.id)
    active_character_info = None
    if user_id in CHARACTERS_DATA and CHARACTERS_DATA[user_id]['active_character']:
        active_char_name = CHARACTERS_DATA[user_id]['active_character']
        for char in CHARACTERS_DATA[user_id]['characters']:
            if char['name'] == active_char_name:
                active_character_info = char
                break

    level_map = {"minimal": "Минимальные правки", "standard": "Стандартная оптимизация", "creative": "Максимальная креативность"}
    prompt = get_optimizer_prompt(level_map[optimization_level.value], active_character_info)
    
    content_to_send = [prompt, f"\n\nПост игрока:\n---\n{post_text}"]
    
    if image:
        try:
            image_bytes = await image.read()
            pil_image = Image.open(io.BytesIO(image_bytes))
            content_to_send.append(pil_image)
        except Exception as e:
            await interaction.followup.send("⚠️ Не удалось обработать прикрепленное изображение.", ephemeral=True)

    try:
        response = await gemini_model.generate_content_async(content_to_send)
        result_text = response.text.strip()

        embed = discord.Embed(title="✨ Ваш пост был оптимизирован!", color=discord.Color.gold())
        if active_character_info:
            embed.set_author(name=f"Персонаж: {active_character_info['name']}", icon_url=active_character_info.get('avatar_url'))
        
        embed.add_field(name="▶️ Оригинал:", value=f"```\n{post_text[:1000]}\n```", inline=False)
        embed.add_field(name="✅ Улучшенная версия (превью):", value=f"{result_text[:1000]}...", inline=False)
        view = PostView(result_text)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    except Exception as e:
        print(f"Произошла внутренняя ошибка в /optimize_post: {e}")
        await interaction.followup.send(embed=discord.Embed(title="🚫 Произошла внутренняя ошибка", description="Не удалось обработать ваш запрос.", color=discord.Color.dark_red()), ephemeral=True)

async def generate_pollinations_image(session: aiohttp.ClientSession, description_prompt: str) -> bytes | None:
    """Генерирует изображение по описанию через API Pollinations.ai."""
    try:
        full_prompt = f"ancient scroll, old paper texture, ink drawing, colorless, sketch style, black and white, masterpiece, depicting {description_prompt}"
        encoded_prompt = urllib.parse.quote_plus(full_prompt)
        
        width = 1024
        height = 768
        seed = random.randint(1, 100000)
        model = 'flux'
        
        image_url = f"https://pollinations.ai/p/{encoded_prompt}?width={width}&height={height}&seed={seed}&model={model}"

        async with session.get(image_url, timeout=120) as resp:
            if resp.status == 200:
                print(f"Изображение для промпта '{description_prompt[:30]}...' успешно сгенерировано.")
                return await resp.read()
            else:
                print(f"Ошибка при запросе к Pollinations.ai: Статус {resp.status}")
                return None
    except Exception as e:
        print(f"Произошла критическая ошибка при генерации изображения: {e}")
        return None


@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(
    question="Ваш вопрос Хранителю знаний.",
    personality="(Опционально) Выберите характер ответа. По умолчанию 'Серьезный'."
)
@app_commands.choices(personality=[
    discord.app_commands.Choice(name="Серьезный Архивариус (По умолчанию)", value="serious"),
    discord.app_commands.Choice(name="Циничный Старик (18+)", value="edgy")
])
async def ask_lore(interaction: discord.Interaction, question: str, personality: discord.app_commands.Choice[str] = None):
    await interaction.response.defer(ephemeral=False)
    
    try:
        if personality and personality.value == 'edgy':
            prompt = get_edgy_lore_prompt()
            embed_color = discord.Color.red()
            author_name = "Ответил Циничный Старик"
        else:
            prompt = get_serious_lore_prompt()
            embed_color = discord.Color.blue()
            author_name = "Ответил Хранитель знаний"

        response = await gemini_model.generate_content_async([prompt, f"\n\nВопрос игрока: {question}"])
        raw_text = response.text.strip()
        
        files_to_send = []
        image_prompts_text = ""
        
        if "%%IMAGE_PROMPTS%%" in raw_text:
            parts = raw_text.split("%%IMAGE_PROMPTS%%")
            raw_text = parts[0]
            image_prompts_text = parts[1].strip()

        answer_text, sources_text = (raw_text.split("%%SOURCES%%") + [""])[:2]
        answer_text = answer_text.strip()
        sources_text = sources_text.strip()

        image_ids = re.findall(r'\[(IMAGE_\d+)\]', answer_text)
        if image_ids:
            answer_text = re.sub(r'\[IMAGE_\d+\]\s*', '', answer_text).strip()
            try:
                with open(IMAGE_MAP_FILE, 'r', encoding='utf-8') as f:
                    image_map = json.load(f)
                for i, image_id in enumerate(image_ids):
                    filename = image_map.get(image_id)
                    if filename and os.path.exists(os.path.join(LORE_IMAGES_DIR, filename)):
                        files_to_send.append(discord.File(os.path.join(LORE_IMAGES_DIR, filename)))
            except Exception as e:
                print(f"ОШИБКА: Не удалось загрузить {IMAGE_MAP_FILE}: {e}")
        
        embed = discord.Embed(title="📜 Ответ из архивов Вальдеса", description=answer_text, color=embed_color)
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        if sources_text:
            embed.add_field(name="Источники:", value=sources_text, inline=False)
        embed.set_footer(text=f"{author_name} | Запросил: {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)

        if files_to_send:
            image_embed = discord.Embed(title="Иллюстрации из архива", color=embed_color)
            await interaction.followup.send(embed=image_embed, files=files_to_send)
        
        if image_prompts_text:
            generated_files = []
            image_prompts = [p.strip() for p in image_prompts_text.split('\n') if p.strip()]
            
            async with aiohttp.ClientSession() as session:
                for i, img_prompt in enumerate(image_prompts):
                    if i > 0:
                        await asyncio.sleep(2)
                    
                    image_bytes = await generate_pollinations_image(session, img_prompt)
                    
                    if image_bytes:
                        file = discord.File(io.BytesIO(image_bytes), filename=f"event_illustration_{i+1}.png")
                        generated_files.append(file)
            
            if generated_files:
                gossip_embed = discord.Embed(
                    title="🎨 Зарисовки к последним событиям", 
                    description="Изображения, увиденные через магический артефакт Архивариуса...", 
                    color=embed_color
                )
                await interaction.followup.send(embed=gossip_embed, files=generated_files)

    except Exception as e:
        print(f"Произошла ошибка при обработке запроса /ask_lore: {e}")
        await interaction.followup.send(embed=discord.Embed(title="🚫 Ошибка в архиве", description="Архивариус не смог найти ответ или его артефакт дал сбой.", color=discord.Color.dark_red()), ephemeral=True)


@bot.tree.command(name="help", description="Показывает информацию обо всех доступных командах.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Справка по командам", description="Вот список всех доступных команд и их описание:", color=discord.Color.blue())
    
    character_commands_description = (
        "**`add`**: Создать нового персонажа (имя, аватар, краткое описание).\n"
        "**`set_bio`**: Загрузить полную биографию из `.txt` файла для персонажа.\n"
        "**`delete`**: Удалить одного из ваших персонажей.\n"
        "**`select`**: Выбрать активного персонажа для других команд.\n"
        "**`view`**: Посмотреть профиль активного персонажа."
    )
    embed.add_field(name="/character [подкоманда]", value=character_commands_description, inline=False)
    
    embed.add_field(name="/optimize_post", value="Улучшает ваш РП-пост. Использует данные активного персонажа для лучшего результата.", inline=False)
    embed.add_field(name="/ask_lore", value="Задает вопрос Хранителю знаний по миру 'Вальдеса'. Ответ будет виден всем в канале.", inline=False)
    embed.add_field(name="/about", value="Показывает информацию о боте и его создателе.", inline=False)
    embed.add_field(name="/help", value="Показывает это справочное сообщение.", inline=False)
    embed.add_field(name="/update_lore", value="**[Только для администраторов]**\nСобирает лор, обновляет файл и перезапускает бота.", inline=False)
    embed.set_footer(text="Ваш верный помощник в мире Вальдеса.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="about", description="Показывает информацию о боте и его создателе.")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(title="О боте 'Хранитель Вальдеса'", description="Я — ассистент, созданный для помощи игрокам и администрации текстового ролевого проекта 'Вальдес'.", color=discord.Color.gold())
    embed.add_field(name="Разработчик", value="**GX**", inline=True)
    embed.add_field(name="Технологии", value="• Discord.py\n• Google Gemini API\n• Pollinations.ai", inline=True)
    embed.set_footer(text=f"Бот запущен на сервере: {interaction.guild.name}")
    await interaction.response.send_message(embed=embed, ephemeral=False)

# --- 8. КОМАНДЫ УПРАВЛЕНИЯ ПЕРСОНАЖАМИ ---
character_group = app_commands.Group(name="character", description="Управление вашими персонажами")

async def character_name_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    user_id = str(interaction.user.id)
    if user_id not in CHARACTERS_DATA:
        return []
    
    chars = CHARACTERS_DATA.get(user_id, {}).get('characters', [])
    return [
        app_commands.Choice(name=char['name'], value=char['name'])
        for char in chars if current.lower() in char['name'].lower()
    ]

@character_group.command(name="add", description="Добавить нового персонажа в систему.")
@app_commands.describe(
    name="Имя вашего персонажа.", 
    description="Краткое описание характера, внешности, манер.", 
    avatar="Изображение вашего персонажа."
)
async def character_add(interaction: discord.Interaction, name: str, description: str, avatar: discord.Attachment):
    if not avatar.content_type or not avatar.content_type.startswith('image/'):
        await interaction.response.send_message("❌ Файл для аватара должен быть изображением.", ephemeral=True)
        return

    user_id = str(interaction.user.id)

    if user_id not in CHARACTERS_DATA:
        CHARACTERS_DATA[user_id] = {"active_character": None, "characters": []}

    if any(char['name'] == name for char in CHARACTERS_DATA[user_id]['characters']):
        await interaction.response.send_message(f"❌ Персонаж с именем '{name}' у вас уже существует.", ephemeral=True)
        return

    new_char = {
        "name": name,
        "description": description,
        "avatar_url": avatar.url
    }
    CHARACTERS_DATA[user_id]['characters'].append(new_char)
    
    if not CHARACTERS_DATA[user_id]['active_character']:
        CHARACTERS_DATA[user_id]['active_character'] = name

    save_characters()
    
    embed = discord.Embed(title=f"✅ Персонаж '{name}' успешно добавлен!", color=discord.Color.green())
    embed.set_thumbnail(url=avatar.url)
    embed.add_field(name="Описание", value=description, inline=False)
    if CHARACTERS_DATA[user_id]['active_character'] == name:
         embed.set_footer(text="Он автоматически выбран как активный. Вы можете добавить полную биографию через /character set_bio.")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@character_group.command(name="set_bio", description="Загрузить или обновить полную биографию персонажа из .txt файла.")
@app_commands.describe(
    name="Имя персонажа, чью биографию вы хотите обновить.",
    file="Файл .txt с полной биографией."
)
@app_commands.autocomplete(name=character_name_autocomplete)
async def character_set_bio(interaction: discord.Interaction, name: str, file: discord.Attachment):
    user_id = str(interaction.user.id)

    if user_id not in CHARACTERS_DATA or not any(c['name'] == name for c in CHARACTERS_DATA[user_id]['characters']):
        await interaction.response.send_message(f"❌ Персонаж с именем '{name}' не найден. Сначала создайте его через `/character add`.", ephemeral=True)
        return
        
    if not file.filename.lower().endswith('.txt'):
        await interaction.response.send_message("❌ **Ошибка:** Файл должен быть в формате `.txt`.", ephemeral=True)
        return
    if file.size > 20000:
         await interaction.response.send_message("❌ **Ошибка:** Файл слишком большой. Максимальный размер - 20 КБ.", ephemeral=True)
         return
        
    try:
        file_bytes = await file.read()
        description_text = file_bytes.decode('utf-8').strip()
    except Exception as e:
        await interaction.response.send_message(f"❌ **Ошибка:** Не удалось прочитать файл. Убедитесь, что он в кодировке UTF-8. ({e})", ephemeral=True)
        return

    for char in CHARACTERS_DATA[user_id]['characters']:
        if char['name'] == name:
            char['description'] = description_text
            break
    
    save_characters()
    
    embed = discord.Embed(title=f"✅ Биография персонажа '{name}' обновлена!", color=discord.Color.green())
    embed.add_field(name="Превью новой биографии", value=f"{description_text[:1000]}...", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@character_group.command(name="delete", description="Удалить вашего персонажа из системы.")
@app_commands.describe(name="Имя персонажа, которого хотите удалить.")
@app_commands.autocomplete(name=character_name_autocomplete)
async def character_delete(interaction: discord.Interaction, name: str):
    user_id = str(interaction.user.id)
    
    if user_id not in CHARACTERS_DATA or not CHARACTERS_DATA[user_id]['characters']:
        await interaction.response.send_message("❌ У вас нет зарегистрированных персонажей.", ephemeral=True)
        return

    char_to_delete = next((char for char in CHARACTERS_DATA[user_id]['characters'] if char['name'] == name), None)

    if not char_to_delete:
        await interaction.response.send_message(f"❌ Персонаж с именем '{name}' не найден.", ephemeral=True)
        return

    CHARACTERS_DATA[user_id]['characters'].remove(char_to_delete)
    
    if CHARACTERS_DATA[user_id]['active_character'] == name:
        CHARACTERS_DATA[user_id]['active_character'] = None
        if CHARACTERS_DATA[user_id]['characters']:
            CHARACTERS_DATA[user_id]['active_character'] = CHARACTERS_DATA[user_id]['characters'][0]['name']

    save_characters()
    await interaction.response.send_message(f"✅ Персонаж '{name}' был успешно удален.", ephemeral=True)


@character_group.command(name="select", description="Выбрать активного персонажа для использования в командах.")
@app_commands.describe(name="Имя персонажа, которого хотите сделать активным.")
@app_commands.autocomplete(name=character_name_autocomplete)
async def character_select(interaction: discord.Interaction, name: str):
    user_id = str(interaction.user.id)
    
    if user_id not in CHARACTERS_DATA or not CHARACTERS_DATA[user_id]['characters']:
        await interaction.response.send_message("❌ У вас нет зарегистрированных персонажей.", ephemeral=True)
        return
        
    char_to_select = next((char for char in CHARACTERS_DATA[user_id]['characters'] if char['name'] == name), None)
    
    if not char_to_select:
        await interaction.response.send_message(f"❌ Персонаж с именем '{name}' не найден.", ephemeral=True)
        return

    CHARACTERS_DATA[user_id]['active_character'] = name
    save_characters()
    
    embed = discord.Embed(title="👤 Активный персонаж изменен", description=f"Теперь ваши команды будут использовать профиль **{name}**.", color=discord.Color.blue())
    embed.set_thumbnail(url=char_to_select.get('avatar_url'))
    await interaction.response.send_message(embed=embed, ephemeral=True)


@character_group.command(name="view", description="Показать информацию о вашем текущем активном персонаже.")
async def character_view(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if user_id not in CHARACTERS_DATA or not CHARACTERS_DATA[user_id]['active_character']:
        await interaction.response.send_message("❌ У вас не выбран активный персонаж. Добавьте его через `/character add`.", ephemeral=True)
        return
        
    active_char_name = CHARACTERS_DATA[user_id]['active_character']
    active_char_info = next((char for char in CHARACTERS_DATA[user_id]['characters'] if char['name'] == active_char_name), None)

    if not active_char_info:
         await interaction.response.send_message("❌ Ошибка: данные активного персонажа не найдены.", ephemeral=True)
         return

    embed = discord.Embed(title=f"Профиль персонажа: {active_char_info['name']}", description=active_char_info['description'], color=discord.Color.purple())
    embed.set_thumbnail(url=active_char_info.get('avatar_url'))
    embed.set_footer(text="Этот персонаж сейчас активен для команд.")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.tree.add_command(character_group)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
