"""
Сервис для проверки подписки пользователей на обязательные каналы.
"""

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config import REQUIRED_CHANNELS, logger
from database import ChatVerification, User


async def check_user_subscription(bot: Bot, user_id: int, channels: list[str] = None) -> dict[str, bool]:
    """
    Проверяет подписку пользователя на список каналов.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        channels: Список каналов для проверки (по умолчанию REQUIRED_CHANNELS)

    Returns:
        Словарь {channel: subscribed}, где subscribed = True если пользователь подписан
    """
    if channels is None:
        channels = REQUIRED_CHANNELS

    if not channels:
        # Если каналов нет, считаем что подписка не требуется
        return {}

    results = {}

    for channel in channels:
        try:
            # Получаем информацию о членстве пользователя в канале
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)

            # Проверяем статус пользователя
            # Статусы: creator, administrator, member - подписан
            # left, kicked - не подписан
            is_subscribed = member.status in ["creator", "administrator", "member"]
            results[channel] = is_subscribed

            logger.debug(f"USER{user_id}: канал {channel}, статус {member.status}, подписан: {is_subscribed}")

        except TelegramBadRequest as e:
            # Специальная обработка для PARTICIPANT_ID_INVALID
            # Это нормальная ситуация для пользователей, которые никогда не были в канале
            if "PARTICIPANT_ID_INVALID" in str(e):
                logger.debug(f"USER{user_id}: не является участником канала {channel} (никогда не был подписан)")
                results[channel] = False
            else:
                # Другие ошибки - канал не найден или бот не является админом
                logger.warning(f"Ошибка при проверке канала {channel} для USER{user_id}: {e}")
                results[channel] = False
        except TelegramForbiddenError as e:
            # Бот заблокирован пользователем или не имеет доступа
            logger.warning(f"Нет доступа к каналу {channel} для USER{user_id}: {e}")
            results[channel] = False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при проверке канала {channel} для USER{user_id}: {e}", exc_info=True)
            results[channel] = False

    return results


async def is_user_subscribed_to_all(bot: Bot, user_id: int, channels: list[str] = None) -> bool:
    """
    Проверяет, подписан ли пользователь на ВСЕ обязательные каналы.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя
        channels: Список каналов для проверки (по умолчанию REQUIRED_CHANNELS)

    Returns:
        True если подписан на все каналы, False иначе
    """
    if channels is None:
        channels = REQUIRED_CHANNELS

    if not channels:
        # Если каналов нет, считаем что подписка не требуется
        return True

    results = await check_user_subscription(bot, user_id, channels)
    is_subscribed = all(results.values())

    logger.info(f"USER{user_id}: проверка подписки завершена, результат: {is_subscribed}")

    return is_subscribed


async def update_user_subscription_status(bot: Bot, user_id: int) -> bool:
    """
    Проверяет подписку пользователя и обновляет статус в БД.

    Args:
        bot: Экземпляр бота
        user_id: ID пользователя

    Returns:
        True если пользователь подписан на все каналы, False иначе
    """
    user = User(user_id)
    await user.get_from_db()

    is_subscribed = await is_user_subscribed_to_all(bot, user_id)

    # Обновляем статус в БД
    user.subscription_verified = 1 if is_subscribed else 0
    await user.update_in_db()

    logger.info(f"USER{user_id}: статус подписки обновлен в БД: {user.subscription_verified}")

    return is_subscribed


async def subscription_check_loop(bot: Bot):
    """
    Фоновая задача для периодической проверки подписок пользователей и чатов.
    Проверяет подписку каждые 30 минут.

    Проверяет:
    1. Личных пользователей (ID > 0) - обновляет subscription_verified
    2. Верифицированные чаты - проверяет подписку пользователя-верификатора
       Если верификатор отписался - удаляет запись из chat_verifications
    """
    logger.info("Запуск фоновой задачи проверки подписок")

    while True:
        try:
            # ========== ПРОВЕРКА ЛИЧНЫХ ПОЛЬЗОВАТЕЛЕЙ ==========
            all_user_ids = await User.get_ids_from_table()
            user_ids = [uid for uid in all_user_ids if uid > 0]
            logger.info(f"Проверка подписок для {len(user_ids)} пользователей")

            for user_id in user_ids:
                try:
                    user = User(user_id)
                    await user.get_from_db()

                    # Пропускаем пользователей, которые еще не проверялись (NULL)
                    if user.subscription_verified is None:
                        continue

                    # Проверяем подписку
                    is_subscribed = await is_user_subscribed_to_all(bot, user_id)
                    new_status = 1 if is_subscribed else 0

                    # Логируем только если статус изменился
                    if user.subscription_verified != new_status:
                        logger.info(f"USER{user_id}: статус подписки изменился с {user.subscription_verified} на {new_status}")
                        user.subscription_verified = new_status
                        await user.update_in_db()

                except Exception as e:
                    logger.error(f"Ошибка при проверке подписки USER{user_id}: {e}", exc_info=True)
                    continue

            logger.debug("Проверка подписок пользователей завершена")

            # ========== ПРОВЕРКА ВЕРИФИЦИРОВАННЫХ ЧАТОВ ==========
            import aiosqlite

            from database import DATABASE_NAME

            async with aiosqlite.connect(DATABASE_NAME) as db:
                cursor = await db.execute("SELECT chat_id, verified_by_user_id, user_name FROM chat_verifications")
                chat_verifications = await cursor.fetchall()

            if chat_verifications:
                logger.info(f"Проверка верификации для {len(chat_verifications)} чатов")

                for chat_id, verifier_user_id, verifier_name in chat_verifications:
                    try:
                        # Проверяем подписку пользователя-верификатора
                        is_subscribed = await is_user_subscribed_to_all(bot, verifier_user_id)

                        if not is_subscribed:
                            # Верификатор отписался - удаляем верификацию чата
                            logger.warning(
                                f"CHAT{chat_id}: верификатор {verifier_name} (ID: {verifier_user_id}) "
                                f"отписался от каналов. Удаляем верификацию чата."
                            )

                            chat_verification = ChatVerification(chat_id)
                            await chat_verification.delete_from_db()

                            logger.info(f"CHAT{chat_id}: верификация удалена")
                        else:
                            logger.debug(f"CHAT{chat_id}: верификатор {verifier_name} подписан, всё ОК")

                    except Exception as e:
                        logger.error(
                            f"Ошибка при проверке верификации CHAT{chat_id}: {e}",
                            exc_info=True
                        )
                        continue

                logger.debug("Проверка верификации чатов завершена")
            else:
                logger.debug("Нет верифицированных чатов для проверки")

        except Exception as e:
            logger.error(f"Критическая ошибка в фоновой задаче проверки подписок: {e}", exc_info=True)

        # Ждем 30 минут до следующей проверки
        await asyncio.sleep(1800)



