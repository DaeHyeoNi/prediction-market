from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    pool_size=10,
    max_overflow=0,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)
