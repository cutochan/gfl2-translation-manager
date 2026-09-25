"""Auto-translate module - wrapper cho optimized_translate.py."""

import json
import os
import re
import asyncio
from pathlib import Path
from typing import Iterator

import aiohttp


FORMAT_TAG = "gfl2-langpackage-by-text-1"


def contains_chinese(text):
    if not text: return False
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def load_file_content(path, max_chars):
    if not path or not os.path.exists(path): return ""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()[:max_chars]


def build_system_prompt(style_file, glossary_file, style_max, glossary_max):
    prompt = (
        "Bạn là chuyên gia bản địa hóa game Girls' Frontline 2: Exilium. "
        "Dịch các giá trị tiếng Trung trong JSON sang tiếng Anh.\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. CHỈ trả về JSON hợp lệ.\n"
        "2. GIỮ NGUYÊN các key (mã hash 16 ký tự) - TUYỆT ĐỐI KHÔNG thay đổi chúng.\n"
        "3. Giữ nguyên các thẻ như {0}, %s, \\n, <color=...>.\n"
        "4. Không thêm, không bớt key."
    )
    style = load_file_content(style_file, style_max)
    if style:
        prompt += f"\n\n--- VĂN PHONG THAM KHẢO ---\n{style}"
    glossary = load_file_content(glossary_file, glossary_max)
    if glossary:
        prompt += f"\n\n--- THUẬT NGỮ BẮT BUỘC ---\n{glossary}"
    return prompt


async def call_api(session, api_key, system_prompt, user_content, model, retry=0, max_retries=3):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.3,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"}
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    try:
        async with session.post(
            "https://api.deepseek.com/chat/completions",
            json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=300)
        ) as response:
            result = await response.json()
            if "error" in result:
                raise Exception(f"API Error: {result['error']}")
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        if retry < max_retries:
            await asyncio.sleep(2 ** retry)
            return await call_api(session, api_key, system_prompt, user_content, model, retry + 1, max_retries)
        raise e


def clean_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


async def translate_batch(session, semaphore, api_key, system_prompt, batch_texts, model, log_queue, max_retries=3):
    async with semaphore:
        user_content = (
            f"Dịch {len(batch_texts)} câu sau (giữ nguyên các key hash):\n\n"
            f"```json\n{json.dumps({'texts': batch_texts}, ensure_ascii=False)}\n```"
        )
        try:
            content = await call_api(session, api_key, system_prompt, user_content, model, max_retries=max_retries)
            translated = json.loads(clean_json_response(content))
            
            if isinstance(translated, dict) and "texts" in translated:
                result = translated["texts"]
            elif isinstance(translated, dict) and "Data" in translated:
                result = translated["Data"]
            elif isinstance(translated, dict):
                result = translated
            else:
                raise Exception("Cấu trúc JSON không hợp lệ")
            
            return {k: v for k, v in result.items() if k in batch_texts and isinstance(v, str)}
        
        except json.JSONDecodeError:
            if len(batch_texts) > 10:
                await asyncio.sleep(1)
                items = list(batch_texts.items())
                mid = len(items) // 2
                r1 = await translate_batch(session, semaphore, api_key, system_prompt, dict(items[:mid]), model, log_queue, max_retries)
                r2 = await translate_batch(session, semaphore, api_key, system_prompt, dict(items[mid:]), model, log_queue, max_retries)
                r1.update(r2)
                return r1
            log_queue.put("   ❌ Lỗi parse JSON sau khi chia batch")
            return {}
        except Exception as e:
            log_queue.put(f"   ❌ Lỗi batch: {e}")
            return {}


async def _run_async(input_file, output_file, progress_file, style_file, glossary_file,
                     api_key, model, style_max, glossary_max, batch_size, concurrent,
                     max_retries, log_queue):
    """Chạy translate trong async context."""
    
    if not os.path.exists(input_file):
        log_queue.put(f"[ERROR] Không tìm thấy file: {input_file}")
        return
    
    log_queue.put(f"[INFO] Đang đọc file: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if "format" not in data or data.get("format") != FORMAT_TAG:
        log_queue.put(f"[ERROR] File không phải định dạng '{FORMAT_TAG}'.")
        log_queue.put(f"[ERROR] Format hiện tại: {data.get('format', '(không có)')}")
        return
    
    texts = data.get("texts", {})
    if not isinstance(texts, dict):
        log_queue.put("[ERROR] Trường 'texts' không hợp lệ.")
        return
    
    log_queue.put(f"[OK] Đã tải {len(texts)} câu từ file.")
    
    # Đọc tiến độ
    done_dict = {}
    if os.path.exists(progress_file):
        with open(progress_file, 'r', encoding='utf-8') as f:
            done_dict = json.load(f)
        log_queue.put(f"[OK] Đã tải tiến độ cũ: {len(done_dict)} câu.")
    
    # Tìm câu cần dịch
    missing_texts = {}
    for key, text in texts.items():
        if contains_chinese(text) and key not in done_dict:
            missing_texts[key] = text
    
    if not missing_texts:
        log_queue.put("[OK] Không còn câu nào cần dịch.")
    else:
        log_queue.put(f"[INFO] Cần dịch: {len(missing_texts)} câu.")
        
        items = list(missing_texts.items())
        batches = [dict(items[i:i+batch_size]) for i in range(0, len(items), batch_size)]
        log_queue.put(f"[INFO] Chia thành {len(batches)} batch.")
        
        system_prompt = build_system_prompt(style_file, glossary_file, style_max, glossary_max)
        log_queue.put(f"[OK] System prompt: {len(system_prompt)} ký tự.\n")
        
        semaphore = asyncio.Semaphore(concurrent)
        
        async with aiohttp.ClientSession() as session:
            tasks = [
                translate_batch(session, semaphore, api_key, system_prompt, b, model, log_queue, max_retries)
                for b in batches
            ]
            
            results = []
            completed = 0
            for coro in asyncio.as_completed(tasks):
                result = await coro
                results.append(result)
                completed += 1
                
                # Log tiến độ mỗi 5 batch
                if completed % 5 == 0 or completed == len(batches):
                    log_queue.put(f"[PROGRESS] {completed}/{len(batches)} batch hoàn thành")
                
                # Lưu tiến độ mỗi 10 batch
                if completed % 10 == 0:
                    updated = dict(done_dict)
                    for r in results:
                        updated.update(r)
                    with open(progress_file, 'w', encoding='utf-8') as f:
                        json.dump(updated, f, ensure_ascii=False)
        
        for r in results:
            done_dict.update(r)
    
    # Ghi kết quả
    output_texts = {}
    for key, text in texts.items():
        output_texts[key] = done_dict.get(key, text)
    
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({
            "format": FORMAT_TAG,
            "texts": output_texts
        }, f, ensure_ascii=False, indent=2)
    
    still_chinese = sum(1 for v in output_texts.values() if contains_chinese(v))
    log_queue.put("")
    log_queue.put("=" * 60)
    log_queue.put("[DONE] HOÀN TẤT!")
    log_queue.put("=" * 60)
    log_queue.put(f"[INFO] Tổng số câu: {len(output_texts)}")
    log_queue.put(f"[WARN] Còn tiếng Trung: {still_chinese}")
    log_queue.put(f"[DONE] File kết quả: {output_file}")
    
    if os.path.exists(progress_file) and still_chinese == 0:
        os.remove(progress_file)
        log_queue.put("[INFO] Đã xóa file tiến độ.")


def run_auto_translate(input_file, output_file, progress_file, style_file, glossary_file,
                       api_key, model, style_max, glossary_max, batch_size, concurrent,
                       max_retries, log_queue):
    """Wrapper chạy async translate, giao tiếp qua queue."""
    try:
        asyncio.run(_run_async(
            input_file, output_file, progress_file, style_file, glossary_file,
            api_key, model, style_max, glossary_max, batch_size, concurrent,
            max_retries, log_queue
        ))
    except Exception as e:
        log_queue.put(f"[ERROR] {e}")
        import traceback
        log_queue.put(traceback.format_exc())
    finally:
        log_queue.put("__DONE__")