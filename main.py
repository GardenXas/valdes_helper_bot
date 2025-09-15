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

IMAGE_CACHE_DIR = "image_cache"

if not all([DISCORD_TOKEN, GEMINI_API_KEY, MAIN_GUILD_ID, ADMIN_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID, LORE_CHANNEL_IDS]):
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Один из ключей или ID не найден в .env")

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- 2. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И ФУНКЦИИ ---
VALDES_LORE = ""

def load_lore_from_file():
    global VALDES_LORE
    try:
        with open("file.txt", "r", encoding="utf-8") as f:
            VALDES_LORE = f.read()
        print("Лор успешно загружен/обновлен в память.")
    except FileNotFoundError:
        print("КРИТИЧЕСКАЯ ОШИБКА: Файл 'file.txt' не найден.")
        VALDES_LORE = "Лор не был загружен из-за отсутствия файла."

class CharacterSanitizer:
    def __init__(self, font_path):
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Файл шрифта не найден по пути: '{font_path}'.")
        try:
            font = TTFont(font_path)
            self.supported_chars = set(key for table in font['cmap'].tables if table.isUnicode() for key in table.cmap.keys())
            if not self.supported_chars: raise RuntimeError("Шрифт не содержит Unicode-совместимой таблицы символов (cmap).")
            print(f"Загружен шрифт {font_path}, найдено {len(self.supported_chars)} поддерживаемых символов.")
            whitelist = {'═', '─', '║', '│', '✅', '❌', '🔑', '⚙️', '▶️', '📝', '📜', '✨', '🚫', '⚠️', '🌟', '📔', '🧬'}
            self.supported_chars.update(ord(c) for c in "".join(whitelist))
            print(f"После добавления белого списка, всего {len(self.supported_chars)} поддерживаемых символов.")
        except Exception as e:
            raise RuntimeError(f"Не удалось обработать файл шрифта '{font_path}': {e}") from e
    def sanitize(self, text: str) -> str:
        return "".join(c if ord(c) in self.supported_chars else '?' for c in str(text))

# --- 3. СИСТЕМНЫЕ ПРОМПТЫ ---
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

def get_lore_retrieval_prompt():
    return f"""
Твоя задача — найти в базе знаний изображение, наиболее релевантное запросу пользователя.
База знаний содержит текстовые блоки и теги изображений формата `[AI_DESCRIPTION: <описание изображения от ИИ> | FILE_PATH: <путь к файлу>]`.

**Твой процесс:**
1.  Проанализируй запрос пользователя.
2.  Найди в тексте `AI_DESCRIPTION`, которое наиболее точно соответствует запросу. Контекст текста вокруг тега тоже важен.
3.  Если найдено подходящее описание, твой ответ должен быть **ТОЛЬКО** значением из `FILE_PATH`. Например: `image_cache/12345.jpg`.
4.  Если подходящего изображения нет, но ответ есть в тексте, дай развернутый текстовый ответ и в конце добавь `%%SOURCES%%Название_канала`.
5.  Если ответа нет нигде, ответь: `NO_INFO`.

**База знаний:**
---
{VALDES_LORE}
---
"""

# --- 4. ВСПОМОГАТЕЛЬНЫЙ КОД И UI ---
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

# --- 5. УПРАВЛЕНИЕ КОДОМ ДОСТУПА ---
DAILY_ACCESS_CODE, CODE_FILE = "", "code.json"
def save_daily_code(code):
    with open(CODE_FILE, 'w') as f: json.dump({'code': code, 'date': datetime.now().strftime('%Y-%m-%d')}, f)
def load_daily_code():
    global DAILY_ACCESS_CODE
    try:
        with open(CODE_FILE, 'r') as f: data = json.load(f)
        if data['date'] == datetime.now().strftime('%Y-%m-%d'):
            DAILY_ACCESS_CODE = data['code']; print(f"Загружен код: {DAILY_ACCESS_CODE}"); return
    except (FileNotFoundError, json.JSONDecodeError): pass
    DAILY_ACCESS_CODE = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    save_daily_code(DAILY_ACCESS_CODE); print(f"Сгенерирован новый код: {DAILY_ACCESS_CODE}")

# --- 6. НАСТРОЙКА БОТА И СОБЫТИЙ ---
intents = discord.Intents.default(); intents.message_content = True; intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

async def send_access_code_to_admin_channel(code: str, title: str, description: str):
    try:
        admin_channel = bot.get_channel(int(CODE_CHANNEL_ID))
        if admin_channel:
            embed = discord.Embed(title=title, description=description, color=discord.Color.gold(), timestamp=datetime.now())
            embed.add_field(name="Код", value=f"```{code}```")
            embed.set_footer(text="Код действителен до конца суток (UTC).")
            await admin_channel.send(embed=embed)
    except Exception as e: print(f"Ошибка при отправке кода: {e}")

@tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))
async def update_code_task():
    load_daily_code()
    await send_access_code_to_admin_channel(DAILY_ACCESS_CODE, "🔑 Новый ежедневный код доступа", f"Код для `/update_lore` на следующие 24 часа:")

@update_code_task.before_loop
async def before_update_code_task(): await bot.wait_until_ready()

@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    if not os.path.exists(IMAGE_CACHE_DIR): os.makedirs(IMAGE_CACHE_DIR)
    load_lore_from_file(); load_daily_code()
    if not update_code_task.is_running(): update_code_task.start()
    await send_access_code_to_admin_channel(DAILY_ACCESS_CODE, "⚙️ Текущий код доступа (После перезапуска)", "Бот был перезапущен. Вот актуальный код на сегодня:")
    try:
        synced = await bot.tree.sync(); print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e: print(f"Ошибка синхронизации: {e}")

def robust_markdown_to_html(text: str) -> str:
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'__(.+?)__', r'<u>\1</u>', text)
    return text.replace('\n', '<br/>')

# --- 7. КОМАНДЫ БОТА ---

@bot.tree.command(name="update_lore", description="[АДМИН] Индексирует лор и изображения с помощью ИИ.")
@app_commands.describe(access_code="Ежедневный код доступа")
async def update_lore(interaction: discord.Interaction, access_code: str):
    if not (str(interaction.user.id) == OWNER_USER_ID or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("❌ **Ошибка доступа:** Только для администраторов.", ephemeral=True)
    if str(interaction.guild.id) != MAIN_GUILD_ID:
        return await interaction.response.send_message("❌ **Ошибка доступа:** Команда запрещена на этом сервере.", ephemeral=True)
    if access_code != DAILY_ACCESS_CODE:
        return await interaction.response.send_message("❌ **Неверный код доступа.**", ephemeral=True)
        
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    try: channel_ids = [int(id.strip()) for id in LORE_CHANNEL_IDS.split(',')]
    except ValueError: return await interaction.followup.send("❌ **Ошибка конфигурации:** LORE_CHANNEL_IDS в .env содержит нечисловые значения.", ephemeral=True)
    
    if os.path.exists(IMAGE_CACHE_DIR):
        for f in os.listdir(IMAGE_CACHE_DIR): os.remove(os.path.join(IMAGE_CACHE_DIR, f))
        print("Старый кэш изображений очищен.")
    
    pdf, sanitizer = FPDF(), None
    try:
        font_path = 'GalindoCyrillic-Regular.ttf'
        sanitizer = CharacterSanitizer(font_path)
        pdf.add_font('Galindo', '', font_path)
        pdf.add_font('Galindo', 'B', font_path)
        pdf.add_font('Galindo', 'I', font_path)
        pdf.add_font('Galindo', 'BI', font_path)
    except Exception as e: return await interaction.followup.send(f"❌ **Критическая ошибка со шрифтом:**\n{e}", ephemeral=True)
    
    pdf.set_font('Galindo', '', 12)
    full_lore_text_for_memory = ""
    parsed_channels_count, total_messages_count, total_images_count = 0, 0, 0
    channels_to_parse = [bot.get_channel(cid) for cid in channel_ids if bot.get_channel(cid)]
    sorted_channels = sorted(channels_to_parse, key=lambda c: c.position)

    async with aiohttp.ClientSession() as session:
        async def index_image_with_ai(image_bytes: bytes, message: discord.Message):
            nonlocal full_lore_text_for_memory, total_images_count
            try:
                await interaction.edit_original_response(content=f"Анализирую изображение из сообщения {message.jump_url}...")
                img = Image.open(io.BytesIO(image_bytes))
                
                prompt = "Опиши это изображение одним-двумя предложениями для поискового индекса. Сосредоточься на ключевых объектах, именах и названиях. Будь краток."
                response = await gemini_model.generate_content_async([prompt, img])
                ai_description = response.text.strip().replace('\n', ' ')

                filename = f"{message.id}.jpg"
                filepath = os.path.join(IMAGE_CACHE_DIR, filename)
                if img.mode in ('RGBA', 'P', 'LA'): img = img.convert('RGB')
                img.save(filepath, format='JPEG', quality=80, optimize=True)
                
                full_lore_text_for_memory += f"\n[AI_DESCRIPTION: {ai_description} | FILE_PATH: {filepath}]\n"
                
                page_width = pdf.w - pdf.l_margin - pdf.r_margin
                pdf.image(filepath, w=page_width, h=page_width * (img.height / img.width))
                pdf.ln(5)
                
                total_images_count += 1
            except Exception as e:
                print(f"Ошибка при ИИ-индексации изображения {message.id}: {e}")

        for channel in sorted_channels:
            pdf.add_page(); pdf.set_font('Galindo', 'B', 16)
            pdf.cell(0, 10, sanitizer.sanitize(f'Канал: {channel.name}'), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='C'); pdf.ln(10)
            full_lore_text_for_memory += f"\n--- НАЧАЛО КАНАЛА: {channel.name} ---\n\n"
            
            history_limit = 2000 # Лимит сообщений на канал
            async for message in channel.history(limit=history_limit, oldest_first=True):
                if message.author.bot: continue
                
                if message.content:
                    full_lore_text_for_memory += message.content + "\n\n"
                    pdf.set_font('Galindo', '', 12)
                    pdf.write_html(robust_markdown_to_html(sanitizer.sanitize(message.content)))
                    pdf.ln(5)
                
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type and attachment.content_type.startswith('image/'):
                            await index_image_with_ai(await attachment.read(), message)
                
                total_messages_count += 1

            full_lore_text_for_memory += f"--- КОНЕЦ КАНАЛА: {channel.name} ---\n"
            parsed_channels_count += 1

    try:
        pdf_output_filename = "lore.pdf"; pdf.output(pdf_output_filename)
        with open("file.txt", "w", encoding="utf-8") as f: f.write(full_lore_text_for_memory)
        load_lore_from_file()
        
        embed = discord.Embed(title="✅ Лор и изображения успешно проиндексированы!", color=discord.Color.green())
        embed.add_field(name="Обработано каналов", value=str(parsed_channels_count))
        embed.add_field(name="Собрано сообщений", value=str(total_messages_count))
        embed.add_field(name="Проиндексировано изображений", value=str(total_images_count))
        
        await interaction.edit_original_response(content="", embed=embed)

    except Exception as e:
        await interaction.edit_original_response(content=f"Критическая ошибка при записи файла: {e}")


@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.")
async def ask_lore(interaction: discord.Interaction, question: str):
    await interaction.response.defer(ephemeral=False)
    try:
        prompt_step1 = get_lore_retrieval_prompt()
        response_step1 = await gemini_model.generate_content_async([prompt_step1, f"\n\nЗапрос: {question}"])
        retrieval_result = response_step1.text.strip()

        final_answer, sources_text = "", ""
        
        if retrieval_result.startswith(IMAGE_CACHE_DIR) and os.path.exists(retrieval_result):
            image_path = retrieval_result
            await interaction.edit_original_response(content="*Хранитель знаний обращается к архиву изображений...*")
            try:
                img = Image.open(image_path)
                prompt_step2 = "Ты Хранитель знаний. Опираясь на вопрос игрока и это изображение, дай подробный и точный ответ."
                response_step2 = await gemini_model.generate_content_async([prompt_step2, f"Вопрос: {question}", img])
                final_answer = response_step2.text.strip()
            except Exception as img_e:
                final_answer = f"Нашел нужное изображение (`{image_path}`), но не смог его прочесть: {img_e}"
        elif "NO_INFO" in retrieval_result:
            final_answer = "В предоставленных архивах нет точной информации по этому вопросу."
        else:
            if "%%SOURCES%%" in retrieval_result:
                parts = retrieval_result.split("%%SOURCES%%")
                final_answer = parts[0].strip()
                sources_text = parts[1].strip()
            else:
                final_answer = retrieval_result

        embed = discord.Embed(title="📜 Ответ из архивов Вальдеса", description=final_answer, color=discord.Color.blue())
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        if sources_text: embed.add_field(name="Источники:", value=sources_text, inline=False)
        embed.set_footer(text=f"Ответил Хранитель знаний | Запросил: {interaction.user.display_name}")
        await interaction.edit_original_response(content=None, embed=embed)

    except Exception as e:
        await interaction.edit_original_response(content=f"Произошла критическая ошибка в /ask_lore: {e}")


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
        await interaction.followup.send(embed=discord.Embed(title="🚫 Произошла внутренняя ошибка", description="Не удалось обработать ваш запрос. Пожалуйста, попробуйте еще раз.", color=discord.Color.dark_red()), ephemeral=True)


@bot.tree.command(name="help", description="Показывает информацию обо всех доступных командах.")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Справка по командам", description="Вот список всех доступных команд и их описание:", color=discord.Color.blue())
    embed.add_field(name="/optimize_post", value="Улучшает ваш РП-пост. Принимает текст, уровень улучшения и опционально изображение.", inline=False)
    embed.add_field(name="/ask_lore", value="Задает вопрос Хранителю знаний по миру 'Вальдеса'. Ответ будет виден всем в канале.", inline=False)
    embed.add_field(name="/about", value="Показывает информацию о боте и его создателе.", inline=False)
    embed.add_field(name="/help", value="Показывает это справочное сообщение.", inline=False)
    embed.add_field(name="/update_lore", value="**[Только для администраторов]**\nИндексирует лор и изображения для ответов на вопросы.", inline=False)
    embed.set_footer(text="Ваш верный помощник в мире Вальдеса.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="about", description="Показывает информацию о боте и его создателе.")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(title="О боте 'Хранитель Вальдеса'", description="Я — ассистент, созданный для помощи игрокам и администрации текстового ролевого проекта 'Вальдес'.\n\nМоя главная задача — делать ваше погружение в мир более гладким и интересным, отвечая на вопросы по лору и помогая с качеством ваших постов.", color=discord.Color.gold())
    embed.add_field(name="Разработчик", value="**GX**", inline=True)
    embed.add_field(name="Технологии", value="• Discord.py\n• Google Gemini API", inline=True)
    embed.set_footer(text=f"Бот запущен на сервере: {interaction.guild.name}")
    await interaction.response.send_message(embed=embed, ephemeral=False)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
