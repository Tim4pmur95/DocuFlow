import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 1. получаем URL базы данных из .env
DATABASE_URL = os.getenv("DATABASE_URL")

# 2. настраиваем движок подключения
if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
    # подключение к PostgreSQL в Docker
    engine = create_engine(DATABASE_URL)
else:
    # для локальных тестов: создаем SQLite в папке storage
    os.makedirs("/storage", exist_ok=True)
    FALLBACK_URL = "sqlite:////storage/docuflow.db"
    engine = create_engine(
        FALLBACK_URL, connect_args={"check_same_thread": False}
    )

# 3. создаем фабрику сессий (через нее мы будем делать запросы к БД)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. базовый класс для описания структуры таблиц
Base = declarative_base()

# 5. функция-зависимость для FastAPI чтобы безопасно открывать и закрывать соединение
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()