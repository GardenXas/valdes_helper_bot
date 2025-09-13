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

# --- 3. СИСТЕМНЫЕ ПРОМПТЫ ---
def get_optimizer_prompt(level):
    """Возвращает системный промпт для оптимизации РП-постов."""
    return f"""
Ты — ассистент для текстового ролевого проекта 'Вальдес'. Твоя задача — улучшить пост игрока, строго следуя правилам оформления и замыслу.
Вот полный свод правил и лора мира 'Вальдес':
--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---

**КЛЮЧЕВЫЕ ПРАВИЛА ОФОРМЛЕНИЯ ПОСТА (САМОЕ ВАЖНОЕ):**
1.  **ДЕЙСТВИЯ:** Все действия персонажа должны быть заключены в двойные звездочки. Пример: `**Он поднялся с кровати и подошел к окну.**`
2.  **МЫСЛИ:** Все мысли персонажа должны быть заключены в обычные кавычки. Пример: `"Какой сегодня прекрасный день."`
3.  **РЕЧЬ:** Вся прямая речь персонажа должна начинаться с дефиса и пробела. Пример: `- Доброе утро.`
4.  Каждый тип (действие, мысль, речь) должен, по возможности, начинаться с новой строки.

**ЗОЛОТЫЕ ПРАВИЛА ОБРАБОТКИ:**
1.  **ПОВЕСТВОВАНИЕ ОТ ТРЕТЬЕГО ЛИЦА:** Все действия персонажа должны быть написаны от **третьего лица** (Он/Она делает), даже если игрок написал от первого ('Я делаю'). Это правило обязательно для всех уровней оптимизации.
2.  **НЕ БУДЬ СОАВТОРОМ:** Ты должен улучшать ТОЛЬКО то, что написал игрок. Строго запрещено добавлять новые действия или придумывать мотивацию, которой не было в исходном тексте.
3.  **ДИАЛОГИ И МЫСЛИ:** Не меняй смысл мыслей и прямой речи.

**ЗАДАЧА 1: ПРОВЕРКА НА ГРУБЫЕ ЛОРНЫЕ ОШИБКИ**
Ищи только фактические нарушения: современная техника (автоматы), несуществующая магия. Если нашел — верни ответ "ОШИБКА:" с объяснением.

**ЗАДАЧА 2: ОПТИМИЗАЦИЯ ПОСТА (если ошибок нет)**
Обработай пост согласно уровню '{level}', соблюдая все 'КЛЮЧЕВЫЕ ПРАВИЛА ОФОРМЛЕНИЯ' и 'ЗОЛОТЫЕ ПРАВИЛА ОБРАБОТКИ'.

*   **Уровень 'Минимальные правки':**
    *   Твоя единственная задача — взять текст игрока и переформатировать его согласно **'КЛЮЧЕВЫМ ПРАВИЛАМ ОФОРМЛЕНИЯ ПОСТА'**.
    *   Переведи действия в третье лицо.
    *   **ЗАПРЕЩЕНО** добавлять, убирать или изменять слова, кроме необходимых для смены лица повествования (я -> он/она). Только форматирование.

*   **Уровень 'Стандартная оптимизация':**
    *   Выполни все требования 'Минимальных правок'.
    *   Исправь грамматические и орфографические ошибки.
    *   Можешь добавить **ОДНО** короткое предложение, описывающее эмоцию или деталь окружения, напрямую связанную с действием.

*   **Уровень 'Максимальная креативность':**
    *   Выполни все требования 'Стандартной оптимизации'.
    *   Художественно обогати описание **заявленных игроком действий**. Например, "Он идет на улицу" можно превратить в "**Тяжело ступая, он выходит на залитую солнцем улицу, щурясь от яркого света.**"

**ФИНАЛЬНОЕ ПРАВИЛО:**
Верни ТОЛЬКО готовый текст поста или сообщение об ошибке. Никаких предисловий или комментариев.
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

# --- 4. ВСПОМОГАТЕЛЬНЫЙ КОД (keep_alive, UI, работа с кодом доступа) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive and running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

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

# --- 6. УНИВЕРСАЛЬНАЯ ФУНКЦИЯ И ЕЖЕДНЕВНАЯ ЗАДАЧА ГЕНЕРАЦИИ КОДА ---
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

@bot.tree.command(name="update_lore", description="[АДМИН] Собирает лор из заданных каналов и обновляет файл.")
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

    full_lore_text = ""
    parsed_channels_count = 0
    total_messages_count = 0
    
    channels_to_parse = []
    for channel_id in channel_ids:
        channel = bot.get_channel(channel_id)
        if channel and (isinstance(channel, discord.TextChannel) or isinstance(channel, discord.ForumChannel)):
            channels_to_parse.append(channel)
        else:
            print(f"Предупреждение: Канал с ID {channel_id} не найден или его тип не поддерживается.")

    sorted_channels = sorted(channels_to_parse, key=lambda c: c.position)

    for channel in sorted_channels:
        full_lore_text += f"\n--- НАЧАЛО КАНАЛА: {channel.name} ---\n\n"
        
        if isinstance(channel, discord.ForumChannel):
            sorted_threads = sorted(channel.threads, key=lambda t: t.created_at)
            for thread in sorted_threads:
                try:
                    starter_message = await thread.fetch_message(thread.id)
                    if starter_message:
                        full_lore_text += f"--- Начало публикации: {thread.name} ---\n\n"
                        content_found = False
                        if starter_message.content:
                            full_lore_text += starter_message.content + "\n\n"
                            content_found = True
                        if starter_message.embeds:
                            for embed in starter_message.embeds:
                                if embed.title: full_lore_text += f"**{embed.title}**\n"
                                if embed.description: full_lore_text += embed.description + "\n"
                                for field in embed.fields: full_lore_text += f"**{field.name}**\n{field.value}\n"
                                full_lore_text += "\n"
                            content_found = True
                        if content_found: total_messages_count += 1
                        full_lore_text += f"--- Конец публикации: {thread.name} ---\n\n"
                except discord.NotFound:
                    print(f"Не удалось найти стартовое сообщение для ветки '{thread.name}' (ID: {thread.id})")
                except Exception as e:
                    print(f"Ошибка при обработке ветки '{thread.name}': {e}")
        
        else:
            async for message in channel.history(limit=500, oldest_first=True):
                content_found = False
                if message.content:
                    full_lore_text += message.content + "\n\n"
                    content_found = True
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title: full_lore_text += f"**{embed.title}**\n"
                        if embed.description: full_lore_text += embed.description + "\n"
                        for field in embed.fields: full_lore_text += f"**{field.name}**\n{field.value}\n"
                        full_lore_text += "\n"
                    content_found = True
                if content_found:
                    total_messages_count += 1

        full_lore_text += f"--- КОНЕЦ КАНАЛА: {channel.name} ---\n"
        parsed_channels_count += 1

    try:
        with open("file.txt", "w", encoding="utf-8") as f:
            f.write(full_lore_text)
        
        load_lore_from_file()
        file_size = os.path.getsize("file.txt") / 1024
        
        embed = discord.Embed(title="✅ Лор успешно обновлен!", description="Файл `file.txt` был перезаписан и прикреплен к этому сообщению для проверки.", color=discord.Color.green())
        embed.add_field(name="Обработано каналов", value=str(parsed_channels_count), inline=True)
        embed.add_field(name="Собрано публикаций/сообщений", value=str(total_messages_count), inline=True)
        embed.add_field(name="Размер файла", value=f"{file_size:.2f} КБ", inline=True)
        
        await interaction.followup.send(
            embed=embed,
            file=discord.File("file.txt"),
            ephemeral=True
        )

        await interaction.followup.send("✅ **Лор обновлен.** Перезапускаюсь для применения изменений через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)
        
        print("Перезапуск бота после обновления лора...")
        sys.exit()
        
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
            # Используем `post_text` для показа оригинала, чтобы он был в том виде, в котором его ввел пользователь
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
