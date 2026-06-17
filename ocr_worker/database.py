import os
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base

# 1. Получаем URL базы данных из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Настраиваем движок подключения
if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
    engine = create_engine(DATABASE_URL)
else:
    os.makedirs("/storage", exist_ok=True)
    FALLBACK_URL = "sqlite:////storage/docuflow.db"
    engine = create_engine(
        FALLBACK_URL, connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

#фикс
class DocumentTask(Base):
    __tablename__ = "document_tasks"

    #  id - сгенерированный UUID
    id = Column(String, primary_key=True, index=True)
    #  status -  состояние задачи
    status = Column(String, default="pending")
    #  extracted_text -  результаты распознавания или текст ошибки
    extracted_text = Column(Text, nullable=True)

#  создаем таблицы в базе данных при запуске
Base.metadata.create_all(bind=engine)

# функция-зависимость для безопасного открытия и закрытия сессий
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
