# Тесты

Этот каталог содержит тесты для бота.

## Установка зависимостей

```bash
pip install -r requirements/requirements-dev.txt
```

## Запуск тестов

Запустить все тесты:

```bash
pytest tests/
```

Запустить с подробным выводом:

```bash
pytest tests/ -v
```

Запустить с покрытием кода:

```bash
pytest tests/ --cov=. --cov-report=html
```

## Структура тестов

### `test_forget_command.py`

Тесты для команды `/forget` и логики управления контекстом:

- **`test_forget_first_message_in_context`** - проверяет, что первое сообщение после `/forget` попадает в промпт для LLM
- **`test_forget_second_message_has_context`** - проверяет, что второе сообщение получает контекст из первого
- **`test_forget_counter_increments`** - проверяет корректное увеличение счетчика `active_messages_count`
- **`test_forget_messages_saved_in_db`** - проверяет, что все сообщения сохраняются в БД даже после `/forget`

## Фикстуры

### `test_db`

Создает изолированную тестовую базу данных SQLite для каждого теста и автоматически очищает ее после выполнения.

## Проверка кода

Запустить линтер:

```bash
ruff check .
```

Автоматически исправить проблемы:

```bash
ruff check --fix .
```

## CI/CD

Тесты автоматически запускаются в GitHub Actions при каждом push и pull request.

