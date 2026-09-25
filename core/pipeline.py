"""Pipeline xử lý chính cho GFL2 Translation Manager."""

from pathlib import Path
from typing import Iterator

from .langpackage_export import (
    TableError, load_table, source_texts, read_translations,
    write_document, convert_legacy, read_legacy, next_update_name,
    has_translations, TRANSLATIONS_DIR,
)
from .langpackage_import import import_table


def run_first_time_setup(old_bytes: Path, old_json: Path, translations_dir: Path) -> Iterator[str]:
    """Chuyển đổi file translations.json cũ (ID-keyed) sang định dạng mới.
    
    Yields từng dòng log để UI hiển thị.
    """
    yield "[INFO] Đang đọc file .bytes gốc..."
    table = load_table(old_bytes)
    
    yield f"[INFO] Đang đọc file cũ: {old_json.name}"
    legacy = read_legacy(old_json)
    yield f"[INFO] Tìm thấy {len(legacy):,} câu trong file cũ"
    
    yield "[INFO] Đang chuyển đổi sang định dạng mới (Text Fingerprint)..."
    conversion = convert_legacy(table, legacy)
    
    translations_dir.mkdir(parents=True, exist_ok=True)
    base_file = translations_dir / "base.json"
    
    if base_file.exists():
        raise TableError(
            f"File '{base_file}' đã tồn tại. "
            "Vui lòng xóa hoặc đổi tên trước khi chạy."
        )
    
    write_document(base_file, conversion.texts)
    
    yield ""
    yield "=" * 60
    yield "[DONE] CHUYỂN ĐỔI THÀNH CÔNG!"
    yield "=" * 60
    yield f"[INFO] {conversion.lines:,} dòng → {len(conversion.texts):,} câu độc nhất"
    yield f"[INFO] Đã lưu tại: {base_file}"
    if conversion.conflicts > 0:
        yield f"[WARN] {conversion.conflicts:,} câu có nhiều bản dịch khác nhau (giữ bản phổ biến nhất)"


def run_update_pipeline(source_bytes: Path, translations_dir: Path, output_bytes: Path) -> Iterator[str]:
    """Chạy pipeline cập nhật đầy đủ.
    
    1. Export: Tìm các câu chưa được dịch trong file .bytes mới
    2. Nếu có câu mới: Lưu vào update-XXX.json để user dịch
    3. Import: Đóng gói tất cả bản dịch vào file .bytes cuối cùng
    """
    # === BƯỚC 1: ĐỌC FILE NGUỒN ===
    yield "[STEP 1/3] Đang đọc file nguồn..."
    table = load_table(source_bytes)
    yield f"[INFO] File: {source_bytes.name}"
    
    # === BƯỚC 2: TÌM CÂU MỚI ===
    yield ""
    yield "[STEP 2/3] Đang quét câu mới..."
    
    if has_translations(translations_dir):
        known = read_translations(translations_dir)
        yield f"[INFO] Đã tải {len(known):,} câu dịch hiện có"
    else:
        known = {}
        yield "[WARN] Không tìm thấy file dịch nào trong thư mục 'translations/'"
        yield "[WARN] → Hãy chạy 'First-Time Setup' trước nếu đây là lần đầu."
    
    all_texts = source_texts(table)
    yield f"[INFO] Tổng số câu trong file nguồn: {len(all_texts):,}"
    
    new_texts = {k: v for k, v in all_texts.items() if k not in known}
    
    if new_texts:
        translations_dir.mkdir(parents=True, exist_ok=True)
        name = next_update_name(translations_dir)
        update_file = translations_dir / name
        write_document(update_file, new_texts)
        yield ""
        yield f"[NEW] ✅ Tìm thấy {len(new_texts):,} câu MỚI"
        yield f"[NEW] → Đã lưu vào: {name}"
        yield f"[INFO] Hãy dịch file này bằng 'Translation Tools' rồi chạy lại."
    else:
        yield "[OK] ✅ Không có câu mới nào cần dịch."
    
    # === BƯỚC 3: ĐÓNG GÓI ===
    yield ""
    yield "[STEP 3/3] Đang đóng gói file .bytes..."
    
    total, translated, changed, missing, unused = import_table(
        source_bytes, translations_dir, output_bytes, refresh_output=True
    )
    
    yield ""
    yield "=" * 60
    yield "[DONE] HOÀN TẤT!"
    yield "=" * 60
    yield f"[INFO] Tổng số dòng:      {total:,}"
    yield f"[INFO] Đã dịch:           {translated:,}"
    yield f"[INFO] Đã thay đổi:       {changed:,}"
    if missing:
        yield f"[WARN] Chưa dịch:         {missing:,} dòng"
    if unused:
        yield f"[INFO] Không sử dụng:     {unused:,} entries"
    yield f"[DONE] File output: {output_bytes}"

def run_export_cn_source(source_bytes: Path, output_json: Path) -> Iterator[str]:
    """Export file .bytes CN ra JSON (dùng làm reference cho Find Errors).
    
    Cấu trúc file output:
    {"format": "gfl2-langpackage-by-text-1", "texts": {"hash": "câu tiếng Trung"}}
    """
    yield f"[INFO] Đang đọc file: {source_bytes.name}"
    table = load_table(source_bytes)
    yield f"[OK] Đã tải bảng"
    
    texts = source_texts(table)
    yield f"[INFO] Tổng số câu: {len(texts):,}"
    
    output_json.parent.mkdir(parents=True, exist_ok=True)
    
    if output_json.exists():
        raise TableError(f"File '{output_json}' đã tồn tại. Chọn tên khác.")
    
    write_document(output_json, texts)
    
    yield ""
    yield "=" * 60
    yield "[DONE] EXPORT THÀNH CÔNG!"
    yield "=" * 60
    yield f"[OK] File: {output_json}"
    yield f"[OK] Số câu: {len(texts):,}"
    yield ""
    yield "[INFO] → Dùng file này làm 'Source (CN)' trong tab Find Errors."