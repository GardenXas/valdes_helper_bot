import discord
from discord import app_commands
from discord.ext import commands
import google.generativeai as genai
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- НАСТРОЙКА И ЗАГРУЗКА ---

# Загружаем переменные окружения (ключи API) из файла .env (или из Replit Secrets)
load_dotenv()

# Проверяем, что ключи существуют
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Не найдены DISCORD_TOKEN или GEMINI_API_KEY. Убедись, что они добавлены в .env или в Secrets на Replit.")

# Настраиваем Gemini API
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# Загружаем лор из файла file.txt при старте бота один раз
try:
    with open("file.txt", "r", encoding="utf-8") as f:
        VALDES_LORE = f.read()
except FileNotFoundError:
    print("ПРЕДУПРЕЖДЕНИЕ: Файл 'file.txt' не найден. Бот будет работать без контекста лора.")
    VALDES_LORE = "Лор не был загружен."

# Формируем основной промпт для Gemini. Это "мозг" нашего бота.
SYSTEM_PROMPT = f"""
Ты — мастер-ассистент для текстового ролевого проекта 'Вальдес'. Твоя задача — помочь игроку улучшить его пост, основываясь на строгих правилах мира.

Вот полный свод правил, лора, механик и сеттинга мира 'Вальдес':
--- НАЧАЛО ДОКУМЕНТА С ЛОРОМ ---
{VALDES_LORE}
--- КОНЕЦ ДОКУМЕНТА С ЛОРОМ ---

Проанализируй и улучши следующий пост от игрока.

Твои задачи:
1.  **Форматирование:** Отформатируй текст согласно правилам РП 'Вальдес':
    *   Действия персонажа должны быть выделены курсивом (*Пример*).
    *   Мысли персонажа должны быть в двойных кавычках ("Пример").
    *   Прямая речь персонажа должна начинаться с тире (- Пример).
    *   Используй красивое форматирование (жирный, курсив) для акцентов, но не переусердствуй.

2.  **Лорная корректность:** Проверь пост на соответствие лору. Если игрок совершает ошибку (например, дварф использует магию, недоступную его расе, или упоминает несуществующий город), мягко исправь это, предложив логичную альтернативу, которая соответствует его способностям и ситуации.

3.  **Обогащение текста:** Сделай пост более "живым" и атмосферным. Добавь краткие, но ёмкие описания окружения, эмоций персонажа, запахов, звуков, основываясь на контексте поста и лоре мира. Если персонаж в Утгарде, добавь ощущение холода и запах камня. Если в Сарионе — шелест листвы и магические отблески.

4.  **Сохранение намерения:** Самое главное — сохрани оригинальный смысл и действие, которое задумал игрок. Ты не переписываешь его историю, а лишь делаешь её лучше и правильнее в рамках мира.

**Верни только готовый, улучшенный пост без лишних комментариев, объяснений или предисловий. Просто сам текст поста.**
"""

# --- КОД, ЧТОБЫ БОТ НЕ СПАЛ (ДЛЯ REPLIT) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run():
  app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
    print("Веб-сервер для поддержания активности запущен.")

# --- ИНТЕРФЕЙС БОТА В DISCORD ---

# Модальное окно (форма), которое будет появляться для ввода поста
class OptimizationModal(discord.ui.Modal, title="Оптимизация поста для 'Вальдес'"):
    post_text = discord.ui.TextInput(
        label="Ваш пост для улучшения",
        style=discord.TextStyle.paragraph,
        placeholder="Вставьте сюда свой сырой пост...",
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        original_post = self.post_text.value
        full_prompt = SYSTEM_PROMPT + f"\n\nВот пост игрока для обработки:\n---\n{original_post}"

        try:
            response = await gemini_model.generate_content_async(full_prompt)
            optimized_text = response.text

            embed = discord.Embed(
                title="✨ Ваш пост был оптимизирован!",
                color=discord.Color.gold()
            )
            # Обрезаем текст до 1024 символов, чтобы не превысить лимит Discord
            embed.add_field(name="▶️ Оригинал:", value=f"```\n{original_post[:1000]}\n```", inline=False)
            embed.add_field(name="✅ Улучшенная версия:", value=f"```\n{optimized_text[:1000]}\n```", inline=False)
            embed.set_footer(text="Скопируйте улучшенную версию из сообщения ниже.")

            await interaction.followup.send(embed=embed, ephemeral=True)
            # Отправляем чистый текст в отдельном сообщении для удобства копирования
            await interaction.followup.send(f"```{discord.utils.escape_markdown(optimized_text)}```", ephemeral=True)

        except Exception as e:
            print(f"Произошла ошибка при обращении к Gemini: {e}")
            await interaction.followup.send("Прости, что-то пошло не так. Возможно, ИИ перегружен. Попробуй еще раз.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.followup.send('Ой, что-то сломалось. Попробуй снова.', ephemeral=True)
        print(error)

# --- ОСНОВНОЙ КОД БОТА ---

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Бот {bot.user} успешно запущен и готов к работе!')
    print(f'Лор "Вальдеса" загружен. Объем: {len(VALDES_LORE)} символов.')
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

@bot.tree.command(name="optimize_post", description="Улучшить РП-пост с помощью ИИ-ассистента.")
async def optimize_post(interaction: discord.Interaction):
    await interaction.response.send_modal(OptimizationModal())

# --- ЗАПУСК БОТА И ВЕБ-СЕРВЕРА ---

# Запускаем веб-сервер, чтобы бот не "уснул" на Replit
keep_alive()
# Запускаем самого бота
bot.run(DISCORD_TOKEN)