#!/bin/bash
# Скрипт для добавления пользователей и чатов в базу данных бота
# Использование: ./add_user.sh USER7581829366 или ./add_user.sh -1003209384984

USER_ID=$1

if [ -z "$USER_ID" ]; then
    echo "Использование: ./add_user.sh USER7581829366"
    echo "              или: ./add_user.sh 7581829366"
    echo "              или: ./add_user.sh USER-1003209384984 (для чатов)"
    exit 1
fi

# Убираем префикс USER если есть
USER_ID=${USER_ID#USER}

# Проверяем что это число (включая отрицательные для чатов)
if ! [[ "$USER_ID" =~ ^-?[0-9]+$ ]]; then
    echo "❌ Некорректный ID: $USER_ID"
    exit 1
fi

# Определяем тип
if [ "$USER_ID" -lt 0 ]; then
    TYPE="CHAT"
else
    TYPE="USER"
fi

# Путь к базе данных (относительно корня проекта)
DB_PATH="../users.db"

# Проверяем существование базы
if [ ! -f "$DB_PATH" ]; then
    echo "❌ База данных не найдена: $DB_PATH"
    exit 1
fi

# Проверяем существование
EXISTS=$(sqlite3 "$DB_PATH" "SELECT EXISTS(SELECT 1 FROM conversations WHERE id = $USER_ID);")

if [ "$EXISTS" -eq 1 ]; then
    echo "ℹ️  $TYPE$USER_ID уже есть в базе"
else
    # Добавляем с минимальным набором полей
    sqlite3 "$DB_PATH" "INSERT INTO conversations (id, name, active_messages_count, subscription_verified, referral_code) VALUES ($USER_ID, NULL, NULL, NULL, NULL);"
    echo "✅ $TYPE$USER_ID добавлен в базу"
    echo "   📝 Имя обновится автоматически при первом сообщении"
fi

