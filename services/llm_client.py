import asyncio
import base64
import json
import os

import aiohttp
from dotenv import load_dotenv

from config import logger

load_dotenv()
LLM_TOKEN = os.environ.get("LLM_TOKEN")
MODEL = os.environ.get("MODEL")
VISION_MODEL = os.environ.get("VISION_MODEL", "google/gemini-2.0-flash-001")


async def send_request_to_openrouter(
    prompt,
    model=MODEL,
    api_key=LLM_TOKEN,
    retries=5,
    backoff_factor=2,
):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {"model": model, "messages": prompt}

    delay = 1
    # HTTP статусы, для которых стоит делать retry (серверные ошибки и rate limit)
    retryable_statuses = {429, 500, 502, 503, 504}

    for attempt in range(1, retries + 1):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, headers=headers, data=json.dumps(data)) as response,
            ):
                # Для retryable статусов делаем retry
                if response.status in retryable_statuses:
                    if attempt < retries:
                        logger.info(
                            f"HTTP {response.status}, попытка {attempt}/{retries}. Жду {delay} сек..."
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                        continue
                    # Это последняя попытка, логируем ошибку
                    error_text = await response.text()
                    logger.error(
                        f"HTTP error after {retries} attempts: {response.status}, "
                        f"message='{response.reason}'. Response: {error_text}"
                    )
                    return None

                response.raise_for_status()
                response_text = await response.text()
                response_json = json.loads(response_text)

                # Логируем ответ для отладки
                logger.debug(
                    f"LLM API response: {json.dumps(response_json, ensure_ascii=False)[:500]}"
                )

                if "choices" in response_json and len(response_json["choices"]) > 0:
                    content = response_json["choices"][0]["message"]["content"]
                    if content is None or content.strip() == "":
                        logger.warning(
                            f"LLM returned empty content. Full response: {response_json}"
                        )
                    return content

                logger.error(f"No choices in LLM response. Response: {response_json}")
                return None

        except aiohttp.ClientResponseError as e:
            # Этот блок ловит ошибки от raise_for_status() для других статус-кодов
            if attempt < retries:
                logger.info(
                    f"HTTP error, попытка {attempt}/{retries}: {e}. Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(f"HTTP error after {retries} attempts: {e}")
                return None
        except aiohttp.ClientError as e:
            # Сетевые ошибки (включая TransferEncodingError, ConnectionResetError и т.д.)
            if attempt < retries:
                logger.info(
                    f"Network error, попытка {attempt}/{retries}: {e}. Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(f"Error sending request to OpenRouter after {retries} attempts: {e}")
                return None
        except json.JSONDecodeError as e:
            # JSON ошибки могут быть из-за неполного ответа при обрыве соединения
            if attempt < retries:
                logger.info(
                    f"JSON decode error, попытка {attempt}/{retries}: {e}. Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(f"Error decoding JSON response after {retries} attempts: {e}")
                return None

    return None


async def send_image_to_vision_model(
    image_bytes: bytes,
    image_mime_type: str = "image/jpeg",
    prompt: str = "Опиши подробно эту картинку на русском языке. Опиши что на ней изображено, какие объекты, люди, эмоции, детали.",
    model: str = VISION_MODEL,
    api_key: str = LLM_TOKEN,
    retries: int = 3,
    retry_delay: int = 1,
) -> str | None:
    """
    Отправляет изображение в модель vision через OpenRouter для получения описания.

    Args:
        image_bytes: Байты изображения
        image_mime_type: MIME-тип изображения (image/jpeg, image/png, и т.д.)
        prompt: Промпт для описания изображения
        model: Модель для обработки изображения
        api_key: API ключ OpenRouter
        retries: Количество попыток при ошибках (по умолчанию 3)
        retry_delay: Задержка между попытками в секундах (по умолчанию 1)

    Returns:
        Описание изображения от модели или None при ошибке
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Кодируем изображение в base64
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    # Формируем запрос с изображением
    data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_mime_type};base64,{base64_image}"
                        },
                    },
                ],
            }
        ],
    }

    # HTTP статусы, для которых стоит делать retry (серверные ошибки и rate limit)
    retryable_statuses = {400, 429, 500, 502, 503, 504}
    delay = retry_delay

    for attempt in range(1, retries + 1):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, headers=headers, data=json.dumps(data)) as response,
            ):
                # Для retryable статусов делаем retry
                if response.status in retryable_statuses:
                    if attempt < retries:
                        logger.info(
                            f"Vision model HTTP {response.status}, попытка {attempt}/{retries}. "
                            f"Жду {delay} сек..."
                        )
                        await asyncio.sleep(delay)
                        delay *= 2  # Простой backoff для vision модели
                        continue
                    # Это последняя попытка, логируем ошибку
                    error_text = await response.text()
                    logger.error(
                        f"Vision model HTTP error after {retries} attempts: {response.status}, "
                        f"message='{response.reason}'. Response: {error_text}"
                    )
                    return None

                response.raise_for_status()
                response_text = await response.text()
                response_json = json.loads(response_text)

                if "choices" in response_json and len(response_json["choices"]) > 0:
                    content = response_json["choices"][0]["message"]["content"]
                    if content is None or content.strip() == "":
                        logger.warning(
                            f"Vision model returned empty content. Full response: {response_json}"
                        )
                    return content

                logger.error(
                    f"No choices in vision model response. Response: {response_json}"
                )
                return None

        except aiohttp.ClientResponseError as e:
            # Этот блок ловит ошибки от raise_for_status() для других статус-кодов
            if attempt < retries:
                logger.info(
                    f"Vision model HTTP error, попытка {attempt}/{retries}: {e}. "
                    f"Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                logger.error(f"Vision model HTTP error after {retries} attempts: {e}")
                return None
        except aiohttp.ClientError as e:
            # Сетевые ошибки (включая TransferEncodingError, ConnectionResetError и т.д.)
            if attempt < retries:
                logger.info(
                    f"Vision model network error, попытка {attempt}/{retries}: {e}. "
                    f"Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                logger.error(
                    f"Error sending image to OpenRouter (vision model) after {retries} attempts: {e}"
                )
                return None
        except json.JSONDecodeError as e:
            # JSON ошибки могут быть из-за неполного ответа при обрыве соединения
            if attempt < retries:
                logger.info(
                    f"Vision model JSON decode error, попытка {attempt}/{retries}: {e}. "
                    f"Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                logger.error(
                    f"Error decoding JSON response (vision model) after {retries} attempts: {e}"
                )
                return None

    return None


async def main():
    pass


if __name__ == "__main__":
    asyncio.run(main())
