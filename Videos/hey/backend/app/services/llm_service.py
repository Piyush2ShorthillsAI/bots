import os
import asyncio
import aiohttp
from dotenv import load_dotenv
import json
 
load_dotenv()
 
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")  
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
 
class LLMService:
    def __init__(self):
        if not AZURE_OPENAI_API_KEY or not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_DEPLOYMENT:
            raise ValueError("Missing Azure OpenAI configuration in environment variables.")
 
        self.api_key = AZURE_OPENAI_API_KEY
        self.endpoint = AZURE_OPENAI_ENDPOINT.rstrip("/")
        self.deployment = AZURE_OPENAI_DEPLOYMENT
        self.api_url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
 
    async def get_response_stream(self, messages: list[dict[str, str]]):
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json"
        }
 
        payload = {
            "messages": messages,
            "temperature": 0.7,
            "stream": True
        }
 
        async with aiohttp.ClientSession() as session:
            async with session.post(self.api_url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"Azure OpenAI API call failed: {resp.status}, {error_text}")
 
                async for line in resp.content:
                    if line:
                        decoded = line.decode("utf-8").strip()
                        if decoded.startswith("data: "):
                            content = decoded[6:].strip()
                            if content == "[DONE]":
                                break
                            try:
                                data = json.loads(content)
                                delta = data["choices"][0]["delta"]
                                if "content" in delta:
                                    yield delta["content"]
                            except Exception as e:
                                print(f"Streaming parse error: {e}")
 
async def main():
    llm_service = LLMService()
    messages = [
        {"role": "user", "content": "Hello, how are you?"}
    ]
    async for item in llm_service.get_response_stream(messages):
        print(item, end="", flush=True)
 
if __name__ == "__main__":
    asyncio.run(main())