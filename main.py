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
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import re
import aiohttp
from fontTools.ttLib import TTFont

# --- НАСТРОЙКА ПЕРЕМЕННЫХ ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAIN_GUILD_ID = os.getenv("MAIN_GUILD_ID")
ADMIN_GUILD_ID = os.getenv("ADMIN_GUILD_ID")
CODE_CHANNEL_ID = os.getenv("CODE_CHANNEL_ID")
OWNER_USER_ID = os.getenv("OWNER_USER_ID")
LORE_CHANNEL_IDS = os.getenv("LORE_CHANNEL_IDS")

# <<<--- НОВОЕ: Пути к файлам вынесены в константы
LORE_PDF_PATH = "lore.pdf"
IMAGE_MAP_PATH = "image_map.json"
# --- НОВОЕ --->

if not all([DISCORD_TOKEN, GEMINI_API_KEY, MAIN_GUILD_ID, ADMIN_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID, LORE_CHANNEL_IDS]):
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Один из ключей или ID не найден в .env")

try:
    CODE_CHANNEL_ID = int(CODE_CHANNEL_ID)
    OWNER_USER_ID = int(OWNER_USER_ID)
except ValueError:
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: CODE_CHANNEL_ID и OWNER_USER_ID должны быть числами.")

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- 2. ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ И ФУНКЦИИ ---
class CharacterSanitizer:
    def __init__(self, font_path):
        if not os.path.exists(font_path): raise FileNotFoundError(f"Файл шрифта не найден: '{font_path}'.")
        try:
            font = TTFont(font_path)
            self.supported_chars = set(key for table in font['cmap'].tables if table.isUnicode() for key in table.cmap.keys())
            if not self.supported_chars: raise RuntimeError("Шрифт не содержит Unicode-совместимой таблицы символов.")
            whitelist = {'═', '─', '║', '│', '✅', '❌', '🔑', '⚙️', '▶️', '📝', '📜', '✨', '🚫', '⚠️', '🌟', '📔', '🧬', '[', ']', ':', '_'}
            self.supported_chars.update(ord(c) for c in "".join(whitelist))
        except Exception as e:
            raise RuntimeError(f"Не удалось обработать файл шрифта '{font_path}': {e}") from e
    def sanitize(self, text: str) -> str:
        return "".join(c if ord(c) in self.supported_chars else '?' for c in str(text))

def get_optimizer_prompt(level):
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

# <<<--- НОВОЕ: Полностью новый промпт для Хранителя
def get_lore_prompt():
    return """
Ты — Хранитель знаний мира 'Вальдес'. Тебе предоставлен PDF-документ, содержащий весь лор проекта.

**Твоя главная задача:** Дать максимально точный и полный ответ на вопрос игрока, основываясь на тексте из документа.

---
**КЛЮЧЕВЫЕ ПРАВИЛА АНАЛИЗА И ОТВЕТА:**

1.  **НАЙДИ РЕЛЕВАНТНЫЙ ТЕКСТ:** Внимательно изучи весь документ и найди фрагмент текста, который лучше всего отвечает на вопрос игрока.

2.  **РАБОТА С ТЕГАМИ ИЗОБРАЖЕНИЙ:**
    *   В документе некоторые блоки текста содержат специальный тег для изображений, например: `[ref_img: 112233445566778899]`.
    *   Этот тег — не для тебя, а для бота. Он означает, что к данному тексту прикреплена картинка.
    *   Если найденный тобой текст содержит такой тег, ты **ОБЯЗАН** включить его в свой ответ **БЕЗ ИЗМЕНЕНИЙ**, в том же виде.

3.  **ССЫЛАЙСЯ НА ИСТОЧНИК:** В документе каждый фрагмент информации предваряется строкой вида `Источник: Канал 'Название канала'`. В своем ответе ты **ОБЯЗАН** указать, из какого канала была взята информация. Пример: "Согласно информации из канала 'Королевства', ..."

4.  **БУДЬ ЧЕСТНЫМ:** Если в документе действительно нет ответа на вопрос, честно скажи об этом. Не выдумывай информацию.

**Пример твоего идеального ответа (если был задан вопрос о Федерации Джура):**

"Согласно информации из канала 'Королевства', Федерация Джура — это страна, обитающая на востоке. Она является самой молодой из всех стран. [ref_img: 998877665544332211]"
"""
# --- НОВОЕ --->

def robust_markdown_to_html(text: str) -> str:
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'__(.+?)__', r'<u>\1</u>', text)
    return text.replace('\n', '<br/>')

app = Flask('')
@app.route('/')
def home(): return "Bot is alive and running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

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

DAILY_ACCESS_CODE, CODE_FILE = "", "code.json"
def save_daily_code(code):
    with open(CODE_FILE, 'w') as f: json.dump({'code': code, 'date': datetime.now().strftime('%Y-%m-%d')}, f)

def load_daily_code():
    global DAILY_ACCESS_CODE
    try:
        with open(CODE_FILE, 'r') as f: data = json.load(f)
        if data['date'] == datetime.now().strftime('%Y-%m-%d'):
            DAILY_ACCESS_CODE = data['code']; print(f"Загружен код на сегодня: {DAILY_ACCESS_CODE}"); return
    except (FileNotFoundError, json.JSONDecodeError): pass
    DAILY_ACCESS_CODE = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8)); save_daily_code(DAILY_ACCESS_CODE); print(f"Сгенерирован новый стартовый код: {DAILY_ACCESS_CODE}")

intents = discord.Intents.default(); intents.message_content = True; intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- 3. ОСНОВНЫЕ КОМАНДЫ И СОБЫТИЯ БОТА ---
@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!');
    load_daily_code()
    send_daily_code_task.start()
    try:
        synced = await bot.tree.sync(); print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e: print(f"Ошибка синхронизации: {e}")

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        seconds = int(error.retry_after)
        minutes = seconds // 60
        seconds %= 60
        
        cooldown_message = f"⏳ Эта команда на перезарядке. Попробуйте снова через "
        if minutes > 0:
            cooldown_message += f"{minutes} мин. "
        if seconds > 0:
            cooldown_message += f"{seconds} сек."

        await interaction.response.send_message(cooldown_message, ephemeral=True)
    else:
        print(f"Необработанная ошибка в slash-команде: {error}")
        try:
            await interaction.response.send_message("Произошла неизвестная ошибка при выполнении команды.", ephemeral=True)
        except discord.errors.InteractionResponded:
            await interaction.followup.send("Произошла неизвестная ошибка при выполнении команды.", ephemeral=True)

SCHEDULED_TIME = time(hour=4, minute=0, tzinfo=timezone.utc)

@tasks.loop(time=SCHEDULED_TIME)
async def send_daily_code_task():
    global DAILY_ACCESS_CODE
    DAILY_ACCESS_CODE = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    save_daily_code(DAILY_ACCESS_CODE)
    print(f"Сгенерирован и сохранен новый ежедневный код: {DAILY_ACCESS_CODE}")
    try:
        channel = bot.get_channel(CODE_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="🔑 Ежедневный код доступа",
                description="Новый код для команды `/update_lore` на сегодня:",
                color=discord.Color.dark_blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Код", value=f"```{DAILY_ACCESS_CODE}```")
            embed.set_footer(text="Этот код действителен 24 часа.")
            await channel.send(embed=embed)
            print(f"Ежедневный код успешно отправлен в канал '{channel.name}'.")
        else:
            print(f"КРИТИЧЕСКАЯ ОШИБКА: Канал для кода с ID {CODE_CHANNEL_ID} не найден.")
    except Exception as e:
        print(f"Произошла ошибка при отправке ежедневного кода: {e}")

@send_daily_code_task.before_loop
async def before_send_daily_code_task():
    await bot.wait_until_ready()
    print("Цикл отправки ежедневного кода готов к запуску.")

# <<<--- НОВОЕ: Полностью переписанная команда update_lore
@bot.tree.command(name="update_lore", description="[АДМИН] Собирает лор в PDF, создает карту изображений и отправляет вам.")
@app_commands.describe(access_code="Ежедневный код доступа")
async def update_lore(interaction: discord.Interaction, access_code: str):
    if not (interaction.user.id == OWNER_USER_ID or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("❌ **Ошибка доступа:** Только для администраторов.", ephemeral=True)
    if access_code != DAILY_ACCESS_CODE:
        return await interaction.response.send_message("❌ **Неверный код доступа.**", ephemeral=True)
        
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    try: channel_ids = [int(id.strip()) for id in LORE_CHANNEL_IDS.split(',')]
    except ValueError: return await interaction.followup.send("❌ Ошибка конфигурации: LORE_CHANNEL_IDS.", ephemeral=True)
    
    pdf, sanitizer = FPDF(), None
    try:
        font_path = 'GalindoCyrillic-Regular.ttf'
        sanitizer = CharacterSanitizer(font_path)
        pdf.add_font('Galindo', '', font_path)
        pdf.add_font('Galindo', 'B', font_path)
        pdf.add_font('Galindo', 'I', font_path)
        pdf.add_font('Galindo', 'BI', font_path)
    except Exception as e: return await interaction.followup.send(f"❌ **Критическая ошибка со шрифтом:**\n{e}", ephemeral=True)
    
    total_messages_count, total_images_count = 0, 0
    image_map = {} # Словарь для хранения ID сообщений и URL их изображений
    
    channels_to_parse = [bot.get_channel(cid) for cid in channel_ids if bot.get_channel(cid)]
    sorted_channels = sorted(channels_to_parse, key=lambda c: c.position)

    async with aiohttp.ClientSession() as session:
        async def process_message(message: discord.Message):
            nonlocal total_messages_count, total_images_count, image_map
            
            # --- Собираем все URL изображений из сообщения ---
            image_urls = []
            if message.attachments:
                image_urls.extend(att.url for att in message.attachments if att.content_type and att.content_type.startswith('image/'))
            if message.embeds:
                image_urls.extend(embed.image.url for embed in message.embeds if embed.image.url)

            # --- Пропускаем сообщение, если в нем нет ни текста, ни картинок ---
            if not message.content and not image_urls:
                return

            if message.author.bot: return

            # --- Заголовок с каналом ---
            pdf.set_fill_color(240, 240, 240)
            pdf.set_font('Galindo', 'I', 8)
            channel_name = message.channel.name if hasattr(message.channel, 'name') else "Неизвестный тред"
            sanitized_channel_name = sanitizer.sanitize(f"Источник: Канал '{channel_name}'")
            pdf.cell(0, 5, sanitized_channel_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L', fill=True)
            pdf.ln(2)
            
            # --- Обработка текста сообщения ---
            if message.content:
                pdf.set_font('Galindo', '', 12)
                sanitized_content = sanitizer.sanitize(message.content)
                pdf.write_html(robust_markdown_to_html(sanitized_content))
                pdf.ln(1) # Уменьшаем отступ
            
            # --- Если есть изображения, сохраняем их и вставляем тег в PDF ---
            if image_urls:
                image_map[str(message.id)] = image_urls
                pdf.set_font('Galindo', 'I', 9)
                pdf.set_text_color(150, 150, 150)
                pdf.cell(0, 5, sanitizer.sanitize(f"[ref_img: {message.id}]"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(0, 0, 0)
                total_images_count += len(image_urls)
            
            pdf.ln(4) # Отступ после всего сообщения
            total_messages_count += 1

        for channel in sorted_channels:
            if not channel:
                print(f"ПРЕДУПРЕЖДЕНИЕ: Канал из LORE_CHANNEL_IDS не найден.")
                continue
            pdf.add_page(); pdf.set_font('Galindo', 'B', 16)
            pdf.cell(0, 10, sanitizer.sanitize(f'Сборник Лора: {channel.name}'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C'); pdf.ln(10)
            
            if isinstance(channel, discord.ForumChannel):
                all_threads = channel.threads + [t async for t in channel.archived_threads(limit=None)]
                for thread in sorted(all_threads, key=lambda t: t.created_at):
                    pdf.set_font('Galindo', 'B', 14)
                    pdf.cell(0, 10, sanitizer.sanitize(f"Тема: {thread.name}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L'); pdf.ln(5)
                    async for message in thread.history(limit=500, oldest_first=True): await process_message(message)
            else:
                async for message in channel.history(limit=2000, oldest_first=True): await process_message(message)

    try:
        # --- Сохраняем PDF и карту изображений ---
        pdf.output(LORE_PDF_PATH)
        with open(IMAGE_MAP_PATH, 'w', encoding='utf-8') as f:
            json.dump(image_map, f, ensure_ascii=False, indent=4)
        
        pdf_size_mb = os.path.getsize(LORE_PDF_PATH) / (1024 * 1024)
        
        embed = discord.Embed(title="✅ Лор успешно собран!", color=discord.Color.green())
        embed.description = "Создан `lore.pdf` и `image_map.json`."
        embed.add_field(name="Обработано сообщений", value=str(total_messages_count))
        embed.add_field(name="Найдено изображений", value=str(total_images_count))
        embed.add_field(name="Размер PDF", value=f"{pdf_size_mb:.2f} МБ")
        
        if pdf_size_mb < 8.0:
            await interaction.followup.send(embed=embed, file=discord.File(LORE_PDF_PATH), ephemeral=True)
        else:
            embed.description += "\n⚠️ **Файл PDF слишком большой (>8 МБ).** Он сохранен, но не может быть отправлен в Discord."
            await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"Критическая ошибка при записи или отправке файла: {e}", ephemeral=True)
# --- НОВОЕ --->

# <<<--- НОВОЕ: Полностью переписанная команда ask_lore
@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.")
@app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id)
async def ask_lore(interaction: discord.Interaction, question: str):
    await interaction.response.defer(ephemeral=False, thinking=True)
    
    if not os.path.exists(LORE_PDF_PATH):
        return await interaction.followup.send("❌ **Ошибка:** Файл лора (`lore.pdf`) не найден. Попросите администратора сгенерировать его командой `/update_lore`.")
    if not os.path.exists(IMAGE_MAP_PATH):
        return await interaction.followup.send("❌ **Ошибка:** Файл карты изображений (`image_map.json`) не найден. Запустите `/update_lore`.")

    lore_file = None
    try:
        # --- Загружаем карту изображений ---
        with open(IMAGE_MAP_PATH, 'r', encoding='utf-8') as f:
            image_map = json.load(f)

        await interaction.edit_original_response(content="*Хранитель знаний загружает архивы...*")
        lore_file = genai.upload_file(path=LORE_PDF_PATH, display_name="Архив Вальдеса")
        
        await interaction.edit_original_response(content="*Ищу ответ в архивах...*")
        prompt = get_lore_prompt()
        response = await gemini_model.generate_content_async([prompt, lore_file, f"Вопрос игрока: {question}"])
        
        raw_text = response.text
        
        # --- Ищем теги изображений в ответе ИИ ---
        image_ids = re.findall(r'\[ref_img: (\d+)]', raw_text)
        
        # --- Очищаем текст от тегов для пользователя ---
        clean_text = re.sub(r'\s*\[ref_img: \d+]', '', raw_text).strip()

        embed = discord.Embed(title="📜 Ответ из архивов Вальдеса", description=clean_text, color=discord.Color.blue())
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        embed.set_footer(text=f"Ответил Хранитель знаний | Запросил: {interaction.user.display_name}")

        # --- Если найдены ID изображений, прикрепляем первое из них ---
        if image_ids:
            first_id = image_ids[0]
            if first_id in image_map and image_map[first_id]:
                first_image_url = image_map[first_id][0]
                embed.set_image(url=first_image_url)
                print(f"Прикреплено изображение: {first_image_url}")

        await interaction.edit_original_response(content=None, embed=embed)

    except Exception as e:
        await interaction.edit_original_response(content=f"Произошла критическая ошибка в /ask_lore: {e}")
    finally:
        if lore_file:
            await asyncio.sleep(1) 
            try:
                genai.delete_file(lore_file.name)
                print(f"Загруженный файл {lore_file.name} удален с сервера.")
            except Exception as e:
                print(f"Не удалось удалить файл {lore_file.name} с сервера: {e}")
# --- НОВОЕ --->


@bot.tree.command(name="optimize_post", description="Улучшает РП-пост.")
@app_commands.describe(post_text="Текст вашего поста для улучшения.", optimization_level="Выберите желаемый уровень улучшения.", image="(Опционально) Изображение для дополнительного контекста.")
@app_commands.choices(optimization_level=[
    discord.app_commands.Choice(name="Минимальные правки", value="minimal"),
    discord.app_commands.Choice(name="Стандартная оптимизация", value="standard"),
    discord.app_commands.Choice(name="Максимальная креативность", value="creative"),
])
@app_commands.checks.cooldown(1, 120.0, key=lambda i: i.user.id)
async def optimize_post(interaction: discord.Interaction, post_text: str, optimization_level: discord.app_commands.Choice[str], image: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if image and (not image.content_type or not image.content_type.startswith("image/")):
        return await interaction.followup.send("❌ **Ошибка:** Прикрепленный файл не является изображением.", ephemeral=True)

    level_map = {"minimal": "Минимальные правки", "standard": "Стандартная оптимизация", "creative": "Максимальная креативность"}
    prompt = get_optimizer_prompt(level_map[optimization_level.value])
    content_to_send = [prompt, f"\n\nПост игрока:\n---\n{post_text}"]
    
    if image:
        try:
            content_to_send.append(Image.open(io.BytesIO(await image.read())))
        except Exception as e:
            print(f"Ошибка обработки изображения: {e}")
            await interaction.followup.send("⚠️ Не удалось обработать изображение, улучшаю текст без него.", ephemeral=True)

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
            await interaction.followup.send(embed=embed, view=PostView(result_text), ephemeral=True)
    except Exception as e:
        print(f"Ошибка в /optimize_post: {e}")
        await interaction.followup.send(embed=discord.Embed(title="🚫 Произошла внутренняя ошибка", description="Не удалось обработать ваш запрос.", color=discord.Color.dark_red()), ephemeral=True)


@bot.tree.command(name="help", description="Показывает информацию обо всех доступных командах.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Справка по командам", description="Вот список всех доступных команд и их описание:", color=discord.Color.blue())
    embed.add_field(name="/optimize_post", value="Улучшает ваш РП-пост (перезарядка 2 мин.).", inline=False)
    embed.add_field(name="/ask_lore", value="Задает вопрос Хранителю знаний (перезарядка 1 мин.).", inline=False)
    embed.add_field(name="/about", value="Показывает информацию о боте и его создателе.", inline=False)
    embed.add_field(name="/help", value="Показывает это справочное сообщение.", inline=False)
    embed.add_field(name="/update_lore", value="**[АДМИН]** Собирает весь лор в PDF, создает карту изображений и отправляет его вам.", inline=False)
    embed.set_footer(text="Ваш верный помощник в мире Вальдеса.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="about", description="Показывает информацию о боте и его создателе.")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(title="О боте 'Хранитель Вальдеса'", description="Я — ассистент, созданный для помощи игрокам и администрации проекта 'Вальдес'.", color=discord.Color.gold())
    embed.add_field(name="Разработчик", value="**GX**", inline=True)
    embed.add_field(name="Технологии", value="• Discord.py\n• Google Gemini API", inline=True)
    embed.set_footer(text=f"Бот запущен на сервере: {interaction.guild.name}")
    await interaction.response.send_message(embed=embed, ephemeral=False)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)

