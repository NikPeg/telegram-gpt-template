# Безопасность

## Обзор

Проект включает встроенные механизмы защиты и следует best practices для безопасной разработки Telegram-ботов.

## Встроенная защита

### 1. Защита от SQL Injection

Используется `aiosqlite` с параметризованными запросами:

```python
# Правильно (защищено)
await db.execute(
    "SELECT * FROM users WHERE user_id = ?",
    (user_id,)
)

# Неправильно (уязвимо)
await db.execute(
    f"SELECT * FROM users WHERE user_id = {user_id}"
)
```

Все запросы к БД в проекте используют параметризацию.

### 2. Безопасное хранение токенов

Все чувствительные данные хранятся в `.env` файле, который:
- Не коммитится в Git (указан в `.gitignore`)
- Загружается через `python-dotenv`
- Доступен только процессу приложения

```python
# core/config.py
from dotenv import load_dotenv
import os

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")  # Никогда не хардкодим
LLM_TOKEN = os.getenv("LLM_TOKEN")
```

### 3. Логирование без чувствительных данных

Логи не содержат:
- Токены API

⚠️ **Важно**: В текущей версии полные тексты сообщений логируются. Это нужно учитывать при работе с чувствительными данными.

```python
# core/config.py
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'logs/bot.log',
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
    ]
)
```

### 4. Rate Limiting от Telegram

Telegram автоматически применяет rate limiting:
- 30 сообщений в секунду для всех чатов
- 1 сообщение в секунду на приватный чат

Бот учитывает эти ограничения и обрабатывает соответствующие ошибки.

## Чек-лист безопасности

### Обязательно

- [x] ✅ `.env` файл добавлен в `.gitignore`
- [x] ✅ Используются разные токены для dev/prod окружений
- [x] ✅ Пароли и токены никогда не хардкодятся в коде
- [ ] ⚠️ Регулярно обновляются зависимости (`pip list --outdated`)
- [x] ✅ Ограничен доступ к admin командам (проверка ADMIN_CHAT)
- [x] ✅ Все SQL запросы параметризованы
- [ ] ⚠️ Логи не содержат чувствительные данные (текущая версия логирует полные тексты)

### Рекомендуется

- [ ] Настроен firewall на сервере (UFW, iptables)
- [ ] Используется HTTPS для webhook (если применимо)
- [ ] SSH доступ только по ключам (без паролей)
- [ ] Регулярные бэкапы базы данных
- [ ] Мониторинг подозрительной активности
- [ ] Автоматические обновления безопасности ОС
- [ ] Собственный rate limiting на уровне приложения
- [ ] Уведомление пользователей о privacy policy

## Управление доступом

### Администраторские команды

Все admin команды защищены проверкой:

```python
# handlers/admin_handlers.py
from core.config import ADMIN_CHAT

@router.message(Command("dispatch"))
async def dispatch_command(message: Message):
    # Проверка прав
    if message.from_user.id != ADMIN_CHAT:
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    # Основная логика
    ...
```

### Настройка ADMIN_CHAT

В `.env`:

```env
ADMIN_CHAT=123456789  # Ваш Telegram User ID
```

Для получения ID чата:
1. Откройте чат в веб-версии Telegram (web.telegram.org)
2. ID чата будет в URL: `https://web.telegram.org/k/#-123456789` (число после `#`)
3. Для приватных чатов ID всегда положительный, для групп — отрицательный

## Защита данных пользователей

### GDPR Compliance

Проект соответствует базовым требованиям GDPR:

1. **Минимизация данных** — сохраняются только необходимые данные
2. **Право на удаление** — команда `/forget` удаляет историю

⚠️ **TODO**: Добавить уведомление пользователей о сохранении данных при первом использовании бота.

### Хранение данных

Данные пользователей:
- Хранятся локально в SQLite
- Не передаются третьим сторонам (кроме LLM API)
- Автоматически очищаются при удалении бота из чата

### Очистка данных

Автоматическая очистка:

```python
# При удалении из группы
@router.my_chat_member(...)
async def on_bot_removed(event: ChatMemberUpdated):
    if event.new_chat_member.status == "left":
        await db.delete_chat(event.chat.id)
```

Ручная очистка через `/forget`:

```python
@router.message(Command("forget"))
async def forget_command(message: Message):
    await db.clear_context(message.from_user.id)
```

## Безопасность зависимостей

### Проверка уязвимостей

```bash
# Установка safety
pip install safety

# Проверка зависимостей
safety check
```

### Обновление зависимостей

```bash
# Просмотр устаревших пакетов
pip list --outdated

# Обновление конкретного пакета
pip install --upgrade aiogram

# Обновление всех (осторожно!)
pip install --upgrade -r requirements/requirements.txt
```

### Фиксация версий

В `requirements.txt` указаны точные версии:

```txt
aiogram==3.20.0  # Точная версия
aiosqlite>=0.19.0  # Минимальная версия
```

Это предотвращает неожиданные breaking changes.

## Docker безопасность

### Non-root пользователь

В `Dockerfile` бот запускается не от root:

```dockerfile
# Создаем пользователя
RUN adduser --disabled-password --gecos '' botuser

# Переключаемся на него
USER botuser

# Запускаем приложение
CMD ["python", "main.py"]
```

### Минимальный образ

Используется `python:3.14-slim` вместо полного образа для уменьшения поверхности атаки.

### Регулярные обновления

```bash
# Обновление базового образа
docker-compose pull
docker-compose up -d --build
```

## Защита от DDoS

### Telegram встроенный Rate Limiting

Telegram автоматически блокирует ботов, которые:
- Отправляют слишком много сообщений
- Совершают подозрительные действия
- Получают много жалоб

Бот учитывает эти ограничения:
- 30 сообщений в секунду для всех чатов
- 1 сообщение в секунду на приватный чат

⚠️ **TODO**: Рассмотреть добавление собственного rate limiting на уровне приложения для защиты от злоупотреблений.

## Мониторинг безопасности

### Логи для анализа

Все критические события логируются с различными уровнями важности:

```python
# Ошибки в обработке запросов
logger.error(f"LLM{chat_id} - Критическая ошибка: {e}", exc_info=True)

# Предупреждения о проблемах
logger.warning(f"USER{user_id} заблокировал бота, удален из БД")

# Информация о действиях пользователей
logger.info(f"USER{chat_id}TOLLM:{message.text}")
```

### Алерты

Уведомления администратору настроены и работают:

```python
# core/utils.py
async def forward_to_debug(message_chat_id: int, message_id: int):
    """Пересылает сообщение в DEBUG чат для мониторинга."""
    # Реализовано в проекте
    
# handlers/admin_handlers.py
await bot.send_message(ADMIN_CHAT, error_msg)
```

Бот автоматически отправляет в `ADMIN_CHAT`:
- Критические ошибки при выполнении команд
- Сообщения пользователей (через `forward_to_debug`)
- Результаты административных операций

## Защита CI/CD

### GitHub Secrets

Все секреты хранятся в GitHub Secrets:
- `SSH_HOST`
- `SSH_USER`
- `SSH_KEY`
- `ENV_FILE`

**Важно:** Никогда не логируйте secrets в GitHub Actions.

### Защищенные ветки

Настройте branch protection для `main`:
- Require pull request reviews
- Require status checks to pass
- No force pushes

## Инциденты безопасности

### Что делать при утечке токена

1. **Немедленно** отзовите старый токен через [@BotFather](https://t.me/BotFather)
2. Сгенерируйте новый токен
3. Обновите `.env` и GitHub Secrets
4. Перезапустите бота
5. Проверьте логи на подозрительную активность
6. Измените все связанные пароли

### Контакты для сообщений

Если обнаружили уязвимость:
- Создайте приватный Security Advisory на GitHub
- Или напишите автору: [t.me/nikpeg](https://t.me/nikpeg)

**Не публикуйте** детали уязвимости в Issues до её исправления.

## Best Practices

### 1. Принцип минимальных привилегий

Бот должен иметь только необходимые разрешения:

```python
# В BotFather отключите неиспользуемые функции
# /setprivacy - Enable для групп (если не нужно видеть все сообщения)
# /setjoingroups - Disable (если не должен быть в группах)
```

### 2. Регулярные аудиты

```bash
# Проверка безопасности кода
bandit -r .

# Проверка зависимостей
safety check

# Анализ Docker образа
docker scan mybot:latest
```

### 3. Разделение окружений

```env
# .env.dev
TG_TOKEN=dev_token
LLM_TOKEN=dev_token
DEBUG=True

# .env.prod
TG_TOKEN=prod_token
LLM_TOKEN=prod_token
DEBUG=False
```

### 4. Резервное копирование

```bash
# Регулярный бэкап БД
sqlite3 data/users.db ".backup 'backup/users_$(date +%Y%m%d).db'"

# Автоматизация через cron
0 3 * * * /path/to/backup_script.sh
```

## Улучшение безопасности

### Текущие задачи (TODO)

Список улучшений безопасности для реализации:

#### Высокий приоритет

1. **Ограничение логирования сообщений**
   - Убрать логирование полных текстов сообщений пользователей
   - Логировать только метаданные (длина, тип, user_id)
   - Добавить флаг для debug-режима с полным логированием

2. **Уведомление о privacy policy**
   - Добавить сообщение при первом запуске `/start` о том, что данные сохраняются
   - Добавить ссылку на политику конфиденциальности
   - Получать согласие пользователя на хранение истории

3. **Rate limiting на уровне приложения**
   - Добавить ограничение количества запросов в минуту на пользователя
   - Защита от флуда и злоупотреблений
   - Уведомления пользователей о превышении лимитов

#### Средний приоритет

4. **Расширенное логирование безопасности**
   - Добавить отдельный файл логов для security events
   - Логировать попытки несанкционированного доступа к admin командам
   - Статистика использования по пользователям для детекции аномалий

5. **Улучшение хранения секретов**
   - Текущая реализация: GitHub Secrets для CI/CD
   - Рассмотреть использование secrets manager (HashiCorp Vault, AWS Secrets Manager)
   - Ротация токенов API
   - Разделение прав доступа для разных компонентов

#### Низкий приоритет

6. **Audit logging**
   - Детальное логирование всех административных действий
   - Immutable audit logs (только добавление, без удаления)
   - Периодический анализ логов на аномалии

7. **Дополнительная защита Docker**
   - Security scanning образов перед деплоем
   - Использование distroless образов
   - Network policies для ограничения сетевого доступа

## Дополнительные ресурсы

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Telegram Bot Security](https://core.telegram.org/bots/security)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [Docker Security](https://docs.docker.com/engine/security/)

