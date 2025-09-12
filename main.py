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

# Загрузка переменных окружения из файла .env
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MAIN_GUILD_ID = os.getenv("MAIN_GUILD_ID")
ADMIN_GUILD_ID = os.getenv("ADMIN_GUILD_ID")
CODE_CHANNEL_ID = os.getenv("CODE_CHANNEL_ID")
OWNER_USER_ID = os.getenv("OWNER_USER_ID")


# Проверяем, что все ID и ключи на месте
if not all([DISCORD_TOKEN, GEMINI_API_KEY, MAIN_GUILD_ID, ADMIN_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID]):
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Один из ключей или ID (DISCORD_TOKEN, GEMINI_API_KEY, *_GUILD_ID, CODE_CHANNEL_ID, OWNER_USER_ID) не найден в .env")

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
Ты — ассистент для текстового ролевого проекта 'Вальдес'. Твоя задача — улучшить пост игрока, строго следуя его замыслу.
Вот полный свод правил и лора мира 'Вальдес':
--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---
**ЗОЛОТЫЕ ПРАВИЛА (ВАЖНЕЕ ВСЕГО): НЕ БУДЬ СОАВТОРОМ!**
Ты должен улучшать ТОЛЬКО то, что написал игрок. Строго запрещено:
1.  **НЕ ДОБАВЛЯЙ НОВЫХ ДЕЙСТВИЙ:** Если игрок встал с кровати, ты можешь описать, КАК он это сделал, но НЕЛЬЗЯ добавлять, что он пошел к двери.
2.  **НЕ ПРИДУМЫВАЙ МОТИВАЦИЮ:** Если игрок крикнул "БЛЯТЬ", ты должен передать эмоцию, а НЕ придумывать причину (голод, плохой сон).
3.  **НЕ МЕНЯЙ ДИАЛОГИ:** Если это восклицание в пустоту, НЕ добавляй собеседника.
4.  **НЕ МЕНЯЙ ПОВЕСТВОВАНИЕ (ЛИЦО):** Если пост написан от первого лица ('Я бегу'), улучшенный пост **ОБЯЗАН** оставаться от первого лица. Если от третьего ('Он бежит'), он должен оставаться от третьего. Это самое важное правило.
**ЗАДАЧА 1: ПРОВЕРКА НА ГРУБЫЕ ЛОРНЫЕ ОШИБКИ**
Ищи только фактические нарушения: современная техника (автоматы, машины), несуществующая магия для расы. Если нашел — верни ответ "ОШИБКА:" с объяснением. Мат и стиль арта ошибкой НЕ считаются.
**ЗАДАЧА 2: ОПТИМИЗАЦИЯ ПОСТА (если ошибок нет)**
Обработай пост согласно уровню '{level}', соблюдая все "Золотые Правила".
1.  **Уровень 'Минимальные правки':**
    *   Только исправь форматирование и грамматику. Мат замени на атмосферное ругательство (например, "Черт!").
    *   Ничего не добавляй.
2.  **Уровень 'Стандартная оптимизация':**
    *   Сделай то же, что и в минимальном.
    *   Добавь ОДНО короткое предложение, описывающее окружение ИЛИ эмоцию персонажа, напрямую связанную с его действием/словами.
3.  **Уровень 'Максимальная креативность':**
    *   Сделай то же, что и в стандартном.
    *   Красочно опиши **заявленное действие**, сохраняя лицо повествования. Например, "Я бегу на улицу" можно превратить в "*Срываясь с места, я выбегаю на холодную улицу, чувствуя, как ветер бьет в лицо.*"
**ФИНАЛЬНОЕ ПРАВИЛО:**
Верни ТОЛЬКО готовый текст поста или сообщение об ошибке. Никаких предисловий.
"""

def get_lore_prompt():
    """Возвращает системный промпт для ответов на вопросы по лору."""
    return f"""
Ты — Хранитель знаний мира 'Вальдес'. Твоя задача — отвечать на вопросы игроков, основываясь ИСКЛЮЧИТЕЛЬНО на предоставленном тебе тексте с лором и правилами.
**ТВОИ ПРАВИЛА:**
1.  **ИСТОЧНИК — ЗАКОН:** Используй только текст, приведенный ниже. Не добавляй никакой информации извне.
2.  **НЕ ДОДУМЫВАЙ:** Если в тексте нет прямого ответа на вопрос, честно скажи: "В предоставленных архивах нет точной информации по этому вопросу."
3.  **БУДЬ ТОЧЕН:** Давай чёткие и лаконичные ответы. Если уместно, можешь цитировать короткие фрагменты текста.
4.  **СТИЛЬ:** Отвечай уважительно, в стиле мудрого летописца.
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
        description="Код доступа для команды `/update_lore_by_name` на следующие 24 часа:"
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
@bot.tree.command(name="update_lore_by_name", description="[АДМИН] Обновляет лор и присылает файл для проверки.")
@app_commands.describe(
    category_name="Точное название категории с лорными каналами",
    exclude_names="Названия каналов для исключения, через запятую БЕЗ пробелов",
    access_code="Ежедневный код доступа для подтверждения"
)
async def update_lore_by_name(interaction: discord.Interaction, category_name: str, exclude_names: str, access_code: str):
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
    
    target_category = discord.utils.get(interaction.guild.categories, name=category_name)
    if not target_category:
        await interaction.followup.send(f"❌ **Ошибка:** Категория «{category_name}» не найдена. Проверьте точность названия.", ephemeral=True)
        return

    excluded_channel_names = {name.strip().lower() for name in exclude_names.split(',')}
    
    full_lore_text = ""
    parsed_channels_count = 0
    total_messages_count = 0
    sorted_channels = sorted(target_category.text_channels, key=lambda c: c.position)

    for channel in sorted_channels:
        if channel.name.lower() in excluded_channel_names:
            continue
        full_lore_text += f"\n--- НАЧАЛО КАНАЛА: {channel.name} ---\n\n"
        async for message in channel.history(limit=500, oldest_first=True):
            if message.content and not message.author.bot:
                full_lore_text += message.content + "\n\n"
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
        embed.add_field(name="Собрано сообщений", value=str(total_messages_count), inline=True)
        embed.add_field(name="Размер файла", value=f"{file_size:.2f} КБ", inline=True)
        
        await interaction.followup.send(
            embed=embed,
            file=discord.File("file.txt"),
            ephemeral=True
        )
        
    except Exception as e:
        await interaction.followup.send(f"Произошла критическая ошибка при записи или отправке файла: {e}", ephemeral=True)

@bot.tree.command(name="optimize_post", description="Улучшает РП-пост с помощью удобного интерфейса.")
@app_commands.describe(post_text="Текст вашего поста.", optimization_level="Выберите уровень улучшения.", image="(Опционально) Изображение для контекста.")
@app_commands.choices(optimization_level=[
    discord.app_commands.Choice(name="Минимальные правки", value="minimal"),
    discord.app_commands.Choice(name="Стандартная оптимизация", value="standard"),
    discord.app_commands.Choice(name="Максимальная креативность", value="creative"),
])
async def optimize_post(interaction: discord.Interaction, post_text: str, optimization_level: discord.app_commands.Choice[str], image: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    level_map = {"minimal": "Минимальные правки", "standard": "Стандартная оптимизация", "creative": "Максимальная креативность"}
    prompt = get_optimizer_prompt(level_map[optimization_level.value])
    content_to_send = [prompt, f"\n\nПост игрока:\n---\n{post_text}"]
    if image and image.content_type and image.content_type.startswith("image/"):
        try:
            image_bytes = await image.read()
            pil_image = Image.open(io.BytesIO(image_bytes))
            content_to_send.append(pil_image)
        except Exception as e:
            print(f"Ошибка обработки изображения: {e}")
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
        error_embed = discord.Embed(title="🚫 Произошла внутренняя ошибка", description="Не удалось обработать ваш запрос. Пожалуйста, попробуйте еще раз.", color=discord.Color.dark_red())
        await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.")
async def ask_lore(interaction: discord.Interaction, question: str):
    await interaction.response.defer(ephemeral=False)
    try:
        prompt = get_lore_prompt()
        response = await gemini_model.generate_content_async([prompt, f"\n\nВопрос игрока: {question}"])
        answer_text = response.text.strip()
        embed = discord.Embed(title="📜 Ответ из архивов Вальдеса", description=answer_text, color=discord.Color.blue())
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        embed.set_footer(text=f"Ответил Хранитель знаний | Запросил: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        error_embed = discord.Embed(title="🚫 Ошибка в архиве", description="Хранитель знаний не смог найти ответ на ваш вопрос из-за непредвиденной ошибки.", color=discord.Color.dark_red())
        await interaction.followup.send(embed=error_embed, ephemeral=True)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
