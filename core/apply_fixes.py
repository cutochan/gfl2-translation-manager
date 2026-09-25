"""Apply corrections module."""

import json
import os
import shutil
from datetime import datetime


def contains_chinese(text):
    if not text: return False
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def run_apply_fixes(corrections_file, translated_file, auto_backup, log_queue):
    """Áp dụng sửa lỗi từ corrections_file vào translated_file."""
    try:
        log_queue.put("[INFO] Đang tải dữ liệu...\n")
        
        if not os.path.exists(corrections_file):
            log_queue.put(f"[ERROR] Không tìm thấy: {corrections_file}")
            return
        if not os.path.exists(translated_file):
            log_queue.put(f"[ERROR] Không tìm thấy: {translated_file}")
            return
        
        with open(corrections_file, 'r', encoding='utf-8') as f:
            corrections_data = json.load(f)
        with open(translated_file, 'r', encoding='utf-8') as f:
            translated_data = json.load(f)
        
        if "texts" not in translated_data:
            log_queue.put(f"[ERROR] File translated không đúng định dạng.")
            return
        
        translated_texts = translated_data["texts"]
        corrections_texts = corrections_data.get("texts", {})
        
        if not corrections_texts:
            log_queue.put("[ERROR] File corrections không có dữ liệu.")
            return
        
        log_queue.put(f"[OK] Corrections: {len(corrections_texts)} câu")
        log_queue.put(f"[OK] Translated: {len(translated_texts)} câu\n")
        
        # Backup
        if auto_backup:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{translated_file}.backup_{timestamp}"
            shutil.copy2(translated_file, backup_path)
            log_queue.put(f"[INFO] Đã sao lưu: {backup_path}\n")
        
        # Apply
        applied = 0
        skipped_no_change = 0
        skipped_not_found = 0
        skipped_still_chinese = 0
        changes_log = []
        
        for hash_key, data in corrections_texts.items():
            cn_text = data.get("CN", "")
            new_en = data.get("EN", "")
            old_en = translated_texts.get(hash_key, "")
            
            if hash_key not in translated_texts:
                skipped_not_found += 1
                continue
            
            if not new_en or new_en.strip() == "" or contains_chinese(new_en):
                skipped_still_chinese += 1
                continue
            
            if old_en == new_en:
                skipped_no_change += 1
                continue
            
            translated_texts[hash_key] = new_en
            applied += 1
            changes_log.append({
                "hash": hash_key,
                "CN": cn_text[:50] + ("..." if len(cn_text) > 50 else ""),
                "OLD_EN": old_en[:50] + ("..." if len(old_en) > 50 else ""),
                "NEW_EN": new_en[:50] + ("..." if len(new_en) > 50 else "")
            })
        
        # Save
        with open(translated_file, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(translated_data, f, ensure_ascii=False, indent=2)
        
        log_queue.put("=" * 60)
        log_queue.put("[DONE] ÁP DỤNG SỬA LỖI HOÀN TẤT!")
        log_queue.put("=" * 60)
        log_queue.put(f"[OK] Đã sửa: {applied} câu")
        log_queue.put(f"[INFO] Không đổi: {skipped_no_change}")
        log_queue.put(f"[WARN] Không tìm thấy: {skipped_not_found}")
        log_queue.put(f"[WARN] Chưa sửa: {skipped_still_chinese}")
        
        if changes_log:
            log_queue.put("")
            log_queue.put("[INFO] Chi tiết (tối đa 10 dòng đầu):")
            for i, ch in enumerate(changes_log[:10], 1):
                log_queue.put(f"  {i}. {ch['CN']}")
                log_queue.put(f"     CŨ: {ch['OLD_EN']}")
                log_queue.put(f"     MỚI: {ch['NEW_EN']}")
        
        # Save log
        log_file = "corrections_log.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "total_applied": applied,
                "changes": changes_log
            }, f, ensure_ascii=False, indent=2)
        log_queue.put(f"\n[INFO] Log lưu tại: {log_file}")
        
    except Exception as e:
        log_queue.put(f"[ERROR] {e}")
        import traceback
        log_queue.put(traceback.format_exc())
    finally:
        log_queue.put("__DONE__")