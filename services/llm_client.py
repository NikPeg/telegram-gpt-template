import asyncio
import base64
import json
import os

import aiohttp
from dotenv import load_dotenv

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

    for attempt in range(1, retries + 1):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, headers=headers, data=json.dumps(data)) as response,
            ):
                if response.status == 429:
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message="Too Many Requests",
                        headers=response.headers,
                    )

                response.raise_for_status()
                response_text = await response.text()
                response_json = json.loads(response_text)
                if "choices" in response_json and len(response_json["choices"]) > 0:
                    return response_json["choices"][0]["message"]["content"]
                print("No choices returned in the response.")
                return None

        except aiohttp.ClientResponseError as e:
            if e.status == 429:
                print(
                    f"429 Too Many Requests, попытка {attempt}/{retries}. Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                print(f"HTTP error: {e}")
                return None
        except aiohttp.ClientError as e:
            print(f"Error sending request to OpenRouter: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON response: {e}")
            return None

    return None


async def send_image_to_vision_model(
    image_bytes: bytes,
    image_mime_type: str = "image/jpeg",
    prompt: str = "Опиши подробно эту картинку на русском языке. Опиши что на ней изображено, какие объекты, люди, эмоции, детали.",
    model: str = VISION_MODEL,
    api_key: str = LLM_TOKEN,
    retries: int = 5,
    backoff_factor: int = 2,
) -> str | None:
    """
    Отправляет изображение в модель vision через OpenRouter для получения описания.

    Args:
        image_bytes: Байты изображения
        image_mime_type: MIME-тип изображения (image/jpeg, image/png, и т.д.)
        prompt: Промпт для описания изображения
        model: Модель для обработки изображения
        api_key: API ключ OpenRouter
        retries: Количество попыток при ошибках
        backoff_factor: Фактор увеличения задержки между попытками

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
                        "image_url": {"url": f"data:{image_mime_type};base64,{base64_image}"},
                    },
                ],
            }
        ],
    }

    delay = 1

    for attempt in range(1, retries + 1):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(url, headers=headers, data=json.dumps(data)) as response,
            ):
                if response.status == 429:
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message="Too Many Requests",
                        headers=response.headers,
                    )

                response.raise_for_status()
                response_text = await response.text()
                response_json = json.loads(response_text)

                if "choices" in response_json and len(response_json["choices"]) > 0:
                    return response_json["choices"][0]["message"]["content"]

                print("No choices returned in the response (vision model).")
                return None

        except aiohttp.ClientResponseError as e:
            if e.status == 429:
                print(
                    f"Vision model 429 Too Many Requests, попытка {attempt}/{retries}. "
                    f"Жду {delay} сек..."
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                print(f"Vision model HTTP error: {e}")
                return None
        except aiohttp.ClientError as e:
            print(f"Error sending image to OpenRouter (vision model): {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON response (vision model): {e}")
            return None

    return None


async def main():
    pass


if __name__ == "__main__":
    asyncio.run(main())
