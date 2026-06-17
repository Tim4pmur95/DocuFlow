import os
import uuid
import asyncio
import time
import logging
import sys
import shutil
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, HTMLResponse
from redis import Redis
from rq import Queue

from database import SessionLocal, DocumentTask

#  логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Document Analyzer API")

#  переменные окружения для подключения к Redis
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_conn = Redis(host=REDIS_HOST, port=REDIS_PORT)

# стандартная очередь для простоты маршрутизации
task_queue = Queue('default', connection=redis_conn)

# фикс
STORAGE_DIR = "/storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Отдает клиенту главный HTML-интерфейс приложения."""
    logger.info("Пользователь открыл главную страницу.")
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

# фикс маршруты для PWA (Manifest и Service Worker)
@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("manifest.json")

@app.get("/sw.js")
async def get_sw():
    return FileResponse("sw.js")

@app.post("/upload/")
async def upload_document(files: List[UploadFile] = File(...), tool_id: str = Form(...), 
                          boxes: Optional[str] = Form(None), extra_param: Optional[str] = Form(None)):
    """Принимает файлы, сохраняет в хранилище и ставит задачу в очередь Redis."""
    file_paths = []
    for file in files:
        unique_filename = f"{uuid.uuid4()}.{file.filename.split('.')[-1].lower()}"
        file_path = os.path.join(STORAGE_DIR, unique_filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_paths.append(file_path)
        
    job = task_queue.enqueue('worker.route_task', tool_id, file_paths, boxes, extra_param)
    
    db = SessionLocal()
    # фикс минус filename т.к. его нет в модели БД
    new_task = DocumentTask(id=job.id, status="pending")
    db.add(new_task)
    db.commit()
    db.close()
    
    logger.info(f"Задача {job.id} создана для инструмента {tool_id}")
    return {"message": "В обработке!", "job_id": job.id}

@app.get("/task/{job_id}")
async def get_task_status(job_id: str):
    """Возвращает текущий статус задачи из базы данных."""
    db = SessionLocal()
    task = db.query(DocumentTask).filter(DocumentTask.id == job_id).first()
    db.close()
    if not task:
        logger.warning(f"Попытка доступа к несуществующей задаче: {job_id}")
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return {"job_id": task.id, "status": task.status, "extracted_text": task.extracted_text}

@app.get("/download/{job_id}")
async def download_result(job_id: str):
    """Формирует HTTP-ответ с результатом обработки (файл)."""
    for ext in ["pdf", "docx", "zip", "xlsx"]:
        path = os.path.join(STORAGE_DIR, f"{job_id}.{ext}")
        if os.path.exists(path):
            logger.info(f"Отправка файла пользователю: {path}")
            return FileResponse(path, filename=f"result_{job_id}.{ext}")
    
    logger.error(f"Файл для задачи {job_id} не найден.")
    raise HTTPException(status_code=404, detail="Файл еще не готов или не существует")

async def clean_old_files():
    """Фоновая функция (Garbage Collector) для удаления старых файлов из хранилища."""
    while True:
        now = time.time()
        for filename in os.listdir(STORAGE_DIR):
            file_path = os.path.join(STORAGE_DIR, filename)
            if os.stat(file_path).st_mtime < now - 3600:
                try:
                    os.remove(file_path)
                    logger.info(f"GC: Удален устаревший файл -> {filename}")
                except Exception as e:
                    logger.error(f"GC: Ошибка удаления {filename}: {e}")
        await asyncio.sleep(1800)

@app.on_event("startup")
async def startup_event():
    logger.info("Запуск API сервера и фоновых задач...")
    asyncio.create_task(clean_old_files())
