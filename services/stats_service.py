"""
Сервис для сбора статистики и генерации графиков.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

import aiosqlite
import matplotlib
import matplotlib.pyplot as plt

from config import TABLE_NAME, TIMEZONE_OFFSET
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
    Применяет TIMEZONE_OFFSET для корректного отображения времени.

    Args:
        user_id: ID пользователя. Если None, собирает статистику по всем пользователям.

    Returns:
        Список объектов datetime с временными метками (с учетом часового пояса).
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

        # Парсим timestamps с учетом часового пояса
        for row in rows:
            if row[0]:
                try:
                    dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    # Применяем смещение часового пояса
                    dt_with_offset = dt + timedelta(hours=TIMEZONE_OFFSET)
                    timestamps.append(dt_with_offset)
                except (ValueError, TypeError):
                    continue

    return timestamps


async def generate_hourly_stats(
    timestamps: list[datetime], user_id: int | None = None
) -> BytesIO:
    """
    Генерирует график статистики по часам суток (среднее значение).

    Args:
        timestamps: Список временных меток.
        user_id: ID пользователя (для заголовка).

    Returns:
        BytesIO объект с изображением графика.
    """
    # Группируем сообщения по дате и часу
    date_hour_counts = defaultdict(lambda: defaultdict(int))
    for dt in timestamps:
        date_key = dt.date()  # Дата без времени
        date_hour_counts[date_key][dt.hour] += 1

    # Подсчитываем среднее количество сообщений для каждого часа
    hourly_averages = defaultdict(list)
    for date_data in date_hour_counts.values():
        for hour in range(24):
            hourly_averages[hour].append(date_data.get(hour, 0))

    # Вычисляем среднее для каждого часа
    hours = list(range(24))
    num_days = len(date_hour_counts) if date_hour_counts else 1
    avg_counts = [
        sum(hourly_averages[h]) / num_days if hourly_averages[h] else 0
        for h in hours
    ]

    # Создаем график
    plt.figure(figsize=(14, 6))
    bars = plt.bar(hours, avg_counts, color="skyblue", edgecolor="navy", alpha=0.7)

    # Подсвечиваем максимальные значения
    if avg_counts:
        max_count = max(avg_counts)
        for bar, count in zip(bars, avg_counts, strict=True):
            if count == max_count and count > 0:
                bar.set_color("orange")
                bar.set_edgecolor("darkred")

    plt.xlabel("Час суток", fontsize=12, weight="bold")
    plt.ylabel("Среднее количество сообщений", fontsize=12, weight="bold")

    if user_id:
        plt.title(
            f"Средняя активность пользователя USER{user_id} по часам суток",
            fontsize=14,
            weight="bold",
        )
    else:
        plt.title(
            "Средняя активность всех пользователей по часам суток",
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
    Генерирует график статистики по дням недели (среднее значение).

    Args:
        timestamps: Список временных меток.
        user_id: ID пользователя (для заголовка).

    Returns:
        BytesIO объект с изображением графика.
    """
    # Группируем сообщения по неделям и дням недели
    # Используем ISO calendar для определения недель
    week_weekday_counts = defaultdict(lambda: defaultdict(int))
    for dt in timestamps:
        # Получаем ISO календарную неделю (год, номер недели)
        iso_year, iso_week, _ = dt.isocalendar()
        week_key = (iso_year, iso_week)
        week_weekday_counts[week_key][dt.weekday()] += 1

    # Подсчитываем среднее количество сообщений для каждого дня недели
    weekday_averages = defaultdict(list)
    for week_data in week_weekday_counts.values():
        for weekday in range(7):
            weekday_averages[weekday].append(week_data.get(weekday, 0))

    # Вычисляем среднее для каждого дня недели
    weekdays = list(range(7))
    num_weeks = len(week_weekday_counts) if week_weekday_counts else 1
    avg_counts = [
        sum(weekday_averages[d]) / num_weeks if weekday_averages[d] else 0
        for d in weekdays
    ]
    day_names = [WEEKDAY_NAMES[d] for d in weekdays]

    # Создаем график
    plt.figure(figsize=(12, 6))
    bars = plt.bar(day_names, avg_counts, color="lightgreen", edgecolor="darkgreen", alpha=0.7)

    # Подсвечиваем максимальные значения
    if avg_counts:
        max_count = max(avg_counts)
        for bar, count in zip(bars, avg_counts, strict=True):
            if count == max_count and count > 0:
                bar.set_color("gold")
                bar.set_edgecolor("darkred")

    plt.xlabel("День недели", fontsize=12, weight="bold")
    plt.ylabel("Среднее количество сообщений", fontsize=12, weight="bold")

    if user_id:
        plt.title(
            f"Средняя активность пользователя USER{user_id} по дням недели",
            fontsize=14,
            weight="bold",
        )
    else:
        plt.title(
            "Средняя активность всех пользователей по дням недели",
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


async def get_total_users_count() -> int:
    """
    Получает общее количество пользователей в базе данных.

    Returns:
        Общее количество пользователей.
    """
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.cursor()
        # Получаем общее количество пользователей из таблицы
        await cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
        result = await cursor.fetchone()
        return result[0] if result else 0


async def generate_user_stats(
    user_id: int | None = None,
) -> tuple[BytesIO, BytesIO, int, int | None]:
    """
    Генерирует статистику для пользователя (или всех пользователей).

    Args:
        user_id: ID пользователя. Если None, собирает статистику по всем пользователям.

    Returns:
        Кортеж из четырех элементов:
        - BytesIO с графиком по часам
        - BytesIO с графиком по дням недели
        - Общее количество сообщений
        - Общее количество пользователей (только если user_id is None, иначе None)
    """
    timestamps = await get_user_timestamps(user_id)

    if not timestamps:
        return None, None, 0, None

    hourly_graph = await generate_hourly_stats(timestamps, user_id)
    weekly_graph = await generate_weekly_stats(timestamps, user_id)

    # Получаем количество пользователей только при запросе статистики для всех
    total_users = await get_total_users_count() if user_id is None else None

    return hourly_graph, weekly_graph, len(timestamps), total_users

