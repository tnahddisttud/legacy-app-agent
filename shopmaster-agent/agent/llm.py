"""The LLMs. Main: OpenAI's open-weight gpt-oss on Groq. Fallback: Google's Gemma on the Gemini API (free).

Keys go in .env: GROQ_API_KEY for the main model, GOOGLE_API_KEY for the fallback (optional, get one at
https://aistudio.google.com/apikey). Without GOOGLE_API_KEY the agent simply has no fallback.
"""
import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

DEFAULT_MODEL = "openai/gpt-oss-120b"        # or "openai/gpt-oss-20b" (faster, cheaper); set LLM_MODEL in .env
DEFAULT_FALLBACK_MODEL = "gemma-4-31b-it"    # or "gemma-4-26b-a4b-it"; set FALLBACK_MODEL in .env


def get_llm() -> ChatGroq:
    load_dotenv()
    return ChatGroq(
        model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        temperature=0,           # tool-calling agents should be predictable
        reasoning_effort="low",  # gpt-oss "thinks" first; low keeps tool loops fast and cheap
        max_tokens=2000,         # always cap output tokens (reasoning tokens count too, so not too tight)
        timeout=60,
        max_retries=1,           # when it keeps failing (e.g. rate limit), hand over to the fallback quickly
    )


def get_fallback_llm() -> ChatGoogleGenerativeAI | None:
    """Used only when the main model's call fails. Returns None if GOOGLE_API_KEY is not set."""
    load_dotenv()
    if not os.getenv("GOOGLE_API_KEY"):
        return None
    return ChatGoogleGenerativeAI(
        model=os.getenv("FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL),
        temperature=0,
        max_output_tokens=2000,
        timeout=60,
        max_retries=1,
    )
