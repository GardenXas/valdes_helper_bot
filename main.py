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

# Загрузка переменных окружения (токены)
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Проверка наличия токенов
if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("КРИТИЧЕСКАЯ ОШИБКА: Не найдены DISCORD_TOKEN или GEMINI_API_KEY в вашем .env файле.")

# Инициализация Gemini API
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')


# --- 2. ЗАГРУЗКА ЛОРА ИЗ ФАЙЛА ---
try:
    with open("file.txt", "r", encoding="utf-8") as f:
        VALDES_LORE = f.read()
except FileNotFoundError:
    print("КРИТИЧЕСКАЯ ОШИБКА: Файл с лором 'file.txt' не найден. Команды бота могут работать некорректно.")
    VALDES_LORE = "Лор не был загружен из-за отсутствия файла."


# --- 3. СИСТЕМНЫЕ ПРОМПТЫ ДЛЯ НЕЙРОСЕТИ ---

def get_optimizer_prompt(level):
    """
    Возвращает полный системный промпт для задачи улучшения РП-постов.
    """
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
Ищи только фактические нарушения: современная техника (автоматы, машины), несуществующая магия для расы.
Если нашел — верни ответ "ОШИБКА:" с объяснением. Мат и стиль арта ошибкой НЕ считаются.

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
    """
    Возвращает полный системный промпт для задачи ответов на вопросы по лору.
    """
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


# --- 4. КОД ДЛЯ ПОДДЕРЖАНИЯ РАБОТЫ БОТА 24/7 ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive and running!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()


# --- 5. ИНТЕРАКТИВНЫЕ UI ЭЛЕМЕНТЫ (ИНТЕРФЕЙС) ---

class OptimizedPostModal(ui.Modal, title='Ваш улучшенный пост'):
    """Модальное окно для удобного отображения и копирования текста."""
    def __init__(self, optimized_text: str):
        super().__init__()
        # Создаем текстовое поле внутри окна
        self.post_content = ui.TextInput(
            label="Текст готов к копированию",
            style=discord.TextStyle.paragraph,
            default=optimized_text,
            required=False,
            max_length=1800, # Максимальная длина поля
        )
        self.add_item(self.post_content)

    async def on_submit(self, interaction: discord.Interaction):
        # Эта функция нужна, чтобы у модального окна была кнопка "Отправить".
        # Фактически она просто закрывает окно.
        await interaction.response.send_message("Окно закрыто.", ephemeral=True, delete_after=3)

class PostView(ui.View):
    """Класс 'Вида', который содержит кнопку для вызова модального окна."""
    def __init__(self, optimized_text: str):
        super().__init__(timeout=300) # Кнопка будет активна 5 минут
        self.optimized_text = optimized_text

    @ui.button(label="📝 Показать и скопировать текст", style=discord.ButtonStyle.primary)
    async def show_modal_button(self, interaction: discord.Interaction, button: ui.Button):
        """При нажатии на кнопку, эта функция создает и отправляет модальное окно."""
        modal = OptimizedPostModal(self.optimized_text)
        await interaction.response.send_modal(modal)


# --- 6. ОСНОВНОЙ КОД БОТА И КОМАНДЫ ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    """Событие, которое выполняется при успешном запуске бота."""
    print(f'Бот {bot.user} успешно запущен и готов к работе!')
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"Ошибка синхронизации команд: {e}")

@bot.tree.command(name="optimize_post", description="Улучшает РП-пост с помощью удобного интерфейса.")
@app_commands.describe(
    post_text="Текст вашего поста для улучшения.",
    optimization_level="Выберите, насколько сильно нужно улучшать пост.",
    image="(Опционально) Прикрепите изображение для контекста."
)
@app_commands.choices(optimization_level=[
    discord.app_commands.Choice(name="Минимальные правки (грамматика, формат)", value="minimal"),
    discord.app_commands.Choice(name="Стандартная оптимизация (немного атмосферы)", value="standard"),
    discord.app_commands.Choice(name="Максимальная креативность (красочное описание)", value="creative"),
])
async def optimize_post(
    interaction: discord.Interaction,
    post_text: str,
    optimization_level: discord.app_commands.Choice[str],
    image: discord.Attachment = None
):
    """Основная команда для улучшения РП-постов."""
    await interaction.response.defer(ephemeral=True, thinking=True)

    level_map = {
        "minimal": "Минимальные правки",
        "standard": "Стандартная оптимизация",
        "creative": "Максимальная креативность"
    }
    prompt = get_optimizer_prompt(level_map[optimization_level.value])
    content_to_send = [prompt, f"\n\nПост игрока:\n---\n{post_text}"]

    if image:
        if image.content_type and image.content_type.startswith("image/"):
            try:
                image_bytes = await image.read()
                pil_image = Image.open(io.BytesIO(image_bytes))
                content_to_send.append(pil_image)
            except Exception as e:
                print(f"Не удалось обработать прикрепленное изображение: {e}")

    try:
        response = await gemini_model.generate_content_async(content_to_send)
        result_text = response.text.strip()

        if result_text.startswith("ОШИБКА:"):
            error_embed = discord.Embed(
                title="❌ Обнаружена грубая лорная ошибка!",
                description=result_text.replace("ОШИБКА:", "").strip(),
                color=discord.Color.red()
            )
            error_embed.set_footer(text="Пожалуйста, исправьте пост в соответствии с правилами мира 'Вальдес'.")
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="✨ Ваш пост был оптимизирован!",
                color=discord.Color.gold()
            )
            embed.add_field(name="▶️ Оригинал:", value=f"```\n{post_text[:1000]}\n```", inline=False)
            embed.add_field(name="✅ Улучшенная версия (превью):", value=f"{result_text[:1000]}...", inline=False)
            embed.set_footer(text=f"Нажмите кнопку ниже, чтобы получить полный текст для копирования.")

            view = PostView(result_text)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    except Exception as e:
        print(f"Произошла ошибка при обращении к Gemini: {e}")
        error_embed = discord.Embed(
            title="🚫 Произошла внутренняя ошибка",
            description="Не удалось обработать ваш запрос. Возможно, API временно недоступен. Пожалуйста, попробуйте еще раз через некоторое время.",
            color=discord.Color.dark_red()
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)

@bot.tree.command(name="ask_lore", description="Задать вопрос по миру, правилам и лору 'Вальдеса'")
@app_commands.describe(question="Ваш вопрос Хранителю знаний.")
async def ask_lore(interaction: discord.Interaction, question: str):
    """Команда для получения информации по лору игры."""
    await interaction.response.defer(ephemeral=False) # Ответ виден всем в канале

    try:
        prompt = get_lore_prompt()
        response = await gemini_model.generate_content_async([prompt, f"\n\nВопрос игрока: {question}"])
        answer_text = response.text.strip()

        embed = discord.Embed(
            title="📜 Ответ из архивов Вальдеса",
            description=answer_text,
            color=discord.Color.blue()
        )
        embed.add_field(name="Ваш запрос:", value=question, inline=False)
        embed.set_footer(text=f"Ответил Хранитель знаний | Запросил: {interaction.user.display_name}")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Произошла ошибка при обработке лорного вопроса: {e}")
        error_embed = discord.Embed(
            title="🚫 Ошибка в архиве",
            description="Хранитель знаний не смог найти ответ на ваш вопрос из-за непредвиденной ошибки. Попробуйте переформулировать запрос или повторить его позже.",
            color=discord.Color.dark_red()
        )
        await interaction.followup.send(embed=error_embed, ephemeral=True)


# --- 7. ЗАПУСК БОТА ---
if __name__ == "__main__":
    keep_alive() # Запускаем веб-сервер для поддержания активности (для Replit и подобных)
    bot.run(DISCORD_TOKEN)
