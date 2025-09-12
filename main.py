# -*- coding: utf-8 -*-

# --- 1. ИМПОРТЫ И НАЧАЛЬНАЯ НАСТРОЙКА ---
import discord
from discord import ui, app_commands
from discord.ext import commands
import google.generativeai as genai
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
from PIL import Image
import io

# Загрузка .env и настройка Gemini
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Не найдены токены в .env")

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
    # (Этот промпт не меняется)
    return f"..."

def get_lore_prompt():
    # (Этот промпт не меняется)
    return f"..."

# --- 4. ВСПОМОГАТЕЛЬНЫЙ КОД (keep_alive, UI и т.д.) ---
# (Этот блок не меняется)
app = Flask('')
@app.route('/')
def home(): return "Bot is alive and running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

class OptimizedPostModal(ui.Modal, title='Ваш улучшенный пост'):
    # ... (код модального окна не меняется)
    def __init__(self, optimized_text: str):
        super().__init__()
        self.post_content = ui.TextInput(label="Текст готов к копированию", style=discord.TextStyle.paragraph, default=optimized_text, max_length=1800)
        self.add_item(self.post_content)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Окно закрыто.", ephemeral=True, delete_after=3)

class PostView(ui.View):
    # ... (код кнопки не меняется)
    def __init__(self, optimized_text: str):
        super().__init__(timeout=300)
        self.optimized_text = optimized_text
    @ui.button(label="📝 Показать и скопировать текст", style=discord.ButtonStyle.primary)
    async def show_modal_button(self, interaction: discord.Interaction, button: ui.Button):
        modal = OptimizedPostModal(self.optimized_text)
        await interaction.response.send_modal(modal)

# --- 5. НАСТРОЙКА БОТА И КОМАНД ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True # Включи это в настройках бота на портале Discord!
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Бот {bot.user} успешно запущен!')
    load_lore_from_file() # Загружаем лор при старте
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

# --- НОВАЯ УДОБНАЯ КОМАНДА ДЛЯ ОБНОВЛЕНИЯ ЛОРА ---

@bot.tree.command(name="update_lore_by_name", description="[АДМИН] Собирает лор по ИМЕНАМ каналов и обновляет file.txt")
@app_commands.describe(
    category_name="Точное название категории с лорными каналами",
    exclude_names="Названия каналов для исключения, через запятую БЕЗ пробелов"
)
@app_commands.checks.has_permissions(administrator=True) # Только для админов
async def update_lore_by_name(interaction: discord.Interaction, category_name: str, exclude_names: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    # Ищем категорию по имени
    target_category = discord.utils.get(interaction.guild.categories, name=category_name)
    
    if not target_category:
        await interaction.followup.send(f"❌ **Ошибка:** Категория с названием «{category_name}» не найдена. Проверьте, что имя введено в точности как на сервере.", ephemeral=True)
        return

    # Создаем список имен для исключения, приводим к нижнему регистру для удобства
    excluded_channel_names = {name.strip().lower() for name in exclude_names.split(',')}
    
    full_lore_text = ""
    parsed_channels_count = 0
    total_messages_count = 0

    # Сортируем каналы по их позиции в Discord
    sorted_channels = sorted(target_category.text_channels, key=lambda c: c.position)

    for channel in sorted_channels:
        # Проверяем, не находится ли канал в списке исключений
        if channel.name.lower() in excluded_channel_names:
            continue

        full_lore_text += f"\n--- НАЧАЛО КАНАЛА: {channel.name} ---\n\n"
        
        # Читаем историю от самых старых сообщений к самым новым
        async for message in channel.history(limit=500, oldest_first=True):
            if message.content and not message.author.bot: # Добавляем только текст от людей
                full_lore_text += message.content + "\n\n"
                total_messages_count += 1
        
        full_lore_text += f"--- КОНЕЦ КАНАЛА: {channel.name} ---\n"
        parsed_channels_count += 1

    try:
        # Перезаписываем файл на сервере
        with open("file.txt", "w", encoding="utf-8") as f:
            f.write(full_lore_text)

        # Перезагружаем лор в память бота, чтобы он сразу начал его использовать
        load_lore_from_file()

        file_size = os.path.getsize("file.txt") / 1024 # Размер в КБ

        embed = discord.Embed(
            title="✅ Лор успешно обновлен!",
            description="Файл `file.txt` на сервере был перезаписан свежей информацией.",
            color=discord.Color.green()
        )
        embed.add_field(name="Обработано каналов", value=str(parsed_channels_count), inline=True)
        embed.add_field(name="Собрано сообщений", value=str(total_messages_count), inline=True)
        embed.add_field(name="Размер файла", value=f"{file_size:.2f} КБ", inline=True)
        embed.set_footer(text="Бот теперь использует актуальную версию лора.")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"Произошла критическая ошибка при записи файла: {e}", ephemeral=True)


# --- ТВОИ СТАРЫЕ КОМАНДЫ (остаются без изменений) ---
# ... (здесь идут твои команды /optimize_post и /ask_lore без каких-либо изменений) ...
@bot.tree.command(name="optimize_post", description="Улучшает РП-пост с помощью удобного интерфейса.")
@app_commands.describe(post_text="Текст вашего поста для улучшения.", optimization_level="Выберите, насколько сильно нужно улучшать пост.", image="(Опционально) Прикрепите изображение для контекста.")
@app_commands.choices(optimization_level=[discord.app_commands.Choice(name="Минимальные правки", value="minimal"), discord.app_commands.Choice(name="Стандартная оптимизация", value="standard"), discord.app_commands.Choice(name="Максимальная креативность", value="creative")])
async def optimize_post(interaction: discord.Interaction, post_text: str, optimization_level: discord.app_commands.Choice[str], image: discord.Attachment = None):
    # ... (твой код здесь)
    await interaction.response.defer(ephemeral=True, thinking=True)
    level_map = {"minimal": "Минимальные правки", "standard": "Стандартная оптимизация", "creative": "Максимальная креативность"}
    prompt = get_optimizer_prompt(level_map[optimization_level.value])
    content_to_send = [prompt, f"\n\nПост игрока:\n---\n{post_text}"]
    if image and image.content_type and image.content_type.startswith("image/"):
        image_bytes = await image.read()
        pil_image = Image.open(io.BytesIO(image_bytes))
        content_to_send.append(pil_image)
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
            embed.set_footer(text=f"Нажмите кнопку ниже, чтобы получить полный текст.")
            view = PostView(result_text)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        error_embed = discord.Embed(title="🚫 Произошла внутренняя ошибка", description="Не удалось обработать ваш запрос.", color=discord.Color.dark_red())
        await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.")
async def ask_lore(interaction: discord.Interaction, question: str):
    # ... (твой код здесь)
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
        error_embed = discord.Embed(title="🚫 Ошибка в архиве", description="Хранитель знаний не смог найти ответ.", color=discord.Color.dark_red())
        await interaction.followup.send(embed=error_embed, ephemeral=True)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive()
    bot.run(DISCORD_TOKEN)
