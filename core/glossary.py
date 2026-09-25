"""Glossary manager module - quản lý file glossary.txt."""

import json
import os
import re
from pathlib import Path


def load_glossary_txt(path):
    """Đọc file glossary.txt dạng 'CN -> EN'.
    
    Trả về list các dict: [{cn, en, type, banned, context}]
    """
    entries = []
    if not os.path.exists(path):
        return entries
    
    current_type = ""
    
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip()
            
            # Bỏ qua dòng trống
            if not line.strip():
                continue
            
            # Comment dạng "--- LOẠI (XXX) ---" => section header
            if line.strip().startswith('#') or line.strip().startswith('//'):
                # Thử parse section
                m = re.search(r'---\s*(.+?)\s*[\(\[]([^\)\]]+)[\)\]]\s*---', line)
                if m:
                    current_type = m.group(2).strip()
                continue
            
            # Parse "CN -> EN"
            if ' -> ' in line:
                parts = line.split(' -> ', 1)
                if len(parts) == 2:
                    cn = parts[0].strip()
                    en = parts[1].strip()
                    if cn and en:
                        entries.append({
                            "cn": cn,
                            "en": en,
                            "type": current_type,
                            "banned": "",
                            "context": "Any"
                        })
    
    return entries


def save_glossary_txt(path, entries, log_queue=None):
    """Ghi glossary.txt (chỉ CN -> EN, không metadata)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    
    lines = [
        "# ============================================================",
        "# GFL2 MASTER GLOSSARY (CN -> EN)",
        "# File này dùng cho Auto-translate. Metadata ở glossary_meta.json",
        "# ============================================================",
        ""
    ]
    
    # Nhóm theo type
    by_type = {}
    for e in entries:
        t = e.get("type") or "General"
        by_type.setdefault(t, []).append(e)
    
    for type_name in sorted(by_type.keys()):
        lines.append(f"# --- {type_name.upper()} ---")
        for e in by_type[type_name]:
            lines.append(f"{e['cn']} -> {e['en']}")
        lines.append("")
    
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write("\n".join(lines))
    
    if log_queue:
        log_queue.put(f"[OK] Đã lưu {len(entries):,} entries vào {path}")


def save_glossary_meta(path, entries, log_queue=None):
    """Ghi glossary_meta.json (đầy đủ metadata)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=2)
    
    if log_queue:
        log_queue.put(f"[OK] Đã lưu metadata vào {path}")


def load_glossary_meta(path):
    """Đọc glossary_meta.json. Fallback về [] nếu không có."""
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("entries", [])


def import_glossary_json(path, log_queue=None):
    """Đọc file glossary JSON."""
    if not os.path.exists(path):
        if log_queue:
            log_queue.put(f"[ERROR] Không tìm thấy: {path}")
        return []
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Hỗ trợ nhiều format
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict) and "entries" in data:
        entries = data["entries"]
    elif isinstance(data, dict) and "texts" in data:
        # Chuyển từ format texts → entries (không có type)
        entries = [{"cn": k, "en": v, "type": "", "banned": "", "context": "Any"}
                   for k, v in data["texts"].items()]
    else:
        if log_queue:
            log_queue.put("[ERROR] Format JSON không được hỗ trợ")
        return []
    
    # Chuẩn hóa các key
    normalized = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        normalized.append({
            "cn": e.get("cn") or e.get("CN") or "",
            "en": e.get("en") or e.get("EN") or "",
            "type": e.get("type") or "",
            "banned": e.get("banned") or "",
            "context": e.get("context") or "Any"
        })
    
    if log_queue:
        log_queue.put(f"[OK] Đã import {len(normalized):,} thuật ngữ")
    return normalized


def export_glossary_json(path, entries, log_queue=None):
    """Xuất glossary ra JSON."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=2)
    if log_queue:
        log_queue.put(f"[OK] Đã export {len(entries):,} thuật ngữ ra {path}")


def merge_glossaries(base_entries, new_entries):
    """Gộp 2 list, ưu tiên new_entries nếu trùng cn."""
    merged = {}
    for e in base_entries:
        merged[e["cn"]] = e
    for e in new_entries:
        merged[e["cn"]] = e  # Ghi đè
    return list(merged.values())


def audit_translations(glossary_entries, translations, cn_source=None, log_queue=None):
    """Quét file translations để tìm vi phạm glossary.
    
    Args:
        glossary_entries: List entries từ glossary
        translations: dict {hash: en_text} - file cần quét
        cn_source: dict {hash: cn_text} - file CN gốc (optional)
                   Nếu KHÔNG có → chỉ check banned (có thể false positive)
                   Nếu CÓ → check thêm cn_term có trong CN không (chính xác)
    
    Returns:
        list các vi phạm
    """
    violations = []
    
    # Build map cn_term -> entry
    glossary_map = {}
    for e in glossary_entries:
        if e["cn"] and e["en"]:
            glossary_map[e["cn"]] = e
    
    total = len(translations)
    if log_queue:
        log_queue.put(f"[INFO] Đang quét {total:,} câu với {len(glossary_map):,} thuật ngữ...")
        if cn_source:
            log_queue.put(f"[INFO] ✅ Có CN source ({len(cn_source):,} câu) → cross-reference")
        else:
            log_queue.put(f"[WARN] ⚠️ Không có CN source → chỉ check banned")
    
    for i, (hash_key, en_text) in enumerate(translations.items(), 1):
        if log_queue and i % 20000 == 0:
            log_queue.put(f"[PROGRESS] {i:,}/{total:,} câu")
        
        # Bỏ qua câu còn tiếng Trung
        if re.search(r'[\u4e00-\u9fff]', en_text):
            continue
        
        # Lấy CN gốc tương ứng (nếu có)
        cn_text = cn_source.get(hash_key, "") if cn_source else ""
        en_lower = en_text.lower()
        
        for cn_term, entry in glossary_map.items():
            banned_raw = entry.get("banned", "")
            if not banned_raw:
                continue
            
            # ⚡ CHECK 1: Nếu có CN source → chỉ check khi cn_term có trong CN
            if cn_source:
                if cn_term not in cn_text:
                    # CN gốc không chứa term này → bỏ qua (tránh false positive)
                    continue
            
            # ⚡ CHECK 2: Bản dịch EN có chứa banned term không?
            for banned in banned_raw.split(','):
                banned = banned.strip()
                if not banned:
                    continue
                
                # Word boundary check
                pattern = r'\b' + re.escape(banned.lower()) + r'\b'
                if re.search(pattern, en_lower):
                    violations.append({
                        "hash": hash_key,
                        "cn_text": cn_text,
                        "en_text": en_text,
                        "cn_term": cn_term,
                        "expected": entry["en"],
                        "violation_type": "BANNED",
                        "found": banned
                    })
                    break  # Chỉ báo 1 lần cho mỗi câu
    
    return violations