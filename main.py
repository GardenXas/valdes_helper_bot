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
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И ФУНКЦИИ ДЛЯ ЛОРА ---
VALDES_LORE = ""
LORE_IMAGES_DIR = "lore_images"
IMAGE_MAP_FILE = "image_map.json"

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
"""

def get_lore_prompt():
    """Возвращает системный промпт для ответов на вопросы по лору."""
    return f"""
Ты — Хранитель знаний мира 'Вальдес'. Твоя задача — отвечать на вопросы игроков, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном тебе тексте с лором и правилами.

**ТВОИ ПРАВИЛА:**
1.  **ИСТОЧНИК — ЗАКОН:** Используй только текст, приведенный ниже. Не добавляй никакой информации извне.
2.  **НЕ ДОДУМЫВАЙ:** Если в тексте нет прямого ответа на вопрос, честно скажи: "В предоставленных архивах нет точной информации по этому вопросу." В этом случае не добавляй источники.
3.  **СТИЛЬ:** Отвечай уважительно, в стиле мудрого летописца.
4.  **РАБОТА С ИЗОБРАЖЕНИЯМИ:** В тексте лора могут встречаться специальные теги вида `[IMAGE_XXX]`. Эти теги обозначают изображения, которые **относятся к тексту, в конце которого они стоят**. Если ты считаешь, что изображение напрямую иллюстрирует твой ответ, **обязательно добавь этот тег** в самый конец своего ответа, на новой строке.
    *   Пример ответа с изображением: `Дварфы - это низкорослый народ...%%SOURCES%%║...│канал\n[IMAGE_123]`
    *   Вставляй только ОДИН, самый релевантный тег. Не пиши ничего после тега.
5.  **ЦИТИРОВАНИЕ ИСТОЧНИКОВ (ОБЯЗАТЕЛЬНО):** После твоего основного ответа, ты **ДОЛЖЕН** добавить специальный разделитель `%%SOURCES%%`. После этого разделителя перечисли через запятую названия каналов, из которых была взята информация. Названия каналов находятся в строках формата `--- НАЧАЛО КАНАЛА: [Имя канала] ---`.
    *   Пример формата: `Ответ на вопрос.%%SOURCES%%║🌟│астромантия, ║🧬│виды-разумных-сущностей`

Вот текст, который является твоей единственной базой знаний:
--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---
"""

# НОВЫЙ ПРОМПТ ДЛЯ ГЕНЕРАЦИИ АНКЕТ
def get_character_prompt():
    """Возвращает системный промпт для генерации анкеты персонажа."""
    return f"""
Ты — Мастер-создатель персонажей для текстового ролевого проекта 'Вальдес'. Твоя задача — написать детальную и интересную анкету персонажа, который органично впишется в этот мир.

**СТРУКТУРА АНКЕТЫ (ОБЯЗАТЕЛЬНО):**
Анкета должна содержать следующие разделы, выделенные жирным шрифтом:
- **Имя:**
- **Возраст:**
- **Раса:** (Должна соответствовать лору мира)
- **Внешность:** (Подробное описание, 2-3 предложения)
- **Характер:** (Ключевые черты, манеры, мировоззрение, 2-3 предложения)
- **Предыстория:** (Краткая, но емкая история жизни, ключевые события, 3-4 предложения)
- **Навыки и способности:** (Что персонаж умеет делать, 2-3 пункта)

**ПРАВИЛА ГЕНЕРАЦИИ:**
1.  **ЛОР — ЭТО ЗАКОН:** Используй приведенный ниже текст с лором как основной источник информации о мире, расах, местах и событиях. Не придумывай того, что противоречит лору.
2.  **КРЕАТИВНОСТЬ:** На основе запроса игрока или при случайной генерации заполни пробелы, добавь интересные детали, сделай персонажа живым и уникальным.
3.  **ФОРМАТ:** Выдай в ответе ТОЛЬКО текст анкеты по указанной структуре. Никаких приветствий, вступлений или лишних фраз. Только анкета.

--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---
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

# НОВЫЕ UI ЭЛЕМЕНТЫ ДЛЯ АНКЕТЫ
class CharacterSheetModal(ui.Modal, title='Анкета персонажа'):
    def __init__(self, character_sheet_text: str):
        super().__init__(timeout=None)
        # Модальные окна имеют ограничение в 4000 символов
        self.sheet_content = ui.TextInput(label="Текст анкеты готов к копированию", style=discord.TextStyle.paragraph, default=character_sheet_text, max_length=4000)
        self.add_item(self.sheet_content)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Окно закрыто.", ephemeral=True, delete_after=3)

class CharacterSheetView(ui.View):
    def __init__(self, character_sheet_text: str):
        super().__init__(timeout=300)
        self.character_sheet_text = character_sheet_text
    @ui.button(label="📝 Показать и скопировать анкету", style=discord.ButtonStyle.primary)
    async def show_modal_button(self, interaction: discord.Interaction, button: ui.Button):
        modal = CharacterSheetModal(self.character_sheet_text)
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

# --- 6. УНИВЕРСАЛЬНАЯ ФУНКЦИЯ И ЕЖЕДНЕВНАЯ ЗАДАЧА ГЕНЕРАЦИИ КОДА ---
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
    await send_access_code_to_admin_channel(code=DAILY_ACCESS_CODE, title="⚙️ Текущий код доступа (После перезапуска)", description="Бот был перезапущен. Вот актуальный код на сегодня:")
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

# --- 7. КОМАНДЫ БОТА ---

# НОВАЯ ФУНКЦИЯ-ЧИСТИЛЬЩИК
def clean_discord_mentions(text: str, guild: discord.Guild) -> str:
    """Заменяет упоминания каналов, ролей и пользователей на их имена."""
    if not text:
        return ""

    # Замена упоминаний каналов: <#123456789> -> #channel-name
    text = re.sub(r'<#(\d+)>', lambda m: f'#{bot.get_channel(int(m.group(1))).name}' if bot.get_channel(int(m.group(1))) else m.group(0), text)
    
    # Замена упоминаний ролей: <@&123456789> -> @role-name
    if guild:
        text = re.sub(r'<@&(\d+)>', lambda m: f'@{guild.get_role(int(m.group(1))).name}' if guild.get_role(int(m.group(1))) else m.group(0), text)
    
    # Замена упоминаний пользователей: <@123456789> или <@!123456789> -> @username
    text = re.sub(r'<@!?(\d+)>', lambda m: f'@{bot.get_user(int(m.group(1))).display_name}' if bot.get_user(int(m.group(1))) else m.group(0), text)
    
    return text

@bot.tree.command(name="update_lore", description="[АДМИН] Собирает лор из заданных каналов и обновляет файл.")
@app_commands.describe(access_code="Ежедневный код доступа для подтверждения")
async def update_lore(interaction: discord.Interaction, access_code: str):
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
        channel_ids = [int(id.strip()) for id in LORE_CHANNEL_IDS.split(',')]
    except ValueError:
        await interaction.followup.send("❌ **Ошибка конфигурации:** Список ID каналов в .env содержит нечисловые значения.", ephemeral=True)
        return

    full_lore_text = ""
    parsed_channels_count = 0
    total_messages_count = 0
    image_id_counter = 1
    image_map = {}
    downloaded_images_count = 0
    
    channels_to_parse = [bot.get_channel(cid) for cid in channel_ids if bot.get_channel(cid) is not None]
    sorted_channels = sorted(channels_to_parse, key=lambda c: c.position)

    async with aiohttp.ClientSession() as session:
        
        async def download_and_register_image(url):
            nonlocal image_id_counter, image_map, downloaded_images_count
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
                    return None
            except Exception as e:
                print(f"Критическая ошибка при скачивании {url}: {e}")
                return None

        for channel in sorted_channels:
            full_lore_text += f"\n--- НАЧАЛО КАНАЛА: {channel.name} ---\n\n"
            
            async def parse_message(message, guild):
                nonlocal full_lore_text, total_messages_count
                
                content_parts = []
                
                # 1. Основной текст сообщения (уже очищенный)
                if message.content:
                    content_parts.append(clean_discord_mentions(message.content.strip(), guild))
                
                # 2. Обработка эмбедов
                if message.embeds:
                    for embed in message.embeds:
                        embed_text_parts = []
                        if embed.title:
                            embed_text_parts.append(f"**{clean_discord_mentions(embed.title, guild)}**")
                        if embed.description:
                            embed_text_parts.append(clean_discord_mentions(embed.description, guild))
                        
                        if embed_text_parts:
                            content_parts.append("\n".join(embed_text_parts))
                        
                        if embed.image and embed.image.url:
                            image_tag = await download_and_register_image(embed.image.url)
                            if image_tag: content_parts.append(image_tag)

                        for field in embed.fields:
                            field_name = clean_discord_mentions(field.name, guild)
                            field_value = clean_discord_mentions(field.value, guild)
                            field_text = f"**{field_name}**\n{field_value}"
                            content_parts.append(field_text)
                
                # 3. Обработка прикрепленных файлов
                if message.attachments:
                    image_attachments = [att for att in message.attachments if att.content_type and att.content_type.startswith('image/')]
                    for attachment in image_attachments:
                        image_tag = await download_and_register_image(attachment.url)
                        if image_tag: content_parts.append(image_tag)
                
                if content_parts:
                    final_text_for_message = "\n\n".join(filter(None, content_parts))
                    full_lore_text += final_text_for_message + "\n\n"
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
                    full_lore_text += f"--- Начало публикации: {thread.name} ---\n\n"
                    async for message in thread.history(limit=500, oldest_first=True):
                        await parse_message(message, interaction.guild) # Передаем guild
                    full_lore_text += f"--- Конец публикации: {thread.name} ---\n\n"
            else:
                async for message in channel.history(limit=500, oldest_first=True):
                    await parse_message(message, interaction.guild) # Передаем guild

            full_lore_text += f"--- КОНЕЦ КАНАЛА: {channel.name} ---\n"
            parsed_channels_count += 1

    try:
        with open("file.txt", "w", encoding="utf-8") as f:
            f.write(full_lore_text)
        with open(IMAGE_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(image_map, f, indent=4)
        
        load_lore_from_file()
        file_size = os.path.getsize("file.txt") / 1024
        
        embed = discord.Embed(title="✅ Лор успешно обновлен!", description="Файл `file.txt` был перезаписан и прикреплен к этому сообщению для проверки.", color=discord.Color.green())
        embed.add_field(name="Обработано каналов", value=str(parsed_channels_count), inline=True)
        embed.add_field(name="Собрано сообщений", value=str(total_messages_count), inline=True)
        embed.add_field(name="Скачано изображений", value=str(downloaded_images_count), inline=True)
        embed.add_field(name="Размер файла", value=f"{file_size:.2f} КБ", inline=True)
        
        await interaction.followup.send(embed=embed, file=discord.File("file.txt"), ephemeral=True)
        await interaction.followup.send("✅ **Лор обновлен.** Перезапускаюсь для применения изменений через 5 секунд...", ephemeral=True)
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

    level_map = {"minimal": "Минимальные правки", "standard": "Стандартная оптимизация", "creative": "Максимальная креативность"}
    prompt = get_optimizer_prompt(level_map[optimization_level.value])
    
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
        if result_text.startswith("ОШИБКА:"):
            error_embed = discord.Embed(title="❌ Обнаружена грубая лорная ошибка!", description=result_text.replace("ОШИБКА:", "").strip(), color=discord.Color.red())
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        else:
            embed = discord.Embed(title="✨ Ваш пост был оптимизирован!", color=discord.Color.gold())
            embed.add_field(name="▶️ Оригинал:", value=f"```\n{post_text[:1000]}\n```", inline=False)
            embed.add_field(name="✅ Улучшенная версия (превью):", value=f"{result_text[:1000]}...", inline=False)
            view = PostView(result_text)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        print(f"Произошла внутренняя ошибка в /optimize_post: {e}")
        await interaction.followup.send(embed=discord.Embed(title="🚫 Произошла внутренняя ошибка", description="Не удалось обработать ваш запрос.", color=discord.Color.dark_red()), ephemeral=True)


# ⭐ НОВАЯ КОМАНДА ⭐
@bot.tree.command(name="generate_character", description="Создает анкету персонажа для мира 'Вальдес'.")
@app_commands.describe(
    params="Опишите желаемые параметры (например: 'молодая эльфийка, лучница из лесов').",
    randomize="Создать полностью случайного персонажа? (игнорирует поле с параметрами)."
)
async def generate_character(interaction: discord.Interaction, params: str = None, randomize: bool = False):
    await interaction.response.defer(ephemeral=False, thinking=True)

    if not params and not randomize:
        await interaction.followup.send("❌ **Ошибка:** Вы должны либо описать персонажа в параметрах, либо выбрать опцию `randomize: True`.", ephemeral=True)
        return

    try:
        prompt = get_character_prompt()
        
        if randomize:
            user_request = "Запрос игрока: Создай полностью случайного, но интересного и лорного персонажа для мира Вальдес."
        else:
            user_request = f"Запрос игрока: Создай персонажа на основе следующего описания - '{params}'."

        response = await gemini_model.generate_content_async([prompt, user_request])
        result_text = response.text.strip()

        embed = discord.Embed(
            title="✨ Создана новая анкета персонажа!",
            description=result_text,
            color=discord.Color.purple()
        )
        request_info = "Полностью случайный персонаж" if randomize else f"'{params}'"
        embed.set_footer(text=f"Сгенерировано для: {interaction.user.display_name} | Запрос: {request_info}")

        view = CharacterSheetView(result_text)
        await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        print(f"Произошла ошибка при обработке запроса /generate_character: {e}")
        await interaction.followup.send(embed=discord.Embed(title="🚫 Ошибка генерации", description="Мастер-создатель не смог выполнить ваш запрос.", color=discord.Color.dark_red()), ephemeral=True)


@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.")
async def ask_lore(interaction: discord.Interaction, question: str):
    await interaction.response.defer(ephemeral=False)
    try:
        prompt = get_lore_prompt()
        response = await gemini_model.generate_content_async([prompt, f"\n\nВопрос игрока: {question}"])
        raw_text = response.text.strip()
        
        image_file_to_send = None
        
        image_tag_match = re.search(r'\[(IMAGE_\d+)\]', raw_text)
        if image_tag_match:
            image_id = image_tag_match.group(1)
            raw_text = raw_text.replace(image_tag_match.group(0), "").strip()
            
            try:
                with open(IMAGE_MAP_FILE, 'r', encoding='utf-8') as f:
                    image_map = json.load(f)
                filename = image_map.get(image_id)
                if filename:
                    image_path = os.path.join(LORE_IMAGES_DIR, filename)
                    if os.path.exists(image_path):
                        image_file_to_send = discord.File(image_path, filename="image.png")
            except (FileNotFoundError, json.JSONDecodeError) as e:
                print(f"ОШИБКА: Не удалось загрузить {IMAGE_MAP_FILE}: {e}")

        answer_text, sources_text = (raw_text.split("%%SOURCES%%") + [""])[:2]
        answer_text = answer_text.strip()
        sources_text = sources_text.strip()

        embed = discord.Embed(title="📜 Ответ из архивов Вальдеса", description=answer_text, color=discord.Color.blue())
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        if sources_text:
            embed.add_field(name="Источники:", value=sources_text, inline=False)
        if image_file_to_send:
            embed.set_image(url="attachment://image.png")
            
        embed.set_footer(text=f"Ответил Хранитель знаний | Запросил: {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed, file=image_file_to_send if image_file_to_send else discord.utils.MISSING)
    except Exception as e:
        print(f"Произошла ошибка при обработке запроса /ask_lore: {e}")
        await interaction.followup.send(embed=discord.Embed(title="🚫 Ошибка в архиве", description="Хранитель знаний не смог найти ответ.", color=discord.Color.dark_red()), ephemeral=True)

@bot.tree.command(name="help", description="Показывает информацию обо всех доступных командах.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Справка по командам", description="Вот список всех доступных команд и их описание:", color=discord.Color.blue())
    embed.add_field(name="/optimize_post", value="Улучшает ваш РП-пост. Принимает текст, уровень улучшения и опционально изображение.", inline=False)
    embed.add_field(name="/ask_lore", value="Задает вопрос Хранителю знаний по миру 'Вальдеса'. Ответ будет виден всем в канале.", inline=False)
    # ОБНОВЛЕННАЯ СЕКЦИЯ HELP
    embed.add_field(name="/generate_character", value="Создает анкету персонажа. Можно задать параметры или сгенерировать полностью случайного.", inline=False)
    embed.add_field(name="/about", value="Показывает информацию о боте и его создателе.", inline=False)
    embed.add_field(name="/help", value="Показывает это справочное сообщение.", inline=False)
    embed.add_field(name="/update_lore", value="**[Только для администраторов]**\nСобирает лор из всех каналов, обновляет файл и перезапускает бота.", inline=False)
    embed.set_footer(text="Ваш верный помощник в мире Вальдеса.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="about", description="Показывает информацию о боте и его создателе.")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(title="О боте 'Хранитель Вальдеса'", description="Я — ассистент, созданный для помощи игрокам и администрации текстового ролевого проекта 'Вальдес'.", color=discord.Color.gold())
    embed.add_field(name="Разработчик", value="**GX**", inline=True)
    embed.add_field(name="Технологии", value="• Discord.py\n• Google Gemini API", inline=True)
    embed.set_footer(text=f"Бот запущен на сервере: {interaction.guild.name}")
    await interaction.response.send_message(embed=embed, ephemeral=False)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
