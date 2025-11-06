"""
Сервис для сбора статистики и генерации графиков.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO

import aiosqlite
import matplotlib
import matplotlib.pyplot as plt

from database import DATABASE_NAME

# Используем Agg backend для работы без GUI
matplotlib.use("Agg")

# Русские названия дней недели
WEEKDAY_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


async def get_user_timestamps(user_id: int | None = None) -> list[datetime]:
    """
    Получает все timestamps из таблицы messages для указанного пользователя или всех пользователей.

    Args:
        user_id: ID пользователя. Если None, собирает статистику по всем пользователям.

    Returns:
        Список объектов datetime с временными метками.
    """
    timestamps = []

    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.cursor()

        if user_id is not None:
            # Получаем данные конкретного пользователя с timestamp
            sql = "SELECT timestamp FROM messages WHERE user_id = ? AND timestamp IS NOT NULL"
            await cursor.execute(sql, (user_id,))
        else:
            # Получаем данные всех пользователей с timestamp
            sql = "SELECT timestamp FROM messages WHERE timestamp IS NOT NULL"
            await cursor.execute(sql)

        rows = await cursor.fetchall()

        # Парсим timestamps
        for row in rows:
            if row[0]:
                try:
                    dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    timestamps.append(dt)
                except (ValueError, TypeError):
                    continue

    return timestamps


async def generate_hourly_stats(
    timestamps: list[datetime], user_id: int | None = None
) -> BytesIO:
    """
    Генерирует график статистики по часам суток.

    Args:
        timestamps: Список временных меток.
        user_id: ID пользователя (для заголовка).

    Returns:
        BytesIO объект с изображением графика.
    """
    # Подсчитываем количество сообщений по часам
    hourly_counts = defaultdict(int)
    for dt in timestamps:
        hourly_counts[dt.hour] += 1

    # Создаем список для всех 24 часов
    hours = list(range(24))
    counts = [hourly_counts.get(h, 0) for h in hours]

    # Создаем график
    plt.figure(figsize=(14, 6))
    bars = plt.bar(hours, counts, color="skyblue", edgecolor="navy", alpha=0.7)

    # Подсвечиваем максимальные значения
    if counts:
        max_count = max(counts)
        for bar, count in zip(bars, counts, strict=True):
            if count == max_count and count > 0:
                bar.set_color("orange")
                bar.set_edgecolor("darkred")

    plt.xlabel("Час суток", fontsize=12, weight="bold")
    plt.ylabel("Количество сообщений", fontsize=12, weight="bold")

    if user_id:
        plt.title(
            f"Активность пользователя USER{user_id} по часам суток",
            fontsize=14,
            weight="bold",
        )
    else:
        plt.title(
            "Активность всех пользователей по часам суток",
            fontsize=14,
            weight="bold",
        )

    plt.xticks(hours)
    plt.grid(axis="y", alpha=0.3, linestyle="--")
    plt.tight_layout()

    # Сохраняем в BytesIO
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close()

    return buf


async def generate_weekly_stats(
    timestamps: list[datetime], user_id: int | None = None
) -> BytesIO:
    """
    Генерирует график статистики по дням недели.

    Args:
        timestamps: Список временных меток.
        user_id: ID пользователя (для заголовка).

    Returns:
        BytesIO объект с изображением графика.
    """
    # Подсчитываем количество сообщений по дням недели
    weekly_counts = defaultdict(int)
    for dt in timestamps:
        weekly_counts[dt.weekday()] += 1

    # Создаем список для всех 7 дней недели
    weekdays = list(range(7))
    counts = [weekly_counts.get(d, 0) for d in weekdays]
    day_names = [WEEKDAY_NAMES[d] for d in weekdays]

    # Создаем график
    plt.figure(figsize=(12, 6))
    bars = plt.bar(day_names, counts, color="lightgreen", edgecolor="darkgreen", alpha=0.7)

    # Подсвечиваем максимальные значения
    if counts:
        max_count = max(counts)
        for bar, count in zip(bars, counts, strict=True):
            if count == max_count and count > 0:
                bar.set_color("gold")
                bar.set_edgecolor("darkred")

    plt.xlabel("День недели", fontsize=12, weight="bold")
    plt.ylabel("Количество сообщений", fontsize=12, weight="bold")

    if user_id:
        plt.title(
            f"Активность пользователя USER{user_id} по дням недели",
            fontsize=14,
            weight="bold",
        )
    else:
        plt.title(
            "Активность всех пользователей по дням недели",
            fontsize=14,
            weight="bold",
        )

    plt.xticks(rotation=45, ha="right")
    plt.grid(axis="y", alpha=0.3, linestyle="--")
    plt.tight_layout()

    # Сохраняем в BytesIO
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close()

    return buf


async def generate_user_stats(
    user_id: int | None = None,
) -> tuple[BytesIO, BytesIO, int]:
    """
    Генерирует статистику для пользователя (или всех пользователей).

    Args:
        user_id: ID пользователя. Если None, собирает статистику по всем пользователям.

    Returns:
        Кортеж из трех элементов:
        - BytesIO с графиком по часам
        - BytesIO с графиком по дням недели
        - Общее количество сообщений
    """
    timestamps = await get_user_timestamps(user_id)

    if not timestamps:
        return None, None, 0

    hourly_graph = await generate_hourly_stats(timestamps, user_id)
    weekly_graph = await generate_weekly_stats(timestamps, user_id)

    return hourly_graph, weekly_graph, len(timestamps)

