import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration settings for the application"""
    
    # API Configuration
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip('"\'')
    SECRET: str = os.getenv("SECRET", "").strip('"\'')
    EMAIL: str = os.getenv("EMAIL", "").strip('"\'')
    
    # Server Configuration
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Quiz Configuration
    QUIZ_TIMEOUT: int = 180  # 3 minutes in seconds
    MAX_RETRIES: int = 5
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that required configuration is present"""
        if not cls.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY environment variable is required")
        if not cls.SECRET:
            raise ValueError("SECRET environment variable is required")
        if not cls.EMAIL:
            raise ValueError("EMAIL environment variable is required")
        return True
