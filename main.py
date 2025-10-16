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
import asyncio
import re
import shutil
import aiohttp
from typing import List
import urllib.parse
import traceback # Для подробных отчетов об ошибках

# --- Загрузка переменных окружения ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAIN_GUILD_ID = os.getenv("MAIN_GUILD_ID")
ADMIN_GUILD_ID = os.getenv("ADMIN_GUILD_ID")
CODE_CHANNEL_ID = os.getenv("CODE_CHANNEL_ID")
OWNER_USER_ID = os.getenv("OWNER_USER_ID")
LORE_CHANNEL_IDS = os.getenv("LORE_CHANNEL_IDS")
GOSSIP_CHANNEL_ID = os.getenv("GOSSIP_CHANNEL_ID")
IS_TEST_BOT = os.getenv("IS_TEST_BOT", "False").lower() == "true"

# --- Критическая проверка переменных ---
if not all([DISCORD_TOKEN, GEMINI_API_KEY, MAIN_GUILD_ID, ADMIN_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID, LORE_CHANNEL_IDS, GOSSIP_CHANNEL_ID]):
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Один из ключей или ID не найден в .env файле.")

# --- Настройка API Gemini ---
genai.configure(api_key=GEMINI_API_KEY)

# --- 2. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
VALDES_LORE = ""
VALDES_GOSSIP = ""
LORE_IMAGES_DIR = "lore_images"
IMAGE_MAP_FILE = "image_map.json"
CHARACTER_DATA_FILE = "characters.json"
CHARACTERS_DATA = {}
GENERATED_FILES_SESSION = []

# --- 3. ИНСТРУМЕНТЫ ДЛЯ GEMINI ---

async def generate_pollinations_image_async(description_prompt: str) -> bytes | None:
    """Асинхронная функция, которая непосредственно выполняет веб-запрос."""
    try:
        full_prompt = f"ancient scroll, old paper texture, ink drawing, colorless, sketch style, black and white, masterpiece, depicting {description_prompt}"
        encoded_prompt = urllib.parse.quote_plus(full_prompt)
        url = f"https://pollinations.ai/p/{encoded_prompt}?width=1024&height=768&seed={random.randint(1, 100000)}&model=flux"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=120) as resp:
                if resp.status == 200:
                    return await resp.read()
                print(f"Ошибка при запросе к Pollinations.ai: Статус {resp.status}")
                return None
    except Exception as e:
        print(f"Критическая ошибка при генерации изображения: {e}")
        return None

def generate_image(description_prompt: str):
    """
    Синхронная обертка для Gemini. Запускает асинхронный код в новом цикле
    в фоновом потоке, не блокируя основной цикл бота.
    """
    global GENERATED_FILES_SESSION
    print(f"  [Инструмент] Получен вызов generate_image с промптом: '{description_prompt}'")
    
    image_bytes = asyncio.run(generate_pollinations_image_async(description_prompt))
    
    if image_bytes:
        file = discord.File(io.BytesIO(image_bytes), filename=f"event_illustration_{random.randint(1,999)}.png")
        GENERATED_FILES_SESSION.append(file)
        print("  [Инструмент] Изображение успешно сгенерировано и добавлено в сессию.")
        return {"status": "success", "message": "Изображение было успешно сгенерировано."}
    else:
        print("  [Инструмент] Ошибка: Не удалось сгенерировать изображение.")
        return {"status": "error", "message": "Не удалось сгенерировать изображение."}

# --- Инициализация моделей Gemini ---
safety_settings = {
    genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
}
lore_model = genai.GenerativeModel('gemini-2.5-flash', tools=[generate_image], safety_settings=safety_settings)
simple_model = genai.GenerativeModel('gemini-2.5-flash', safety_settings=safety_settings)

# --- 4. ФУНКЦИИ-ЗАГРУЗЧИКИ ДАННЫХ ---
def load_lore_from_file():
    global VALDES_LORE
    try:
        with open("file.txt", "r", encoding="utf-8") as f: VALDES_LORE = f.read()
        print("Основной лор успешно загружен.")
    except FileNotFoundError:
        print("КРИТИКА: Файл 'file.txt' не найден."); VALDES_LORE = "Лор не загружен."

def load_gossip_from_file():
    global VALDES_GOSSIP
    try:
        with open("gossip.txt", "r", encoding="utf-8") as f: VALDES_GOSSIP = f.read()
        print("Лор сплетен успешно загружен.")
    except FileNotFoundError:
        print("ПРЕДУПРЕЖДЕНИЕ: Файл 'gossip.txt' не найден."); VALDES_GOSSIP = "Событий не зафиксировано."

def load_characters():
    global CHARACTERS_DATA
    try:
        with open(CHARACTER_DATA_FILE, 'r', encoding='utf-8') as f: CHARACTERS_DATA = json.load(f)
        print("Данные персонажей успешно загружены.")
    except (FileNotFoundError, json.JSONDecodeError):
        CHARACTERS_DATA = {}; print("Файл персонажей не найден или пуст.")

def save_characters():
    with open(CHARACTER_DATA_FILE, 'w', encoding='utf-8') as f: json.dump(CHARACTERS_DATA, f, indent=4)

# --- 5. СИСТЕМНЫЕ ПРОМПТЫ ---
def get_optimizer_prompt(character_info=None):
    character_context_prompt = ""
    if character_info:
        character_context_prompt = f"**КОНТЕКСТ О ПЕРСОНАЖЕ:**\n- **Имя:** {character_info['name']}\n- **Описание и характер:** {character_info['description']}\nОсновывайся на этой информации, чтобы сохранить стиль персонажа."
    return f"Ты — ассистент для текстового ролевого проекта 'Вальдес'. Твоя задача — идеально отформатировать и, при необходимости, улучшить пост игрока.\n{character_context_prompt}\n**ПРАВИЛА ОФОРМЛЕНИЯ (СТРОГО):**\n1.  **ДЕЙСТВИЯ:** В одинарных звездочках. `*Он встал.*`\n2.  **МЫСЛИ/ЗВУКИ:** В двойных звездочках. `**Что за...**`\n3.  **РЕЧЬ:** Начинается с дефиса и пробела. `- Привет.`\n4.  Каждый тип (действие, мысль, речь) **ОБЯЗАН** начинаться с новой строки.\n**ПРАВИЛА ОБРАБОТКИ:**\n1.  **ОТ ТРЕТЬЕГО ЛИЦА:** Всегда пиши 'Он/Она', даже если игрок написал 'Я'.\n2.  **НЕ ДОДУМЫВАЙ:** Не добавляй новых действий или мыслей. Ты редактор, а не соавтор."

def get_serious_lore_prompt():
    return f"Ты — Хранитель знаний мира 'Вальдес'. Отвечай на вопросы, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном тексте.\n**ПРАВИЛА:**\n1.  **ИСТОЧНИК — ЗАКОН:** Используй только текст ниже.\n2.  **НЕ ДОДУМЫВАЙ:** Если ответа нет, скажи: 'В архивах нет точной информации по этому вопросу.'\n3.  **ЦИТИРОВАНИЕ:** В конце ответа **ОБЯЗАТЕЛЬНО** добавь разделитель `%%SOURCES%%` и после него перечисли упоминания каналов, откуда взята информация.\n4.  **ИНСТРУМЕНТЫ:** Если твой ответ содержит информацию из 'СВОДКИ СОБЫТИЙ', ты **ДОЛЖЕН** вызвать инструмент `generate_image`, чтобы проиллюстрировать каждое упомянутое событие. После вызова дождись результата и сформулируй финальный текстовый ответ.\n\n**ТВОЯ БАЗА ЗНАНИЙ:**\n--- ЛОР ---\n{VALDES_LORE}\n--- СВОДКА СОБЫТИЙ ---\n{VALDES_GOSSIP}"

def get_edgy_lore_prompt():
    return f"Ты — Архивариус Вальдеса. Циничный, уставший от жизни старик. Твои знания ОГРАНИЧЕНЫ предоставленным текстом.\n**ПРАВИЛА, ЗАСРАНЕЦ:**\n1.  **ОСНОВА — ЛОР:** Отвечай по сути, своими словами.\n2.  **ДОДУМЫВАЙ ВНУТРИ ЛОРА:** Можешь делать циничные предположения на основе фактов.\n3.  **ЦИТИРОВАНИЕ:** После ответа поставь `%%SOURCES%%` и перечисли упоминания каналов.\n4.  **ИНСТРУМЕНТЫ:** Твой магический артефакт показывает образы. Если отвечаешь на что-то из новостей, **ДОЛЖЕН** использовать инструмент `generate_image`, чтобы зарисовать эту херню. Опиши ему сцену. Когда он отработает, просто дай свой обычный едкий ответ.\n\n**ТВОЯ БАЗА ЗНАНИЙ:**\n--- ЛОР ---\n{VALDES_LORE}\n--- НОВОСТИ С АРТЕФАКТА ---\n{VALDES_GOSSIP}"

# --- 6. ВСПОМОГАТЕЛЬНЫЙ КОД И НАСТРОЙКА БОТА ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

intents = discord.Intents.default(); intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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
        await interaction.response.send_modal(OptimizedPostModal(self.optimized_text))

# --- 7. ЕЖЕДНЕВНЫЕ ЗАДАЧИ И СОБЫТИЯ БОТА ---
DAILY_ACCESS_CODE = ""
CODE_FILE = "code.json"
def save_daily_code(code):
    with open(CODE_FILE, 'w') as f: json.dump({'code': code, 'date': datetime.now().strftime('%Y-%m-%d')}, f)
def load_daily_code():
    global DAILY_ACCESS_CODE
    try:
        with open(CODE_FILE, 'r') as f: data = json.load(f)
        if data['date'] == datetime.now().strftime('%Y-%m-%d'):
            DAILY_ACCESS_CODE = data['code']; print(f"Загружен код доступа: {DAILY_ACCESS_CODE}"); return
    except (FileNotFoundError, json.JSONDecodeError): pass
    DAILY_ACCESS_CODE = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    save_daily_code(DAILY_ACCESS_CODE); print(f"Сгенерирован новый код: {DAILY_ACCESS_CODE}")

async def send_access_code_to_admin_channel(code: str, title: str, description: str):
    try:
        channel = bot.get_channel(int(CODE_CHANNEL_ID))
        if channel:
            embed = discord.Embed(title=title, description=description, color=discord.Color.gold(), timestamp=datetime.now())
            embed.add_field(name="Код", value=f"```{code}```").set_footer(text="Действителен до конца суток (UTC).")
            await channel.send(embed=embed)
    except Exception as e: print(f"Ошибка при отправке кода: {e}")

@tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
async def update_code_task():
    global DAILY_ACCESS_CODE
    DAILY_ACCESS_CODE = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    save_daily_code(DAILY_ACCESS_CODE)
    print(f"Сгенерирован новый ежедневный код: {DAILY_ACCESS_CODE}")
    await send_access_code_to_admin_channel(DAILY_ACCESS_CODE, "🔑 Новый ежедневный код доступа", "Код для `/update_lore` на 24 часа:")

@tasks.loop(time=time(hour=0, minute=5, tzinfo=timezone.utc))
async def update_gossip_task():
    print("\n[Ежедневная задача] Запускаю обновление сплетен...")
    try:
        gossip_channel = await bot.fetch_channel(int(GOSSIP_CHANNEL_ID))
        print(f"[Ежедневная задача] Доступ к каналу '{gossip_channel.name}' получен.")
        async with aiohttp.ClientSession() as session:
            gossip_text, msg_count, _, _ = await parse_channel_content([gossip_channel], session, download_images=False)
        with open("gossip.txt", "w", encoding="utf-8") as f: f.write(gossip_text)
        load_gossip_from_file()
        print(f"[Ежедневная задача] Обновление сплетен завершено. Обработано {msg_count} сообщений.\n")
    except (discord.NotFound, discord.Forbidden):
        print(f"[Ежедневная задача] КРИТИКА: Не удалось найти/получить доступ к каналу сплетен. Задача прервана.")
    except Exception as e: print(f"[Ежедневная задача] Непредвиденная ошибка: {e}")

@update_code_task.before_loop
async def before_tasks(): await bot.wait_until_ready()
@update_gossip_task.before_loop
async def before_gossip_task(): await bot.wait_until_ready()

@bot.event
async def on_ready():
    print(f"--- БОТ {bot.user} ЗАПУЩЕН {'В ТЕСТОВОМ РЕЖИМЕ' if IS_TEST_BOT else ''} ---")
    load_lore_from_file(); load_gossip_from_file(); load_characters()
    if not IS_TEST_BOT:
        load_daily_code()
        if not update_code_task.is_running(): update_code_task.start()
        if not update_gossip_task.is_running(): update_gossip_task.start()
        await send_access_code_to_admin_channel(DAILY_ACCESS_CODE, "⚙️ Текущий код (после перезапуска)", "Актуальный код на сегодня:")
    try:
        synced = await bot.tree.sync(); print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e: print(f"Ошибка синхронизации: {e}")

# --- 8. ОСНОВНЫЕ КОМАНДЫ БОТА ---
def clean_discord_mentions(text: str, guild: discord.Guild) -> str:
    if not text: return ""
    text = re.sub(r'<#(\d+)>', lambda m: f'#{bot.get_channel(int(m.group(1))).name}' if bot.get_channel(int(m.group(1))) else m.group(0), text)
    if guild: text = re.sub(r'<@&(\d+)>', lambda m: f'@{guild.get_role(int(m.group(1))).name}' if guild.get_role(int(m.group(1))) else m.group(0), text)
    text = re.sub(r'<@!?(\d+)>', lambda m: f'@{bot.get_user(int(m.group(1))).display_name}' if bot.get_user(int(m.group(1))) else m.group(0), text)
    return text

async def parse_channel_content(channels_to_parse: list, session: aiohttp.ClientSession, download_images: bool = True):
    full_text, total_messages_count, image_id_counter, image_map, downloaded_images_count = "", 0, 1, {}, 0
    sorted_channels = sorted(channels_to_parse, key=lambda c: c.position)
    async def download_and_register_image(url):
        nonlocal image_id_counter, image_map, downloaded_images_count
        if not download_images: return ""
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    image_bytes = await resp.read(); image_id = f"IMAGE_{image_id_counter}"; content_type = resp.headers.get('Content-Type', ''); file_extension = 'png'
                    if 'jpeg' in content_type or 'jpg' in content_type: file_extension = 'jpg'
                    elif 'png' in content_type: file_extension = 'png'
                    elif 'gif' in content_type: file_extension = 'gif'
                    elif 'webp' in content_type: file_extension = 'webp'
                    new_filename = f"{image_id}.{file_extension}"; save_path = os.path.join(LORE_IMAGES_DIR, new_filename)
                    with open(save_path, 'wb') as f: f.write(image_bytes)
                    image_map[image_id] = new_filename; image_id_counter += 1; downloaded_images_count += 1
                    return f"[{image_id}]"
                return ""
        except Exception as e: print(f"Ошибка скачивания {url}: {e}"); return ""
    for channel in sorted_channels:
        guild = channel.guild; full_text += f"\n--- НАЧАЛО КАНАЛА: {channel.mention} ---\n\n"
        async def parse_message(message):
            nonlocal full_text, total_messages_count
            content_parts = []
            if message.content: content_parts.append(clean_discord_mentions(message.content.strip(), guild))
            if message.embeds:
                for embed in message.embeds:
                    embed_text_parts = []
                    if embed.title: embed_text_parts.append(f"**{clean_discord_mentions(embed.title, guild)}**")
                    if embed.description: embed_text_parts.append(clean_discord_mentions(embed.description, guild))
                    if embed_text_parts: content_parts.append("\n".join(embed_text_parts))
                    if embed.image and embed.image.url:
                        image_tag = await download_and_register_image(embed.image.url)
                        if image_tag: content_parts.append(image_tag)
                    for field in embed.fields: content_parts.append(f"**{clean_discord_mentions(field.name, guild)}**\n{clean_discord_mentions(field.value, guild)}")
            if message.attachments:
                for attachment in [att for att in message.attachments if att.content_type and att.content_type.startswith('image/')]:
                    image_tag = await download_and_register_image(attachment.url)
                    if image_tag: content_parts.append(image_tag)
            if content_parts: full_text += "\n\n".join(filter(None, content_parts)) + "\n\n"; total_messages_count += 1
        if isinstance(channel, discord.ForumChannel):
            all_threads = channel.threads
            try: all_threads.extend([thread async for thread in channel.archived_threads(limit=None)])
            except discord.Forbidden: print(f"Нет прав на архивные ветки в: {channel.name}")
            for thread in sorted(all_threads, key=lambda t: t.created_at):
                full_text += f"--- Публикация: {thread.name} ---\n\n"
                async for message in thread.history(limit=500, oldest_first=True): await parse_message(message)
                full_text += f"--- Конец публикации: {thread.name} ---\n\n"
        else:
            async for message in channel.history(limit=500, oldest_first=True): await parse_message(message)
        full_text += f"--- КОНЕЦ КАНАЛА: {channel.mention} ---\n"
    return full_text, total_messages_count, downloaded_images_count, image_map

@bot.tree.command(name="update_lore", description="[АДМИН] Собирает лор и обновляет бота.")
@app_commands.describe(access_code="Ежедневный код доступа.")
async def update_lore(interaction: discord.Interaction, access_code: str):
    print("Получена команда /update_lore. Проверяю доступы...");
    if IS_TEST_BOT: await interaction.response.send_message("❌ Команда отключена в тестовом режиме.", ephemeral=True); return
    if str(interaction.user.id) != OWNER_USER_ID and not interaction.user.guild_permissions.administrator: await interaction.response.send_message("❌ Только администраторы.", ephemeral=True); return
    if str(interaction.guild.id) != MAIN_GUILD_ID: await interaction.response.send_message("❌ Команда запрещена на этом сервере.", ephemeral=True); return
    if access_code != DAILY_ACCESS_CODE: await interaction.response.send_message("❌ Неверный код доступа.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True, thinking=True)
    if os.path.exists(LORE_IMAGES_DIR): shutil.rmtree(LORE_IMAGES_DIR)
    os.makedirs(LORE_IMAGES_DIR)
    try:
        lore_channel_ids = [int(id.strip()) for id in LORE_CHANNEL_IDS.split(',')]
        gossip_channel_id = int(GOSSIP_CHANNEL_ID)
    except ValueError: await interaction.followup.send("❌ Ошибка конфигурации ID каналов в .env.", ephemeral=True); return
    lore_channels = []
    print("Загружаю объекты лор-каналов...")
    for cid in lore_channel_ids:
        try:
            channel = await bot.fetch_channel(cid); lore_channels.append(channel); print(f"  [+] Канал '{channel.name}' найден.")
        except (discord.NotFound, discord.Forbidden):
            print(f"  [!] ОШИБКА: Не удалось получить доступ к лор-каналу ID {cid}.")
            await interaction.followup.send(f"⚠️ Предупреждение: нет доступа к лор-каналу `{cid}`.", ephemeral=True)
    print("Загружаю объект канала сплетен...")
    try:
        gossip_channel = await bot.fetch_channel(gossip_channel_id); print(f"  [+] Канал '{gossip_channel.name}' найден.")
    except (discord.NotFound, discord.Forbidden):
        print(f"  [!] КРИТИКА: Нет доступа к каналу сплетен ID {gossip_channel_id}.")
        await interaction.followup.send(f"❌ Критическая ошибка: нет доступа к каналу сплетен `{gossip_channel_id}`.", ephemeral=True); return
    print("\nАнализирую каналы...");
    async with aiohttp.ClientSession() as session:
        full_lore_text, lore_msg, img_count, img_map = await parse_channel_content(lore_channels, session, download_images=True)
        gossip_text, gossip_msg, _, _ = await parse_channel_content([gossip_channel], session, download_images=False)
    print("Анализ завершен. Сохраняю файлы...")
    try:
        with open("file.txt", "w", encoding="utf-8") as f: f.write(full_lore_text)
        with open(IMAGE_MAP_FILE, "w", encoding="utf-8") as f: json.dump(img_map, f, indent=4)
        with open("gossip.txt", "w", encoding="utf-8") as f: f.write(gossip_text)
        print("Файлы сохранены. Перезагружаю данные в память...")
        load_lore_from_file(); load_gossip_from_file()
        embed = discord.Embed(title="✅ Лор и события успешно обновлены!", color=discord.Color.green())
        embed.add_field(name="Лор-каналы", value=str(len(lore_channels)), inline=True).add_field(name="Лор-сообщения", value=str(lore_msg), inline=True).add_field(name="Изображения", value=str(img_count), inline=True)
        embed.add_field(name="События", value=str(gossip_msg), inline=True).add_field(name="Размер лора", value=f"{os.path.getsize('file.txt') / 1024:.2f} КБ", inline=True).add_field(name="Размер событий", value=f"{os.path.getsize('gossip.txt') / 1024:.2f} КБ", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
        print("Отправлено подтверждение. Перезапуск через 5 секунд...")
        await interaction.followup.send("✅ **Данные обновлены.** Перезапускаюсь...", ephemeral=True)
        await asyncio.sleep(5); await bot.close()
    except Exception as e:
        print(f"КРИТИКА при записи файлов: {e}"); await interaction.followup.send(f"Критическая ошибка при записи файлов: {e}", ephemeral=True)

@bot.tree.command(name="optimize_post", description="Улучшает РП-пост, сохраняя стиль вашего персонажа.")
@app_commands.describe(post_text="Текст вашего поста.", image="(Опционально) Изображение для контекста.")
async def optimize_post(interaction: discord.Interaction, post_text: str, image: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if image and (not image.content_type or not image.content_type.startswith("image/")):
        await interaction.followup.send("❌ Прикрепленный файл не является изображением.", ephemeral=True); return
    user_id = str(interaction.user.id); active_character_info = None
    if user_id in CHARACTERS_DATA and CHARACTERS_DATA[user_id].get('active_character'):
        active_char_name = CHARACTERS_DATA[user_id]['active_character']
        active_character_info = next((char for char in CHARACTERS_DATA[user_id]['characters'] if char['name'] == active_char_name), None)
    prompt = get_optimizer_prompt(active_character_info); content_to_send = [prompt, f"\n\nПост игрока:\n---\n{post_text}"]
    if image:
        try: content_to_send.append(Image.open(io.BytesIO(await image.read())))
        except Exception: await interaction.followup.send("⚠️ Не удалось обработать изображение.", ephemeral=True, delete_after=10)
    try:
        response = await simple_model.generate_content_async(content_to_send)
        result_text = response.text.strip()
        embed = discord.Embed(title="✨ Ваш пост был оптимизирован!", color=discord.Color.gold())
        if active_character_info: embed.set_author(name=f"Персонаж: {active_character_info['name']}", icon_url=active_character_info.get('avatar_url'))
        embed.add_field(name="▶️ Оригинал (превью):", value=f"```\n{post_text[:500]}\n```", inline=False)
        embed.add_field(name="✅ Улучшенная версия (превью):", value=f"{result_text[:500]}...", inline=False)
        await interaction.followup.send(embed=embed, view=PostView(result_text), ephemeral=True)
    except Exception as e:
        print(f"Ошибка в /optimize_post: {e}"); await interaction.followup.send("🚫 Произошла внутренняя ошибка.", color=discord.Color.dark_red(), ephemeral=True)

@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.", personality="Выберите характер ответа.")
@app_commands.choices(personality=[
    discord.app_commands.Choice(name="Серьезный Архивариус", value="serious"),
    discord.app_commands.Choice(name="Циничный Старик (18+)", value="edgy")
])
async def ask_lore(interaction: discord.Interaction, question: str, personality: discord.app_commands.Choice[str] = None):
    global GENERATED_FILES_SESSION
    GENERATED_FILES_SESSION.clear()
    print(f"\nПолучен /ask_lore от '{interaction.user.display_name}'. Вопрос: '{question}'")
    await interaction.response.defer(ephemeral=False)
    
    try:
        if personality and personality.value == 'edgy':
            prompt = get_edgy_lore_prompt(); embed_color = discord.Color.red(); author_name = "Ответил Циничный Старик"
        else:
            prompt = get_serious_lore_prompt(); embed_color = discord.Color.blue(); author_name = "Ответил Хранитель знаний"
        
        print("Начинаю сессию с Gemini и отправляю первичный запрос...")
        chat_session = lore_model.start_chat()
        response = await chat_session.send_message_async(f"{prompt}\n\nВопрос игрока: {question}")

        while response.candidates[0].content.parts[0].function_call:
            fc = response.candidates[0].content.parts[0].function_call
            print(f"Gemini запросил вызов инструмента: {fc.name}")
            
            # Библиотека Gemini автоматически вызывает синхронные функции-инструменты в отдельном потоке,
            # что предотвращает блокировку основного потока Discord.
            result = generate_image(**{key: value for key, value in fc.args.items()})
            
            print("Инструмент отработал. Отправляю результат обратно в Gemini...")
            response = await chat_session.send_message_async(
                genai.Part.from_function_response(name=fc.name, response=result)
            )
        
        print("Вызовов инструментов больше нет. Получен финальный текстовый ответ.")
        raw_text = response.text.strip()
        answer_text, sources_text = (raw_text.split("%%SOURCES%%") + [""])[:2]
        answer_text = answer_text.strip(); sources_text = sources_text.strip()
        
        embed = discord.Embed(title="📜 Ответ из архивов Вальдеса", description=answer_text, color=embed_color)
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        if sources_text: embed.add_field(name="Источники:", value=sources_text, inline=False)
        embed.set_footer(text=f"{author_name} | Запросил: {interaction.user.display_name}")
        
        print("Отправляю финальный текстовый ответ...")
        await interaction.followup.send(embed=embed)

        if GENERATED_FILES_SESSION:
            print(f"Отправляю {len(GENERATED_FILES_SESSION)} сгенерированных изображений...")
            gossip_embed = discord.Embed(title="🎨 Зарисовки к последним событиям", description="Образы, увиденные через магический артефакт...", color=embed_color)
            await interaction.followup.send(embed=gossip_embed, files=GENERATED_FILES_SESSION)
        
        print("Обработка /ask_lore завершена.\n")
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ НЕПРЕДВИДЕННАЯ ОШИБКА в /ask_lore:")
        traceback.print_exc()
        await interaction.followup.send("🚫 Ошибка в архиве. Архивариус не смог найти ответ или его артефакт дал сбой. **Подробности записаны в лог консоли.**", ephemeral=True)
    finally:
        GENERATED_FILES_SESSION.clear()

@bot.tree.command(name="help", description="Показывает информацию обо всех доступных командах.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Справка по командам", color=discord.Color.blue())
    embed.add_field(name="/character [add|set_bio|delete|select|view]", value="Полный набор команд для управления вашими персонажами.", inline=False)
    embed.add_field(name="/optimize_post [post_text]", value="Улучшает ваш РП-пост, используя стиль активного персонажа.", inline=False)
    embed.add_field(name="/ask_lore [question]", value="Задает вопрос Хранителю знаний по миру 'Вальдеса'.", inline=False)
    embed.add_field(name="/about", value="Информация о боте.", inline=False)
    embed.add_field(name="/update_lore [access_code]", value="**[Админ]** Обновляет базу знаний бота и перезапускает его.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="about", description="Показывает информацию о боте.")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(title="О боте 'Хранитель Вальдеса'", color=discord.Color.gold())
    embed.add_field(name="Разработчик", value="**GX**", inline=True)
    embed.add_field(name="Технологии", value="• Discord.py\n• Google Gemini API\n• Pollinations.ai", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=False)

# --- 9. КОМАНДЫ УПРАВЛЕНИЯ ПЕРСОНАЖАМИ ---
character_group = app_commands.Group(name="character", description="Управление вашими персонажами")

async def character_name_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    user_id = str(interaction.user.id)
    if user_id not in CHARACTERS_DATA: return []
    chars = CHARACTERS_DATA.get(user_id, {}).get('characters', [])
    return [app_commands.Choice(name=char['name'], value=char['name']) for char in chars if current.lower() in char['name'].lower()]

@character_group.command(name="add", description="Добавить нового персонажа.")
@app_commands.describe(name="Имя персонажа.", description="Краткое описание.", avatar="Изображение.")
async def character_add(interaction: discord.Interaction, name: str, description: str, avatar: discord.Attachment):
    if not avatar.content_type or not avatar.content_type.startswith('image/'):
        await interaction.response.send_message("❌ Файл аватара должен быть изображением.", ephemeral=True); return
    user_id = str(interaction.user.id)
    if user_id not in CHARACTERS_DATA: CHARACTERS_DATA[user_id] = {"active_character": None, "characters": []}
    if any(char['name'] == name for char in CHARACTERS_DATA[user_id]['characters']):
        await interaction.response.send_message(f"❌ Персонаж '{name}' уже существует.", ephemeral=True); return
    new_char = {"name": name, "description": description, "avatar_url": avatar.url}
    CHARACTERS_DATA[user_id]['characters'].append(new_char)
    if not CHARACTERS_DATA[user_id]['active_character']: CHARACTERS_DATA[user_id]['active_character'] = name
    save_characters()
    embed = discord.Embed(title=f"✅ Персонаж '{name}' добавлен!", color=discord.Color.green()).set_thumbnail(url=avatar.url)
    embed.add_field(name="Описание", value=description, inline=False)
    if CHARACTERS_DATA[user_id]['active_character'] == name: embed.set_footer(text="Он автоматически выбран как активный.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@character_group.command(name="set_bio", description="Загрузить биографию персонажа из .txt файла.")
@app_commands.describe(name="Имя персонажа.", file="Файл .txt с биографией.")
@app_commands.autocomplete(name=character_name_autocomplete)
async def character_set_bio(interaction: discord.Interaction, name: str, file: discord.Attachment):
    user_id = str(interaction.user.id)
    if user_id not in CHARACTERS_DATA or not any(c['name'] == name for c in CHARACTERS_DATA[user_id]['characters']):
        await interaction.response.send_message(f"❌ Персонаж '{name}' не найден.", ephemeral=True); return
    if not file.filename.lower().endswith('.txt'): await interaction.response.send_message("❌ Файл должен быть `.txt`.", ephemeral=True); return
    if file.size > 20000: await interaction.response.send_message("❌ Файл слишком большой (макс. 20 КБ).", ephemeral=True); return
    try: description_text = (await file.read()).decode('utf-8').strip()
    except Exception as e: await interaction.response.send_message(f"❌ Не удалось прочитать файл: {e}", ephemeral=True); return
    for char in CHARACTERS_DATA[user_id]['characters']:
        if char['name'] == name: char['description'] = description_text; break
    save_characters()
    embed = discord.Embed(title=f"✅ Биография персонажа '{name}' обновлена!", color=discord.Color.green())
    embed.add_field(name="Превью", value=f"{description_text[:1000]}...", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@character_group.command(name="delete", description="Удалить вашего персонажа.")
@app_commands.describe(name="Имя персонажа для удаления.")
@app_commands.autocomplete(name=character_name_autocomplete)
async def character_delete(interaction: discord.Interaction, name: str):
    user_id = str(interaction.user.id)
    if user_id not in CHARACTERS_DATA or not CHARACTERS_DATA[user_id]['characters']:
        await interaction.response.send_message("❌ У вас нет персонажей.", ephemeral=True); return
    char_to_delete = next((char for char in CHARACTERS_DATA[user_id]['characters'] if char['name'] == name), None)
    if not char_to_delete: await interaction.response.send_message(f"❌ Персонаж '{name}' не найден.", ephemeral=True); return
    CHARACTERS_DATA[user_id]['characters'].remove(char_to_delete)
    if CHARACTERS_DATA[user_id]['active_character'] == name:
        CHARACTERS_DATA[user_id]['active_character'] = CHARACTERS_DATA[user_id]['characters'][0]['name'] if CHARACTERS_DATA[user_id]['characters'] else None
    save_characters()
    await interaction.response.send_message(f"✅ Персонаж '{name}' удален.", ephemeral=True)

@character_group.command(name="select", description="Выбрать активного персонажа.")
@app_commands.describe(name="Имя персонажа, которого сделать активным.")
@app_commands.autocomplete(name=character_name_autocomplete)
async def character_select(interaction: discord.Interaction, name: str):
    user_id = str(interaction.user.id)
    if user_id not in CHARACTERS_DATA or not CHARACTERS_DATA[user_id]['characters']:
        await interaction.response.send_message("❌ У вас нет персонажей.", ephemeral=True); return
    char_to_select = next((char for char in CHARACTERS_DATA[user_id]['characters'] if char['name'] == name), None)
    if not char_to_select: await interaction.response.send_message(f"❌ Персонаж '{name}' не найден.", ephemeral=True); return
    CHARACTERS_DATA[user_id]['active_character'] = name; save_characters()
    embed = discord.Embed(title="👤 Активный персонаж изменен", description=f"Теперь используется профиль **{name}**.", color=discord.Color.blue())
    embed.set_thumbnail(url=char_to_select.get('avatar_url'))
    await interaction.response.send_message(embed=embed, ephemeral=True)

@character_group.command(name="view", description="Показать профиль активного персонажа.")
async def character_view(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in CHARACTERS_DATA or not CHARACTERS_DATA[user_id].get('active_character'):
        await interaction.response.send_message("❌ Активный персонаж не выбран.", ephemeral=True); return
    active_char_name = CHARACTERS_DATA[user_id]['active_character']
    active_char_info = next((char for char in CHARACTERS_DATA[user_id]['characters'] if char['name'] == active_char_name), None)
    if not active_char_info: await interaction.response.send_message("❌ Ошибка: данные персонажа не найдены.", ephemeral=True); return
    embed = discord.Embed(title=f"Профиль: {active_char_info['name']}", description=active_char_info['description'], color=discord.Color.purple())
    embed.set_thumbnail(url=active_char_info.get('avatar_url'))
    embed.set_footer(text="Этот персонаж сейчас активен.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.tree.add_command(character_group)

# --- 10. ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)

