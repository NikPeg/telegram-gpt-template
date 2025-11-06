# ⚡ Быстрый старт за 3 минуты

## Docker Compose (проще всего)

```bash
# 1. Клонируйте репозиторий
git clone <repository-url>
cd empathy-ai-bot

# 2. Создайте .env файл
cp .env.example .env
```

Откройте `.env` и заполните **4 обязательных поля**:

```env
TG_TOKEN=ваш_токен_от_BotFather
LLM_TOKEN=ваш_ключ_от_OpenRouter
MODEL=google/gemini-2.0-flash-exp:free
ADMIN_CHAT=ваш_chat_id
```

```bash
# 3. Запустите!
docker-compose up -d
```

**Готово!** 🎉 Бот запущен.

### Базовые команды

```bash
# Логи
docker-compose logs -f

# Остановка
docker-compose down

# Перезапуск
docker-compose restart
```

---

## Локальный запуск

```bash
# 1. Клонируйте и настройте
git clone <repository-url>
cd empathy-ai-bot
cp .env.example .env
nano .env  # Заполните токены

# 2. Установите зависимости
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Запустите
python main.py
```

---

## Где получить токены?

- **TG_TOKEN**: [@BotFather](https://t.me/BotFather) — создайте бота и скопируйте токен
- **LLM_TOKEN**: [OpenRouter](https://openrouter.ai/) — зарегистрируйтесь и создайте API ключ
- **ADMIN_CHAT**: [@userinfobot](https://t.me/userinfobot) — отправьте /start и получите свой ID

---

📖 **[Подробная документация →](docs/deployment.md)**

