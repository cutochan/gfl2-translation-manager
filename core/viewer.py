"""Translation Viewer - SQLite in-memory view layer cho JSON translations."""

import json
import os
import re
import sqlite3
import csv
from pathlib import Path


class TranslationViewerDB:
    """SQLite in-memory DB để query và edit translations."""
    
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)   # ← THÊM
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
        self.loaded_files = []   # Danh sách file đã load
    
    def _init_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE NOT NULL,
                source_cn TEXT NOT NULL,
                target_en TEXT NOT NULL,
                frequency INTEGER DEFAULT 0,
                source_type TEXT DEFAULT 'matched',
                source_file TEXT
            )
        """)
        # Bảng tham chiếu CN gốc
        cur.execute("""
            CREATE TABLE cn_reference (
                hash TEXT PRIMARY KEY,
                source_cn TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX idx_hash ON translations(hash)")
        cur.execute("CREATE INDEX idx_cn ON translations(source_cn)")
        cur.execute("CREATE INDEX idx_en ON translations(target_en)")
        self.conn.commit()

    def load_cn_reference(self, path, log_queue=None):
        """Load file CN source (export từ tab Find Errors) để map hash → CN gốc."""
        if not os.path.exists(path):
            if log_queue:
                log_queue.put(f"[WARN] Không tìm thấy CN reference: {path}")
            return 0
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            if log_queue:
                log_queue.put(f"[ERROR] Lỗi đọc {path}: {e}")
            return 0
        
        texts = data.get("texts", {})
        if not texts:
            return 0
        
        cur = self.conn.cursor()
        for hash_key, cn_text in texts.items():
            cur.execute(
                "INSERT OR REPLACE INTO cn_reference (hash, source_cn) VALUES (?, ?)",
                (hash_key, cn_text)
            )
        self.conn.commit()
        
        if log_queue:
            log_queue.put(f"[OK] Load {len(texts):,} CN reference entries từ {os.path.basename(path)}")
        return len(texts)
    
    def load_file(self, path, log_queue=None):
        if not os.path.exists(path):
            if log_queue:
                log_queue.put(f"[WARN] Không tìm thấy: {path}")
            return 0
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            if log_queue:
                log_queue.put(f"[ERROR] Lỗi đọc {path}: {e}")
            return 0
        
        texts = data.get("texts", {})
        if not texts:
            return 0
        
        fname = os.path.basename(path)
        if fname == "base.json":
            stype = "base"
        elif fname.startswith("update-") and "translated" not in fname:
            stype = "update"
        elif "translated" in fname:
            stype = "translated"
        else:
            stype = "other"
        
        cur = self.conn.cursor()
        inserted = 0
        updated = 0
        
        for hash_key, text in texts.items():
            # Ưu tiên lấy CN từ reference
            cur.execute("SELECT source_cn FROM cn_reference WHERE hash = ?", (hash_key,))
            ref = cur.fetchone()
            source_cn = ref["source_cn"] if ref else text  # fallback = text
            
            cur.execute("SELECT id FROM translations WHERE hash = ?", (hash_key,))
            existing = cur.fetchone()
            
            if existing:
                cur.execute(
                    "UPDATE translations SET source_cn = ?, target_en = ?, source_file = ? WHERE hash = ?",
                    (source_cn, text, fname, hash_key)
                )
                updated += 1
            else:
                cur.execute(
                    "INSERT INTO translations (hash, source_cn, target_en, source_file) VALUES (?, ?, ?, ?)",
                    (hash_key, source_cn, text, fname)
                )
                inserted += 1
        
        self.conn.commit()
        self.loaded_files.append(path)
        
        if log_queue:
            log_queue.put(f"[OK] {fname}: +{inserted:,} mới, ~{updated:,} cập nhật")
        
        return inserted + updated
    
    def load_all_translations(self, translations_dir, cn_source_path=None, log_queue=None):
        tdir = Path(translations_dir)
        if not tdir.exists():
            if log_queue:
                log_queue.put(f"[ERROR] Không tìm thấy: {translations_dir}")
            return 0
        
        # === Load CN reference trước ===
        candidates = []
        if cn_source_path:
            candidates.append(cn_source_path)
        # Tự tìm trong thư mục translations và root
        candidates.extend([
            str(tdir / "cn_source.json"),
            str(tdir / "cn.json"),
            "cn_source.json",
            "cn.json",
        ])
        
        loaded_ref = False
        for c in candidates:
            if os.path.exists(c):
                count = self.load_cn_reference(c, log_queue)
                if count > 0:
                    loaded_ref = True
                    break
        
        if not loaded_ref and log_queue:
            log_queue.put("[WARN] Không tìm thấy file CN reference. Cột Source sẽ hiển thị bản dịch.")
            log_queue.put("[INFO] → Export CN source ở tab Find Errors, đặt cạnh translations/")
        
        # === Load translations ===
        files = []
        base = tdir / "base.json"
        if base.exists():
            files.append(base)
        
        for f in sorted(tdir.glob("*.json")):
            if f.name == "base.json":
                continue
            files.append(f)
        
        if log_queue:
            log_queue.put(f"[INFO] Đang load {len(files)} translation files...")
        
        total = 0
        for f in files:
            total += self.load_file(str(f), log_queue)
        
        return total
    
    def compute_frequency(self, log_queue=None):
        """Đếm số lần mỗi source_cn xuất hiện (dựa trên các câu giống nhau)."""
        if log_queue:
            log_queue.put("[INFO] Đang tính frequency...")
        
        cur = self.conn.cursor()
        # Đếm số hash có cùng source_cn (nội dung giống nhau → cùng nhóm)
        cur.execute("""
            UPDATE translations 
            SET frequency = (
                SELECT COUNT(*) FROM translations t2 
                WHERE t2.source_cn = translations.source_cn
            )
        """)
        self.conn.commit()
        
        if log_queue:
            log_queue.put("[OK] Đã tính frequency")
    
    def query(self, where_clause="", order_by="id", limit=None):
        """Query với WHERE clause. Trả về list dict."""
        sql = f"SELECT * FROM translations"
        if where_clause and where_clause.strip():
            sql += f" WHERE {where_clause}"
        sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {limit}"
        
        cur = self.conn.cursor()
        cur.execute(sql)
        return [dict(row) for row in cur.fetchall()]
    
    def count(self, where_clause=""):
        sql = "SELECT COUNT(*) FROM translations"
        if where_clause and where_clause.strip():
            sql += f" WHERE {where_clause}"
        cur = self.conn.cursor()
        cur.execute(sql)
        return cur.fetchone()[0]
    
    def update_row(self, hash_key, column, value):
        """Update 1 ô."""
        allowed = {"source_cn", "target_en", "source_type"}
        if column not in allowed:
            raise ValueError(f"Không thể update column '{column}'")
        
        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE translations SET {column} = ? WHERE hash = ?",
            (value, hash_key)
        )
        self.conn.commit()
    
    def save_to_files(self, log_queue=None):
        """Ghi ngược lại vào các file JSON."""
        cur = self.conn.cursor()
        cur.execute("SELECT source_file, hash, target_en FROM translations")
        rows = cur.fetchall()
        
        # Nhóm theo file
        by_file = {}
        for row in rows:
            fname = row["source_file"]
            if fname not in by_file:
                by_file[fname] = {}
            by_file[fname][row["hash"]] = row["target_en"]
        
        translations_dir = Path("translations")
        saved = 0
        
        for fname, texts in by_file.items():
            fpath = translations_dir / fname
            with open(fpath, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({
                    "format": "gfl2-langpackage-by-text-1",
                    "texts": texts
                }, f, ensure_ascii=False, indent=2)
            saved += 1
            if log_queue:
                log_queue.put(f"[OK] Đã lưu {fname} ({len(texts):,} entries)")
        
        return saved
    
    def export_csv(self, output_path, where_clause="", log_queue=None):
        """Export ra CSV."""
        rows = self.query(where_clause)
        if not rows:
            if log_queue:
                log_queue.put("[WARN] Không có dữ liệu")
            return False
        
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["hash", "source_cn", "target_en", "frequency", "source_type", "source_file"])
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "hash": row["hash"],
                    "source_cn": row["source_cn"],
                    "target_en": row["target_en"],
                    "frequency": row["frequency"],
                    "source_type": row["source_type"],
                    "source_file": row["source_file"],
                })
        
        if log_queue:
            log_queue.put(f"[OK] Đã export {len(rows):,} rows ra {output_path}")
        return True
    
    def get_stats(self):
        """Thống kê tổng quan."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM translations")
        total = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM translations WHERE target_en GLOB '*[一-龥]*'")
        chinese = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(DISTINCT source_cn) FROM translations")
        unique_cn = cur.fetchone()[0]
        
        return {
            "total": total,
            "still_chinese": chinese,
            "translated": total - chinese,
            "unique_cn": unique_cn,
            "loaded_files": len(self.loaded_files),
        }


class GlossaryViewerDB:
    """SQLite in-memory cho glossary."""
    
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)   # ← THÊM
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
    
    def _init_tables(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE glossary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_cn TEXT UNIQUE NOT NULL,
                target_en TEXT NOT NULL,
                banned_translations TEXT DEFAULT '',
                category TEXT DEFAULT 'General'
            )
        """)
        self.conn.commit()
    
    def load_entries(self, entries, log_queue=None):
        """Load từ list dict."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM glossary")
        
        for e in entries:
            cur.execute(
                "INSERT OR REPLACE INTO glossary (source_cn, target_en, banned_translations, category) VALUES (?, ?, ?, ?)",
                (e.get("cn", ""), e.get("en", ""), e.get("banned", ""), e.get("type", "General"))
            )
        
        self.conn.commit()
        if log_queue:
            log_queue.put(f"[OK] Load {len(entries):,} entries vào glossary DB")
    
    def query(self, where_clause="", order_by="id"):
        sql = "SELECT * FROM glossary"
        if where_clause and where_clause.strip():
            sql += f" WHERE {where_clause}"
        sql += f" ORDER BY {order_by}"
        cur = self.conn.cursor()
        cur.execute(sql)
        return [dict(row) for row in cur.fetchall()]
    
    def count(self, where_clause=""):
        sql = "SELECT COUNT(*) FROM glossary"
        if where_clause and where_clause.strip():
            sql += f" WHERE {where_clause}"
        cur = self.conn.cursor()
        cur.execute(sql)
        return cur.fetchone()[0]
    
    def update_row(self, row_id, column, value):
        allowed = {"source_cn", "target_en", "banned_translations", "category"}
        if column not in allowed:
            raise ValueError(f"Không thể update '{column}'")
        cur = self.conn.cursor()
        cur.execute(f"UPDATE glossary SET {column} = ? WHERE id = ?", (value, row_id))
        self.conn.commit()
    
    def to_entries_list(self):
        """Trả về list dict theo format glossary.txt."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM glossary ORDER BY id")
        return [
            {
                "cn": row["source_cn"],
                "en": row["target_en"],
                "banned": row["banned_translations"],
                "type": row["category"],
                "context": "Any"
            }
            for row in cur.fetchall()
        ]