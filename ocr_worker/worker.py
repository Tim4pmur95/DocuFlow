import time
import io
import os
import zipfile
import json
import logging
import sys
import cv2
import numpy as np
import PyPDF2
import pytesseract
import pandas as pd
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color
from pdf2image import convert_from_path
import pdfplumber
from deep_translator import GoogleTranslator
from rq import get_current_job
from pix2tex.cli import LatexOCR
from docx import Document
from docx.shared import Inches
from pdf2docx import Converter

from database import SessionLocal, DocumentTask

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

logger.info("Загрузка весов нейросети Pix2Tex...")
math_model = LatexOCR()
logger.info("Системы воркера готовы к работе!")

def route_task(tool_id, file_paths, boxes=None, extra_param=None):
    """Главный диспетчер задач: определяет функцию обработки по tool_id."""
    job = get_current_job()
    db = SessionLocal()
    task = db.query(DocumentTask).filter(DocumentTask.id == job.id).first()
    if task:
        task.status = "processing"
        db.commit()
    
    logger.info(f"Задача {job.id} начала выполнение. Инструмент: {tool_id}")
    
    try:
        # Словарь маршрутизации
        tasks = {
            'ocr_manual': lambda: do_ocr_manual(job.id, file_paths[0], boxes),
            'ocr_text': lambda: do_ocr_text(job.id, file_paths[0]),
            'ocr_math': lambda: do_ocr_math(job.id, file_paths[0]),
            'pdf_merge': lambda: do_pdf_merge(job.id, file_paths),
            'img_to_pdf': lambda: do_img_to_pdf(job.id, file_paths),
            'pdf_to_word': lambda: do_pdf_to_word(job.id, file_paths[0]),
            'pdf_split': lambda: do_pdf_split(job.id, file_paths[0]),
            'pdf_compress': lambda: do_pdf_compress(job.id, file_paths[0]),
            'pdf_protect': lambda: do_pdf_protect(job.id, file_paths[0], extra_param),
            'pdf_unprotect': lambda: do_pdf_unprotect(job.id, file_paths[0], extra_param),
            'pdf_rotate': lambda: do_pdf_rotate(job.id, file_paths[0], extra_param),
            'pdf_delete': lambda: do_pdf_delete_pages(job.id, file_paths[0], extra_param),
            'pdf_to_excel': lambda: do_pdf_to_excel(job.id, file_paths[0]),
            'pdf_watermark': lambda: do_pdf_watermark(job.id, file_paths[0], extra_param),
            'ocr_translate': lambda: do_ocr_translate(job.id, file_paths[0], extra_param),
        }
        
        result = tasks[tool_id]()
        
        if task:
            task.status = "completed"
            task.extracted_text = result
            db.commit()
        logger.info(f"Задача {job.id} успешно завершена.")
        return result

    except Exception as e:
        logger.error(f"Ошибка в задаче {job.id}: {str(e)}", exc_info=True)
        if task:
            task.status = "error"
            task.extracted_text = str(e)
            db.commit()
        return str(e)
    finally:
        db.close()

# обычный текст
def do_ocr_text(job_id, file_path):
    print(f"[{time.strftime('%X')}] Запуск OCR (Сплошной текст)...")
    
    ext = file_path.lower().split('.')[-1]
    full_text = ""
    
    # PDF (скан или обычный)
    if ext == 'pdf':
        print(" -> Обработка PDF через pdf2image...")
        images = convert_from_path(file_path)
        for i, img in enumerate(images):
            print(f" -> Распознавание страницы {i+1} из {len(images)}...")
            full_text += pytesseract.image_to_string(img, lang='rus+eng') + "\n\n"
    #  картинка
    else:
        img = Image.open(file_path)
        full_text = pytesseract.image_to_string(img, lang='rus+eng')
        
    full_text = full_text.strip()
    if not full_text:
        raise Exception("Не удалось распознать текст на документе.")
        
    # сохраняем в Word
    doc = Document()
    doc.add_heading('Распознанный текст', 1)
    doc.add_paragraph(full_text)
    
    output_path = os.path.join("/app/storage", f"{job_id}.docx")
    doc.save(output_path)
    
    return full_text

# формулы
def do_ocr_math(job_id, file_path):
    img = Image.open(file_path)
    extracted_text = math_model(img)

    doc = Document()
    doc.add_heading('Распознанная формула (LaTeX)', 0)
    p = doc.add_paragraph()
    run = p.add_run(extracted_text)
    run.font.name = 'Courier New'
    doc.save(os.path.join("/app/storage", f"{job_id}.docx"))
    return extracted_text
def do_pdf_merge(job_id, file_paths):
    print(f"[{time.strftime('%X')}] Начинаю объединение {len(file_paths)} PDF файлов...")
    
    merger = PyPDF2.PdfMerger()
    
    #  каждый файл по очереди в склейку
    for path in file_paths:
        if path.lower().endswith('.pdf'):
            merger.append(path)
        else:
            raise Exception(f"Файл {path} не является PDF!")
            
    # сохраняем 
    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    merger.write(output_path)
    merger.close()
    
    print(f"[{time.strftime('%X')}] PDF файлы успешно объединены!")
    return "Файлы успешно объединены в один PDF-документ."

# картинка в пдф
def do_img_to_pdf(job_id, file_paths):
    print(f"[{time.strftime('%X')}] Конвертирую {len(file_paths)} фото в PDF...")
    
    image_list = []
    # первая картинка
    first_image = Image.open(file_paths[0]).convert('RGB')
    
    # остальные картинки
    for path in file_paths[1:]:
        img = Image.open(path).convert('RGB')
        image_list.append(img)
        
    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    
    # склеиваем всё в один PDF 
    first_image.save(output_path, save_all=True, append_images=image_list)
    print(f"[{time.strftime('%X')}] PDF из картинок успешно создан!")
    return "Изображения успешно конвертированы в PDF."

# пдф в ворд
def do_pdf_to_word(job_id, file_path):
    print(f"[{time.strftime('%X')}] Конвертирую PDF в Word...")
    
    if not file_path.lower().endswith('.pdf'):
        raise Exception("Пожалуйста, загрузите файл формата PDF.")
        
    output_path = os.path.join("/app/storage", f"{job_id}.docx")
    
    cv = Converter(file_path)
    cv.convert(output_path)      
    cv.close()
    
    print(f"[{time.strftime('%X')}] Конвертация PDF -> DOCX завершена!")
    return "PDF успешно конвертирован в редактируемый Word документ."

# пдф раздедение на страницы
def do_pdf_split(job_id, file_path):
    print(f"[{time.strftime('%X')}] Начинаю разделение PDF на страницы...")
    
    reader = PyPDF2.PdfReader(file_path)
    zip_path = os.path.join("/app/storage", f"{job_id}.zip")
    
    #  зип-архив
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # проходимся по каждой странице
        for i in range(len(reader.pages)):
            writer = PyPDF2.PdfWriter()
            writer.add_page(reader.pages[i])
            
            # сохраняем одну страницу во временный файл
            temp_page_path = os.path.join("/app/storage", f"temp_page_{i+1}.pdf")
            with open(temp_page_path, "wb") as f:
                writer.write(f)
                
            # страницу в архив и удаляем временный файл
            zipf.write(temp_page_path, arcname=f"page_{i+1}.pdf")
            os.remove(temp_page_path)
            
    print(f"[{time.strftime('%X')}] PDF успешно разделен и упакован в ZIP!")
    return f"Документ разделен на {len(reader.pages)} страниц(ы)."

# сжатие пдф
def do_pdf_compress(job_id, file_path):
    print(f"[{time.strftime('%X')}] Начинаю сжатие PDF...")
    
    reader = PyPDF2.PdfReader(file_path)
    writer = PyPDF2.PdfWriter()

    for page in reader.pages:
        
        page.compress_content_streams()
        writer.add_page(page)

    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    with open(output_path, "wb") as f:
        writer.write(f)
        
    print(f"[{time.strftime('%X')}] PDF успешно сжат!")
    return "Размер PDF-документа был оптимизирован."

def do_ocr_manual(job_id, file_path, boxes_json):
    print(f"[{time.strftime('%X')}] Запуск ручной разметки (Режим: Картинки + Текст)...")
    
    image = cv2.imread(file_path)
    math_boxes = []
    
    if boxes_json:
        math_boxes = json.loads(boxes_json)
        
    math_boxes = sorted(math_boxes, key=lambda b: b['y'])
    
    doc = Document()
    doc.add_heading('Результат ручной разметки', 1)
    
    current_y = 0
    
    for idx, box in enumerate(math_boxes):
        bx, by, bw, bh = box['x'], box['y'], box['w'], box['h']
        
        # текст до рамки
        if by > current_y:
            text_roi = image[current_y:by, 0:image.shape[1]]
            if text_roi.shape[0] > 15:
                text_path = f"/app/storage/temp_text_{job_id}_{idx}.png"
                cv2.imwrite(text_path, text_roi)
                text_line = pytesseract.image_to_string(Image.open(text_path), lang='rus+eng', config='--oem 3 --psm 6').strip()
                if len(text_line) > 2:
                    doc.add_paragraph(text_line)
                if os.path.exists(text_path): os.remove(text_path)
                
        # вырез рамку, вставляем картинкой
        math_roi = image[by:by+bh, bx:bx+bw]
        math_path = f"/app/storage/temp_img_{job_id}_{idx}.png"
        cv2.imwrite(math_path, math_roi)
        try:
            print(f" -> Вставка рамки {idx} как картинки")
            doc.add_paragraph()
            doc.add_picture(math_path, width=Inches(4.0))
        except Exception as e:
            print(f"Ошибка вставки картинки: {e}")
            
        if os.path.exists(math_path): os.remove(math_path)
            
        current_y = by + bh
        
    if current_y < image.shape[0]:
        tail_roi = image[current_y:image.shape[0], 0:image.shape[1]]
        if tail_roi.shape[0] > 15:
            tail_path = f"/app/storage/temp_tail_{job_id}.png"
            cv2.imwrite(tail_path, tail_roi)
            text_line = pytesseract.image_to_string(Image.open(tail_path), lang='rus+eng', config='--oem 3 --psm 6').strip()
            if len(text_line) > 2:
                doc.add_paragraph(text_line)
            if os.path.exists(tail_path): os.remove(tail_path)
            
    output_path = os.path.join("/app/storage", f"{job_id}.docx")
    doc.save(output_path)
    
    return "Документ размечен вручную. Зоны сохранены как изображения."
def do_pdf_protect(job_id, file_path, password):
    if not password:
        raise Exception("Не указан пароль для защиты!")
        
    reader = PyPDF2.PdfReader(file_path)
    writer = PyPDF2.PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
        
    writer.encrypt(password) # Шифруем документ
    
    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    with open(output_path, "wb") as f:
        writer.write(f)
        
    return f"PDF успешно зашифрован. Пароль: {password}"

def do_pdf_unprotect(job_id, file_path, password):
    if not password:
        raise Exception("Не указан пароль для снятия защиты!")
        
    reader = PyPDF2.PdfReader(file_path)
    
    if reader.is_encrypted:
        try:
            reader.decrypt(password) # Пытаемся взломать переданным паролем
        except:
            raise Exception("Неверный пароль!")
            
    writer = PyPDF2.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
        
    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    with open(output_path, "wb") as f:
        writer.write(f)
        
    return "Защита с PDF успешно снята. Файл открыт."
def do_pdf_rotate(job_id, file_path, angle_str):
    # по умолчанию 90 градусов
    angle = int(angle_str) if angle_str and angle_str.isdigit() else 90
    
    reader = PyPDF2.PdfReader(file_path)
    writer = PyPDF2.PdfWriter()
    
    for page in reader.pages:
        page.rotate(angle)
        writer.add_page(page)
        
    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    with open(output_path, "wb") as f:
        writer.write(f)
        
    return f"Все страницы успешно повернуты на {angle} градусов."

def do_pdf_delete_pages(job_id, file_path, pages_str):
    if not pages_str:
        raise Exception("Укажите страницы для удаления (например: 1, 3, 5-7)")
        
    pages_to_delete = set()
    parts = pages_str.replace(" ", "").split(",")
    for part in parts:
        if "-" in part:
            try:
                start, end = part.split("-")
                pages_to_delete.update(range(int(start), int(end) + 1))
            except:
                pass # Игнорируем ошибки ввода
        elif part.isdigit():
            pages_to_delete.add(int(part))
            
    reader = PyPDF2.PdfReader(file_path)
    writer = PyPDF2.PdfWriter()
    
    for i, page in enumerate(reader.pages):
        if (i + 1) not in pages_to_delete:
            writer.add_page(page)
            
    if len(writer.pages) == 0:
        raise Exception("Вы удалили все страницы! Документ пуст.")
        
    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    with open(output_path, "wb") as f:
        writer.write(f)
        
    return "Выбранные страницы успешно удалены."

def do_pdf_to_excel(job_id, file_path):
    print(f"[{time.strftime('%X')}] Запуск извлечения таблиц (PDF в Excel)...")
    output_path = os.path.join("/app/storage", f"{job_id}.xlsx")
    
    tables_found = 0
    
    with pdfplumber.open(file_path) as pdf:
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                
                for j, table in enumerate(tables):
                    if table:
                        tables_found += 1
                        df = pd.DataFrame(table)
                        
                        sheet_name = f"Стр_{i+1}_Таб_{j+1}"
                        df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
                        
    if tables_found == 0:
        raise Exception("В документе не найдено ни одной таблицы!")
        
    return f"Успешно! Извлечено таблиц: {tables_found}."

def do_pdf_watermark(job_id, file_path, watermark_text):
    if not watermark_text:
        watermark_text = "CONFIDENTIAL"
        
    
    packet = io.BytesIO()
    can = canvas.Canvas(packet)
    
    can.setFont("Helvetica-Bold", 60)
    can.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.3)) 
    
    can.translate(250, 400)
    can.rotate(45)
    can.drawCentredString(0, 0, watermark_text)
    can.save()
    
    packet.seek(0)
    watermark_pdf = PyPDF2.PdfReader(packet)
    watermark_page = watermark_pdf.pages[0]
    
    reader = PyPDF2.PdfReader(file_path)
    writer = PyPDF2.PdfWriter()
    
    for page in reader.pages:
        page.merge_page(watermark_page) # <-- Само наложение слоев!
        writer.add_page(page)
        
    output_path = os.path.join("/app/storage", f"{job_id}.pdf")
    with open(output_path, "wb") as f:
        writer.write(f)
        
    return f"Водяной знак '{watermark_text}' успешно наложен на все страницы."

def do_ocr_translate(job_id, file_path, target_lang):
    # англ по умолчанию
    if not target_lang:
        target_lang = 'en'
    target_lang = target_lang.strip().lower()

    print(f"[{time.strftime('%X')}] Запуск извлечения и перевода на '{target_lang}'...")

    original_text = ""
    ext = file_path.lower().split('.')[-1]

    # извлечение в зависимости от типа файла
    try:
        if ext == 'pdf':
            # достать цифровой текст 
            reader = PyPDF2.PdfReader(file_path)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    original_text += text + "\n"
            
            # если текст не нашли, длина меньше 10 - скан
            if len(original_text.strip()) < 10:
                print(f"[{time.strftime('%X')}] Цифровой текст не найден. Запуск OCR для отсканированного PDF...")
                original_text = "" # очищаем мусор
                images = convert_from_path(file_path) # режем PDF на картинки
                for i, img in enumerate(images):
                    print(f" -> Распознавание страницы {i+1} из {len(images)}...")
                    page_text = pytesseract.image_to_string(img, lang='rus+eng')
                    original_text += page_text + "\n\n"
        else:
            # если это не PDF и не DOCX, считаем, что это картинка
            img = Image.open(file_path)
            original_text = pytesseract.image_to_string(img, lang='rus+eng').strip()
    except Exception as e:
        raise Exception(f"Ошибка чтения файла: {e}")

    original_text = original_text.strip()
    if len(original_text) < 2:
        raise Exception("Не удалось найти текст. Если это PDF, возможно, он отсканирован как картинка без текстового слоя.")

    # перевод
    chunk_size = 4000 
    chunks = [original_text[i:i+chunk_size] for i in range(0, len(original_text), chunk_size)]
    translated_text = ""
    
    translator = GoogleTranslator(source='auto', target=target_lang)
    
    try:
        for i, chunk in enumerate(chunks):
            print(f" -> Перевод части {i+1} из {len(chunks)}...")
            translated_text += translator.translate(chunk) + "\n"
    except Exception as e:
        raise Exception(f"Ошибка переводчика: {e}. Проверьте код языка (например: en, ru, de).")

    # сохраняем
    doc_out = Document()
    doc_out.add_heading('Оригинальный текст', 1)
    doc_out.add_paragraph(original_text)
    
    doc_out.add_heading(f'Перевод ({target_lang})', 1)
    doc_out.add_paragraph(translated_text.strip())

    output_path = os.path.join("/app/storage", f"{job_id}.docx")
    doc_out.save(output_path)

    preview = translated_text[:200] + "..." if len(translated_text) > 200 else translated_text
    return f"Текст ({len(original_text)} симв.) переведен на [{target_lang}]:\n{preview}"