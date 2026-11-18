"""Run this first: uv run healthcheck.py   (checks the shop, the login, and the LLM)"""
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

from shopmaster.operations import get_client  # noqa: E402


def main() -> int:
    client = get_client()
    try:
        pong = httpx.get(f"{client.base_url}/ping.do", timeout=5).text.strip()
        print(f"✅ ShopMaster is up ({pong}) at {client.base_url}")
    except httpx.HTTPError as e:
        print(f"❌ Cannot reach ShopMaster: {e}\n   Did you run 'docker compose up --build' in legacy-shop/ ?")
        return 1
    try:
        product = client.get_product(1)
        print(f"✅ Logged in and read a product: {product.name} (${product.price})")
    except Exception as e:
        print(f"❌ Login/read failed: {e}")
        return 1
    try:
        from agent.llm import get_llm
        reply = get_llm().invoke("Say 'stack connected' and nothing else.")
        print(f"✅ LLM answered: {reply.content}")
    except Exception as e:
        print(f"❌ LLM call failed: {type(e).__name__}: {e}\n   Check GROQ_API_KEY and LLM_MODEL in .env")
        return 1
    try:
        from agent.llm import get_fallback_llm
        fallback = get_fallback_llm()
        if fallback is None:
            print("➖ No fallback LLM (set GOOGLE_API_KEY in .env to add Gemma as a backup)")
        else:
            reply = fallback.invoke("Say 'fallback connected' and nothing else.")
            print(f"✅ Fallback LLM ({fallback.model}) answered: {reply.text}")
    except Exception as e:  # a broken fallback is a warning, not a failure: the main model still works
        print(f"⚠️  Fallback LLM call failed: {type(e).__name__}: {e}\n   Check GOOGLE_API_KEY and FALLBACK_MODEL in .env")
    print("✅ Check smith.langchain.com: a trace should have appeared.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
