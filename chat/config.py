"""
config.py
---------
Single source of truth for all environment variables and settings.
Import `settings` anywhere in the service; never read os.environ directly elsewhere.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Groq
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = "openai/gpt-oss-120b"     # best free-tier model with tool calling support (llama-3.3-70b-versatile was deprecated by Groq on 2026-08-16)

    # Backend integration
    BACKEND_MODE: str = os.getenv("BACKEND_MODE", "mock")   # "mock" | "real"
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")

    # Service
    SERVICE_PORT: int = int(os.getenv("SERVICE_PORT", "8001"))

    def is_mock(self) -> bool:
        return self.BACKEND_MODE.lower() == "mock"

    def validate(self) -> None:
        """Call at startup. Raises if critical config is missing."""
        if not self.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY is not set. "
                "Copy .env.example to .env and add your key."
            )


settings = Settings()