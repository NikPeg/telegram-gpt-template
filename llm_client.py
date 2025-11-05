import aiohttp
import json
import asyncio
import os
from dotenv import load_dotenv


load_dotenv()
LLM_TOKEN = os.environ.get("LLM_TOKEN")
MODEL = os.environ.get("MODEL")


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
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=json.dumps(data)) as response:
                    if response.status == 429:
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message="Too Many Requests",
                            headers=response.headers
                        )

                    response.raise_for_status()
                    response_text = await response.text()
                    response_json = json.loads(response_text)
                    if "choices" in response_json and len(response_json["choices"]) > 0:
                        return response_json["choices"][0]["message"]["content"]
                    else:
                        print("No choices returned in the response.")
                        return None

        except aiohttp.ClientResponseError as e:
            if e.status == 429:
                print(f"429 Too Many Requests, попытка {attempt}/{retries}. Жду {delay} сек...")
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


async def main():
    pass

if __name__ == "__main__":
    asyncio.run(main())
