"""Backup & Utilities module."""

import os
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path


def get_system_info(log_queue=None):
    """Lấy thông tin hệ thống."""
    info = {
        "translations_files": 0,
        "translations_size_mb": 0.0,
        "glossary_count": 0,
        "total_translated": 0,
        "still_chinese": 0,
        "output_exists": False,
        "output_size_mb": 0.0,
    }
    
    # Scan translations folder
    tdir = Path("translations")
    if tdir.exists():
        json_files = list(tdir.glob("*.json"))
        info["translations_files"] = len(json_files)
        
        total_size = sum(f.stat().st_size for f in json_files)
        info["translations_size_mb"] = total_size / (1024 * 1024)
        
        # Đếm số câu
        total = 0
        chinese = 0
        import re
        for jf in json_files:
            try:
                with open(jf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                texts = data.get("texts", {})
                total += len(texts)
                for v in texts.values():
                    if re.search(r'[\u4e00-\u9fff]', v):
                        chinese += 1
            except Exception:
                pass
        
        info["total_translated"] = total
        info["still_chinese"] = chinese
    
    # Glossary
    if os.path.exists("glossary_meta.json"):
        try:
            with open("glossary_meta.json", 'r', encoding='utf-8') as f:
                data = json.load(f)
            info["glossary_count"] = len(data.get("entries", []))
        except Exception:
            pass
    elif os.path.exists("glossary.txt"):
        try:
            with open("glossary.txt", 'r', encoding='utf-8') as f:
                info["glossary_count"] = sum(1 for l in f if ' -> ' in l)
        except Exception:
            pass
    
    # Output
    out_dir = Path("output")
    if out_dir.exists():
        out_files = list(out_dir.glob("*.bytes"))
        if out_files:
            info["output_exists"] = True
            info["output_size_mb"] = out_files[0].stat().st_size / (1024 * 1024)
    
    if log_queue:
        log_queue.put(f"[INFO] Translations: {info['translations_files']} files, {info['translations_size_mb']:.2f} MB")
        log_queue.put(f"[INFO] Tổng số câu: {info['total_translated']:,} ({info['still_chinese']:,} còn tiếng Trung)")
        log_queue.put(f"[INFO] Glossary: {info['glossary_count']:,} entries")
    
    return info


def create_backup(log_queue=None):
    """Nén thư mục translations + glossary + output thành file zip."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.zip"
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / backup_name
    
    try:
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 1. translations/
            tdir = Path("translations")
            if tdir.exists():
                for f in tdir.glob("*.json"):
                    zf.write(f, f"translations/{f.name}")
                    if log_queue:
                        log_queue.put(f"[OK] + translations/{f.name}")
            
            # 2. glossary files
            for gfile in ["glossary.txt", "glossary_meta.json"]:
                if os.path.exists(gfile):
                    zf.write(gfile, gfile)
                    if log_queue:
                        log_queue.put(f"[OK] + {gfile}")
            
            # 3. output/
            out_dir = Path("output")
            if out_dir.exists():
                for f in out_dir.glob("*.bytes"):
                    zf.write(f, f"output/{f.name}")
                    if log_queue:
                        log_queue.put(f"[OK] + output/{f.name}")
        
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        if log_queue:
            log_queue.put(f"[DONE] Backup thành công: {backup_path} ({size_mb:.2f} MB)")
        
        return str(backup_path)
    except Exception as e:
        if log_queue:
            log_queue.put(f"[ERROR] Backup thất bại: {e}")
        return None


def restore_backup(zip_path, log_queue=None):
    """Giải nén backup, ghi đè file hiện tại."""
    if not os.path.exists(zip_path):
        if log_queue:
            log_queue.put(f"[ERROR] Không tìm thấy: {zip_path}")
        return False
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Kiểm tra an toàn (không có path traversal)
            for name in zf.namelist():
                if ".." in name or name.startswith("/"):
                    if log_queue:
                        log_queue.put(f"[ERROR] File zip chứa path không an toàn: {name}")
                    return False
            
            # Giải nén
            extracted = zf.namelist()
            zf.extractall(".")
            
            if log_queue:
                log_queue.put(f"[OK] Đã restore {len(extracted)} files từ {zip_path}")
                for name in extracted:
                    log_queue.put(f"[OK] + {name}")
        
        return True
    except Exception as e:
        if log_queue:
            log_queue.put(f"[ERROR] Restore thất bại: {e}")
        return False


def list_backups():
    """Liệt kê các file backup."""
    backup_dir = Path("backups")
    if not backup_dir.exists():
        return []
    
    backups = []
    for f in sorted(backup_dir.glob("*.zip"), reverse=True):
        size_mb = f.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        backups.append({
            "name": f.name,
            "path": str(f),
            "size_mb": size_mb,
            "modified": mtime
        })
    return backups


def export_all_translations(output_path, log_queue=None):
    """Gộp tất cả file translations/*.json thành 1 file JSON."""
    tdir = Path("translations")
    if not tdir.exists():
        if log_queue:
            log_queue.put("[ERROR] Không có thư mục translations/")
        return False
    
    merged = {}
    json_files = sorted(tdir.glob("*.json"))
    
    if log_queue:
        log_queue.put(f"[INFO] Đang gộp {len(json_files)} files...")
    
    for jf in json_files:
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                data = json.load(f)
            texts = data.get("texts", {})
            for k, v in texts.items():
                if k not in merged:  # Ưu tiên file sau (đã dịch)
                    merged[k] = v
                else:
                    merged[k] = v  # Ghi đè
            if log_queue:
                log_queue.put(f"[OK] + {jf.name} ({len(texts):,} câu)")
        except Exception as e:
            if log_queue:
                log_queue.put(f"[WARN] Bỏ qua {jf.name}: {e}")
    
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({
            "format": "gfl2-langpackage-by-text-1",
            "texts": merged
        }, f, ensure_ascii=False, indent=2)
    
    if log_queue:
        log_queue.put(f"[DONE] Đã gộp {len(merged):,} câu vào {output_path}")
    
    return True


def clear_temp_files(log_queue=None):
    """Xóa các file tạm: progress, violations, corrections log."""
    temp_files = [
        "translation_progress.json",
        "glossary_violations.json",
        "corrections_log.json",
        "suspicious_translations.json",
    ]
    
    deleted = 0
    for fname in temp_files:
        if os.path.exists(fname):
            try:
                os.remove(fname)
                if log_queue:
                    log_queue.put(f"[OK] Đã xóa {fname}")
                deleted += 1
            except Exception as e:
                if log_queue:
                    log_queue.put(f"[WARN] Không xóa được {fname}: {e}")
    
    if deleted == 0 and log_queue:
        log_queue.put("[INFO] Không có file tạm nào.")