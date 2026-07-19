from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://etair:etair_secret@localhost:5432/etair"
    CELERY_DATABASE_URL: str = "postgresql+psycopg2://etair:etair_secret@localhost:5432/etair"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO / S3 / Supabase Storage
    STORAGE_PROVIDER: str = "minio"  # "minio" or "supabase_s3"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "etair_minio"
    MINIO_SECRET_KEY: str = "etair_minio_secret"
    MINIO_BUCKET_FILES: str = "etair-files"
    MINIO_BUCKET_THUMBS: str = "etair-thumbnails"
    MINIO_SECURE: bool = False
    MINIO_REGION: str = "us-east-1"

    # Supabase direct API settings (optional, used if calling Supabase REST/Auth)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_KEY: Optional[str] = None

    # JWT
    JWT_SECRET: str = "change_this_in_production_super_secret_key"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours

    # OpenAI — optional, no longer needed for core pipeline
    # (Embeddings use Gemini, audio transcription uses Groq Whisper)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"  # unused if GEMINI_API_KEY is set

    # Local Embeddings via FastEmbed (768-dim)
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"
    GEMINI_API_KEY: Optional[str] = None  # kept to avoid pydantic extra_forbidden validation on existing .env

    # Groq (LLM query answering + Whisper audio transcription — free tier)
    GROQ_API_KEY: Optional[str] = None
    GROQ_CHAT_MODEL: str = "llama-3.3-70b-versatile"        # free tier, comparable to GPT-4o-mini
    GROQ_CHAT_MODEL_STRONG: str = "llama-3.3-70b-versatile"  # swap to 'deepseek-r1-distill-llama-70b' for reasoning
    GROQ_RCA_MODEL: str = "llama-3.3-70b-versatile"         # model used by SOPRAG RCA agent (Feature 3)
    GROQ_WHISPER_MODEL: str = "whisper-large-v3"            # Groq's free Whisper for audio transcription

    # Processing
    CHUNK_SIZE_TOKENS: int = 512
    CHUNK_OVERLAP_TOKENS: int = 64
    MAX_CONTEXT_TOKENS: int = 12000
    RETRIEVAL_TOP_K: int = 3          # Top K files after similarity ≥ 0.45 filter
    SIMILARITY_THRESHOLD: float = 0.45

    # File limits
    MAX_FILE_SIZE_MB: int = 500

    # Audio processing
    # Set to True to retain the original audio in MinIO after transcription.
    # False (default) deletes raw audio post-transcription to save storage —
    # the full transcript text is preserved in the DB and family_data JSONB.
    KEEP_AUDIO_RAW: bool = False

    # Transcript chunk size for audio files (in approximate tokens)
    # Whisper segments are merged until this budget is reached before creating a chunk.
    AUDIO_CHUNK_MAX_TOKENS: int = 300

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
