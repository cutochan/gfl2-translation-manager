from core import viewer
from core import backup as bk
from core import glossary as gl
from tkinter import ttk
from core import auto_translate, find_errors, apply_fixes
from core.pipeline import run_export_cn_source
from core import auto_translate, find_errors, apply_fixes
from tkinter import END
import threading
import queue
from core.pipeline import run_first_time_setup, run_update_pipeline
from core.langpackage_export import TableError
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import json
from pathlib import Path
from core import uploader

# ==================== CẤU HÌNH GIAO DIỆN ====================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Fix scaling - quan trọng cho màn hình DPI cao
ctk.set_widget_scaling(1.25)   # Tăng 15% kích thước widget
ctk.set_window_scaling(1.0)    # Giữ nguyên window scaling

# Màu sắc chủ đạo
COLOR_BG = "#0f1419"           # Nền chính (đen xanh)
COLOR_SIDEBAR = "#161b22"       # Nền sidebar
COLOR_CONTENT = "#1a1f26"       # Nền content
COLOR_CARD = "#21262d"          # Nền card
COLOR_ACCENT = "#ff8c42"        # Cam đặc trưng
COLOR_ACCENT_DIM = "#b36229"    # Cam tối
COLOR_ACCENT_HOVER = "#ffa360"
COLOR_TEXT = "#e6edf3"
COLOR_TEXT_DIM = "#7d8590"
COLOR_TEXT_MUTED = "#484f58"
COLOR_BORDER = "#30363d"
COLOR_SUCCESS = "#3fb950"
COLOR_WARNING = "#d29922"
COLOR_ERROR = "#f85149"

APP_TITLE = "GFL2 Translation Manager"
APP_VERSION = "v0.1.0-alpha"

# Kích thước
SIDEBAR_WIDTH = 240


# ==================== SIDEBAR BUTTON ====================
class SidebarButton(ctk.CTkFrame):
    """Nút trong sidebar với icon và label."""
    def __init__(self, parent, icon, text, command, is_active=False):
        super().__init__(parent, fg_color="transparent", height=48, corner_radius=8)
        
        self.command = command
        self.is_active = is_active
        
        # Frame chứa nội dung
        self.inner = ctk.CTkFrame(self, fg_color="transparent", corner_radius=8)
        self.inner.pack(fill="both", expand=True, padx=6, pady=2)
        
        # Icon
        self.icon_label = ctk.CTkLabel(
            self.inner, text=icon, font=ctk.CTkFont(size=18),
            text_color=COLOR_ACCENT if is_active else COLOR_TEXT_DIM,
            width=30
        )
        self.icon_label.pack(side="left", padx=(12, 8))
        
        # Text
        self.text_label = ctk.CTkLabel(
            self.inner, text=text, font=ctk.CTkFont(size=13, weight="bold" if is_active else "normal"),
            text_color=COLOR_TEXT if is_active else COLOR_TEXT_DIM,
            anchor="w"
        )
        self.text_label.pack(side="left", fill="x", expand=True)
        
        # Active indicator
        self.indicator = ctk.CTkFrame(
            self, fg_color=COLOR_ACCENT if is_active else "transparent",
            width=3, height=24, corner_radius=2
        )
        
        self._apply_state()
        
        # Bind events
        for widget in [self, self.inner, self.icon_label, self.text_label]:
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.configure(cursor="hand2")
    
    def _apply_state(self):
        if self.is_active:
            self.inner.configure(fg_color=COLOR_CARD)
            self.indicator.place(x=0, rely=0.5, anchor="w")
        else:
            self.inner.configure(fg_color="transparent")
            self.indicator.place_forget()
    
    def _on_click(self, event=None):
        if self.command:
            self.command()
    
    def _on_enter(self, event=None):
        if not self.is_active:
            self.inner.configure(fg_color=COLOR_CONTENT)
            self.icon_label.configure(text_color=COLOR_TEXT)
            self.text_label.configure(text_color=COLOR_TEXT)
    
    def _on_leave(self, event=None):
        if not self.is_active:
            self.inner.configure(fg_color="transparent")
            self.icon_label.configure(text_color=COLOR_TEXT_DIM)
            self.text_label.configure(text_color=COLOR_TEXT_DIM)
    
    def set_active(self, active):
        self.is_active = active
        self._apply_state()
        if active:
            self.icon_label.configure(text_color=COLOR_ACCENT)
            self.text_label.configure(text_color=COLOR_TEXT, font=ctk.CTkFont(size=13, weight="bold"))
        else:
            self.icon_label.configure(text_color=COLOR_TEXT_DIM)
            self.text_label.configure(text_color=COLOR_TEXT_DIM, font=ctk.CTkFont(size=13, weight="normal"))


# ==================== MAIN APP ====================
class GFL2TranslationTool(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Queues
        self.log_queue_patch = queue.Queue()
        self.log_queue_setup = queue.Queue()
        self.log_queue_translate = queue.Queue()  # ← THÊM DÒNG NÀY
        self.log_queue_find = queue.Queue()    # ← THÊM
        self.log_queue_apply = queue.Queue()   # ← THÊM
        self.log_queue_export = queue.Queue()  # ← THÊM
        self.log_queue_glossary = queue.Queue()
        self.glossary_entries = []      # Cache danh sách thuật ngữ
        self.glossary_path = "glossary.txt"
        self.log_queue_backup = queue.Queue()
        # Translation Viewer state
        self.viewer_db = viewer.TranslationViewerDB()
        self.glossary_db = viewer.GlossaryViewerDB()
        self.log_queue_viewer = queue.Queue()
        self.viewer_current_subtab = "translations"  # hoặc "glossary"
        self.viewer_sort_column = "id"
        self.viewer_sort_order = "ASC"
        self.viewer_edit_widget = None  # Widget đang edit inline
        self.viewer_edit_panel_visible = tk.BooleanVar(value=False)
        self.viewer_edit_hash = None   # Hash của row đang edit
        self.sidebar_visible = True
        self.sidebar_width = SIDEBAR_WIDTH
        self.toolbar_visible = tk.BooleanVar(value=True)
        self.filter_visible = tk.BooleanVar(value=True)
        self.subtab_visible = tk.BooleanVar(value=True)
        # Advanced filter state
        self.advanced_filter_visible = tk.BooleanVar(value=True)
        self.adv_checkboxes = {}
        self.quick_filter_map = {}   # Sẽ fill trong _build_viewer_translations_tab
        self.adv_search_col = None   # Sẽ set trong _build
        self.adv_exact_cn = None   # Sẽ set trong _build
        self.adv_exact_en = None   # Sẽ set trong _build
        # Replace All state
        self.replace_dialog = None
        self.log_queue_settings = queue.Queue()

        # Paths lưu trữ cho tab Translate
        self.translate_paths = {
            "input": "",
            "output": "",
            "style": "",
            "glossary": "",
            "api_key": "",
            "corrections": "",
            "translated": "",
        }

        # Queues cho logging từ thread
        self.log_queue_patch = queue.Queue()
        self.log_queue_setup = queue.Queue()

        # Flag
        self.pipeline_running = False
        
        self.title(f"{APP_TITLE} - {APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(fg_color=COLOR_BG)
        
        # Grid config
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # Lưu trữ các page
        self.pages = {}
        self.current_page = None
        self.sidebar_buttons = {}
        
        # Xây dựng UI
        self._build_header()
        self._build_main_area()
        self._build_status_bar()
        
        # Mở trang mặc định
        self._show_page("patch")
        self.bind("<Control-s>", lambda e: self._viewer_save() if self.current_page == "viewer" else None)

        self.bind("<Control-s>", self._global_save_shortcut)

    def _global_save_shortcut(self, event=None):
        """Ctrl+S: Nếu đang ở tab viewer, lưu edit panel trước, rồi mới save file."""
        if self.current_page != "viewer":
            return
        if self.viewer_edit_panel_visible.get() and self.viewer_edit_hash:
            self._edit_panel_save()
            
    # ==================== HEADER ====================
    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=COLOR_SIDEBAR, height=48, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)
        
        # === Hamburger button (☰) ===
        self.btn_toggle_sidebar = ctk.CTkButton(
            header, text="☰", width=40, height=32,
            fg_color="transparent", hover_color=COLOR_CARD,
            text_color=COLOR_ACCENT, font=ctk.CTkFont(size=20, weight="bold"),
            command=self._toggle_sidebar
        )
        self.btn_toggle_sidebar.grid(row=0, column=0, padx=(10, 5), pady=8)
        
        # === Title (compact) ===
        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=1, sticky="w", padx=5, pady=8)
        
        ctk.CTkLabel(
            title_frame, text="GFL2",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLOR_ACCENT
        ).pack(side="left")
        
        ctk.CTkLabel(
            title_frame, text=" Translation Manager",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_TEXT
        ).pack(side="left")
        
        # === Version ===
        ctk.CTkLabel(
            header, text=f"● {APP_VERSION}",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=COLOR_TEXT_DIM
        ).grid(row=0, column=2, sticky="e", padx=15, pady=8)
    
    def _toggle_sidebar(self):
        """Ẩn/hiện sidebar."""
        if self.sidebar_visible:
            # Ẩn
            self.sidebar.grid_remove()
            self.sidebar_visible = False
            self.btn_toggle_sidebar.configure(text="▶")   # Đổi icon
        else:
            # Hiện
            self.sidebar.grid()
            self.sidebar_visible = True
            self.btn_toggle_sidebar.configure(text="☰")
    
    # ==================== MAIN AREA ====================
    def _build_main_area(self):
        """Xây dựng sidebar + content area."""
        main = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        main.grid(row=1, column=0, sticky="nsew")
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=1)
        
        # === SIDEBAR ===
        self.sidebar = ctk.CTkFrame(main, fg_color=COLOR_SIDEBAR, width=SIDEBAR_WIDTH, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        
        # Sidebar content
        sidebar_content = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        sidebar_content.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Nhóm 1: WORKFLOW
        self._add_section_label(sidebar_content, "WORKFLOW")
        
        buttons_config = [
            ("patch", "🗓️", "Patch Updater"),
            ("setup", "⚙️", "First-Time Setup"),
        ]
        for key, icon, text in buttons_config:
            btn = SidebarButton(sidebar_content, icon, text, lambda k=key: self._show_page(k))
            btn.pack(fill="x", pady=2)
            self.sidebar_buttons[key] = btn
        
        # Nhóm 2: TOOLS
        self._add_section_label(sidebar_content, "TOOLS")
        
        buttons_config2 = [
            ("viewer", "🗄️", "Translation Viewer"),
            ("glossary", "📖", "Glossary Manager"),
            ("translate", "🌐", "Translation Tools"),
        ]
        for key, icon, text in buttons_config2:
            btn = SidebarButton(sidebar_content, icon, text, lambda k=key: self._show_page(k))
            btn.pack(fill="x", pady=2)
            self.sidebar_buttons[key] = btn
        
        # Nhóm 3: SYSTEM
        self._add_section_label(sidebar_content, "SYSTEM")
        
        buttons_config3 = [
            ("backup", "💾", "Backup & Utilities"),
            ("settings", "⚙️", "Settings"),
        ]
        for key, icon, text in buttons_config3:
            btn = SidebarButton(sidebar_content, icon, text, lambda k=key: self._show_page(k))
            btn.pack(fill="x", pady=2)
            self.sidebar_buttons[key] = btn
        
        # Info ở dưới cùng sidebar
        sidebar_footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        sidebar_footer.pack(side="bottom", fill="x", padx=15, pady=10)
        
        ctk.CTkFrame(sidebar_footer, fg_color=COLOR_BORDER, height=1).pack(fill="x", pady=(0, 8))
        
        self.sidebar_info = ctk.CTkLabel(
            sidebar_footer,
            text="📁 Chưa có translations",
            font=ctk.CTkFont(size=10),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
            anchor="w"
        )
        self.sidebar_info.pack(anchor="w")
        
        self._update_sidebar_info()
        
        # === CONTENT AREA ===
        self.content = ctk.CTkFrame(main, fg_color=COLOR_CONTENT, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        
        # Tạo các page
        self._create_pages()
    
    def _add_section_label(self, parent, text):
        """Thêm label phân nhóm trong sidebar."""
        label = ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
            anchor="w"
        )
        label.pack(fill="x", padx=15, pady=(15, 5))
    
    # ==================== PAGES ====================
    def _create_pages(self):
        """Tạo tất cả các page."""
        self.pages["patch"] = self._create_page_patch()
        self.pages["setup"] = self._create_page_setup()
        self.pages["glossary"] = self._create_page_glossary()
        self.pages["translate"] = self._create_page_translate()
        self.pages["backup"] = self._create_page_backup()
        self.pages["viewer"] = self._create_page_viewer()
        self.pages["settings"] = self._create_page_settings()

        # Place tất cả vào content nhưng ẩn
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
            page.grid_remove()
    
    def _show_page(self, key):
        """Chuyển trang."""
        # Ẩn tất cả page
        for page in self.pages.values():
            page.grid_remove()
        
        # Hiện page được chọn
        self.pages[key].grid()
        self.current_page = key
        
        # Cập nhật active state của buttons
        for btn_key, btn in self.sidebar_buttons.items():
            btn.set_active(btn_key == key)

    # ==================== PAGE: VIEWER ====================
    def _create_page_viewer(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=20)
        page.grid_rowconfigure(5, weight=1)
        
        # === HEADER ===
        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(10, 5))
        
        ctk.CTkLabel(
            header, text="🗄️  Translation Viewer",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=COLOR_TEXT
        ).pack(side="left")
        
        ctk.CTkLabel(
            header, text="Xem, query và chỉnh sửa bản dịch",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM
        ).pack(side="left", padx=(15, 0))
        
        # === TOGGLE BAR (LUÔN HIỆN) ===
        self.viewer_toggle_bar = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=8, height=38)
        self.viewer_toggle_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 5))
        self.viewer_toggle_bar.grid_propagate(False)
        
        ctk.CTkLabel(
            self.viewer_toggle_bar, text="⚙️ Hiển thị:",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_DIM
        ).pack(side="left", padx=(12, 8), pady=7)
        
        # Checkbox Toolbar
        self.toolbar_visible = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.viewer_toggle_bar, text="Toolbar",
            variable=self.toolbar_visible,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_toggle_toolbar,
            checkbox_width=16, checkbox_height=16
        ).pack(side="left", padx=5, pady=7)
        
        # Checkbox Filter
        self.filter_visible = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.viewer_toggle_bar, text="Filter",
            variable=self.filter_visible,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_toggle_filter,
            checkbox_width=16, checkbox_height=16
        ).pack(side="left", padx=5, pady=7)
        
        # ⚡ Checkbox Advanced (MỚI)
        self.advanced_filter_visible = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.viewer_toggle_bar, text="Advanced",
            variable=self.advanced_filter_visible,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_toggle_advanced,
            checkbox_width=16, checkbox_height=16
        ).pack(side="left", padx=5, pady=7)
        
        # Checkbox Tabs
        self.subtab_visible = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.viewer_toggle_bar, text="Tabs",
            variable=self.subtab_visible,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_toggle_subtab,
            checkbox_width=16, checkbox_height=16
        ).pack(side="left", padx=5, pady=7)
        
        # Checkbox Edit Panel
        self.viewer_edit_panel_visible = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.viewer_toggle_bar, text="Edit Panel",
            variable=self.viewer_edit_panel_visible,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_toggle_edit_panel,
            checkbox_width=16, checkbox_height=16
        ).pack(side="left", padx=5, pady=7)
        
        # Checkbox Log
        self.viewer_log_visible = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.viewer_toggle_bar, text="Log",
            variable=self.viewer_log_visible,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_toggle_log,
            checkbox_width=16, checkbox_height=16
        ).pack(side="left", padx=5, pady=7)
        
        # Stats ở góc phải
        self.viewer_stats_label = ctk.CTkLabel(
            self.viewer_toggle_bar, text="Chưa load",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM
        )
        self.viewer_stats_label.pack(side="right", padx=12, pady=7)
        
        # === TOOLBAR (có thể ẩn) ===
        self.viewer_toolbar_frame = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=8, height=48)
        self.viewer_toolbar_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 5))
        self.viewer_toolbar_frame.grid_propagate(False)
        
        ctk.CTkButton(
            self.viewer_toolbar_frame, text="🔄 Load", height=32, width=100,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._viewer_load
        ).pack(side="left", padx=(10, 4), pady=8)
        
        ctk.CTkButton(
            self.viewer_toolbar_frame, text="💾 Save", height=32, width=100,
            fg_color=COLOR_SUCCESS, hover_color="#45a049",
            text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._viewer_save
        ).pack(side="left", padx=4, pady=8)
        
        ctk.CTkButton(
            self.viewer_toolbar_frame, text="📤 Export", height=32, width=100,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._viewer_export_csv
        ).pack(side="left", padx=4, pady=8)
        
        # === SUB-TABVIEW (row 3) ===
        self.viewer_tabs = ctk.CTkTabview(
            page,
            fg_color=COLOR_CONTENT,
            segmented_button_fg_color=COLOR_CARD,
            segmented_button_selected_color=COLOR_ACCENT,
            segmented_button_selected_hover_color=COLOR_ACCENT_HOVER,
            segmented_button_unselected_color=COLOR_CARD,
            text_color=COLOR_TEXT,
            corner_radius=8, border_width=1, border_color=COLOR_BORDER,
            command=self._viewer_subtab_changed
        )
        self.viewer_tabs.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 5))
        
        # ⚡ Sửa weight của row 3 (chứa tabview)
        page.grid_rowconfigure(3, weight=20)
        page.grid_rowconfigure(2, weight=0)   # Toolbar không giãn
        
        tab_trans = self.viewer_tabs.add("📝 Translations")
        tab_gloss = self.viewer_tabs.add("📖 Glossary")
        
        self._build_viewer_translations_tab(tab_trans)
        self._build_viewer_glossary_tab(tab_gloss)
        
        # === LOG (row 5) ===
        self.viewer_log_frame = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=8)
        self.viewer_log_frame.grid_columnconfigure(0, weight=1)
        self.viewer_log_frame.grid_rowconfigure(0, weight=1)
        
        self.log_viewer = ctk.CTkTextbox(
            self.viewer_log_frame, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=10),
            border_width=1, border_color=COLOR_BORDER, corner_radius=6
        )
        self.log_viewer.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.log_viewer.insert("0.0", "[Ready] Nhấn 'Load' để bắt đầu...\n")
        self.log_viewer.configure(state="disabled")
        
        # === Bind phím tắt ===
        self.bind("<Control-t>", lambda e: self._toggle_toolbar_shortcut())
        self.bind("<Control-f>", lambda e: self._toggle_filter_shortcut())
        self.bind("<Control-b>", lambda e: self._toggle_sidebar())
        
        return page
    
    def _viewer_toggle_log(self):
        """Ẩn/hiện log frame."""
        if self.viewer_log_visible.get():
            self.viewer_log_frame.grid(
                row=4, column=0, sticky="nsew", padx=30, pady=(0, 20)
            )
        else:
            self.viewer_log_frame.grid_remove()

    # ==================== ADVANCED FILTER HANDLERS ====================
    def _viewer_toggle_advanced(self):
        """Ẩn/hiện Advanced Filter panel."""
        if self.advanced_filter_visible.get():
            self.viewer_advanced_filter.grid()
        else:
            self.viewer_advanced_filter.grid_remove()
    
    def _on_quick_filter_changed(self, selected_value):
        """Khi user chọn 1 quick filter từ dropdown → auto fill SQL."""
        sql = self.quick_filter_map.get(selected_value, "")
        self.viewer_filter_entry.delete(0, "end")
        if sql:
            self.viewer_filter_entry.insert(0, sql)
            # Auto apply
            self._viewer_apply_filter()
    
    def _adv_build_sql(self):
        """Build SQL từ Advanced Filter panel."""
        conditions = []
        
        # 1. Text search
        search_text = self.adv_search_entry.get().strip()
        if search_text:
            # Escape single quote
            escaped = search_text.replace("'", "''")
            col_choice = self.adv_search_col.get()
            if col_choice == "Source CN":
                conditions.append(f"source_cn LIKE '%{escaped}%'")
            elif col_choice == "Target EN":
                conditions.append(f"target_en LIKE '%{escaped}%'")
            else:  # Cả hai
                conditions.append(f"(source_cn LIKE '%{escaped}%' OR target_en LIKE '%{escaped}%')")
        
        # 2. Checkboxes
        if self.adv_checkboxes["undone"].get():
            conditions.append("target_en GLOB '*[一-龥]*'")
        if self.adv_checkboxes["done"].get():
            conditions.append("target_en NOT GLOB '*[一-龥]*'")
        if self.adv_checkboxes["long"].get():
            conditions.append("length(source_cn) > 200")
        if self.adv_checkboxes["short"].get():
            conditions.append("length(source_cn) < 10")
        if self.adv_checkboxes["base"].get():
            conditions.append("source_file = 'base.json'")
        if self.adv_checkboxes["update"].get():
            conditions.append("source_file LIKE 'update-%'")
        if self.adv_checkboxes["duplicates"].get():
            conditions.append("frequency > 1")
        if self.adv_checkboxes["has_tag"].get():
            conditions.append("source_cn LIKE '%<color=%'")
        if self.adv_checkboxes["empty"].get():
            conditions.append("(target_en = '' OR target_en IS NULL)")
        
        # Nếu có filter SQL sẵn trong entry, giữ nguyên làm điều kiện đầu
        existing = self.viewer_filter_entry.get().strip()
        if existing:
            # Kiểm tra: nếu existing là quick filter vừa chọn thì bỏ qua
            is_quick = existing in self.quick_filter_map.values()
            if not is_quick:
                conditions.insert(0, f"({existing})")
        
        # Build final SQL
        if not conditions:
            final_sql = ""
        else:
            final_sql = " AND ".join(conditions)
        
        self.viewer_filter_entry.delete(0, "end")
        if final_sql:
            self.viewer_filter_entry.insert(0, final_sql)
            self._viewer_apply_filter()
            self._log(self.log_viewer, f"[OK] Đã build filter: {final_sql[:80]}...")
        else:
            self._log(self.log_viewer, "[WARN] Không có điều kiện nào được chọn.")
    
    def _adv_reset(self):
        """Reset Advanced Filter panel."""
        self.adv_search_entry.delete(0, "end")
        self.adv_search_col.set("Source CN")
        for var in self.adv_checkboxes.values():
            var.set(False)
        self._log(self.log_viewer, "[INFO] Đã reset Advanced Filter")

    def _adv_exact_match(self):
        """Build SQL exact match từ 2 ô input."""
        cn_exact = self.adv_exact_cn.get().strip()
        en_exact = self.adv_exact_en.get().strip()
        
        if not cn_exact and not en_exact:
            self._log(self.log_viewer, "[WARN] Nhập ít nhất 1 ô để tìm!")
            return
        
        conditions = []
        
        if cn_exact:
            # Escape single quotes
            escaped = cn_exact.replace("'", "''")
            conditions.append(f"source_cn = '{escaped}'")
        
        if en_exact:
            escaped = en_exact.replace("'", "''")
            conditions.append(f"target_en = '{escaped}'")
        
        final_sql = " AND ".join(conditions)
        
        # Fill vào SQL entry và auto apply
        self.viewer_filter_entry.delete(0, "end")
        self.viewer_filter_entry.insert(0, final_sql)
        self._viewer_apply_filter()
        
        self._log(self.log_viewer, f"[OK] Exact match: {final_sql}")
    
    def _adv_exact_reset(self):
        """Reset 2 ô exact match."""
        self.adv_exact_cn.delete(0, "end")
        self.adv_exact_en.delete(0, "end")
        self._log(self.log_viewer, "[INFO] Đã reset Exact Match")

    def _toggle_toolbar_shortcut(self):
        """Ctrl+T: Toggle toolbar."""
        self.toolbar_visible.set(not self.toolbar_visible.get())
        self._viewer_toggle_toolbar()
    
    def _toggle_filter_shortcut(self):
        """Ctrl+F: Toggle filter."""
        self.filter_visible.set(not self.filter_visible.get())
        self._viewer_toggle_filter()

    def _build_viewer_translations_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)   # Row 2 = content (table+panel)
        
        # === ROW 0: FILTER BAR (Quick dropdown + SQL entry) ===
        self.viewer_filter_bar = ctk.CTkFrame(parent, fg_color="transparent")
        self.viewer_filter_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(5, 3))
        self.viewer_filter_bar.grid_columnconfigure(3, weight=1)   # SQL entry giãn
        
        # Quick dropdown
        ctk.CTkLabel(
            self.viewer_filter_bar, text="⚡",
            font=ctk.CTkFont(size=14), text_color=COLOR_ACCENT
        ).grid(row=0, column=0, padx=(0, 5))
        
        self.quick_filter_map = {
            "— Chọn filter nhanh —": "",
            "🚫 Chưa dịch": "target_en GLOB '*[一-龥]*'",
            "✅ Đã dịch": "target_en NOT GLOB '*[一-龥]*'",
            "📊 Duplicates (freq > 1)": "frequency > 1",
            "📁 Base only": "source_file = 'base.json'",
            "🔄 Update only": "source_file LIKE 'update-%'",
            "📏 Câu dài (>200)": "length(source_cn) > 200",
            "📐 Câu ngắn (<10)": "length(source_cn) < 10",
            "🎨 Có tag color": "source_cn LIKE '%<color=%'",
            "❌ Câu rỗng": "target_en = '' OR target_en IS NULL",
            "⚠️ Dịch lan man (>3x)": "length(target_en) > length(source_cn) * 3",
            "🚫 Chưa dịch + dài": "target_en GLOB '*[一-龥]*' AND length(source_cn) > 200",
            "🚫 Chưa dịch + ngắn": "target_en GLOB '*[一-龥]*' AND length(source_cn) < 20",
            "🚫 Chưa dịch + base": "source_file = 'base.json' AND target_en GLOB '*[一-龥]*'",
            "🚫 Chưa dịch + update": "source_file LIKE 'update-%' AND target_en GLOB '*[一-龥]*'",
        }
        
        self.quick_filter_var = tk.StringVar(value="— Chọn filter nhanh —")
        self.quick_filter_menu = ctk.CTkOptionMenu(
            self.viewer_filter_bar,
            variable=self.quick_filter_var,
            values=list(self.quick_filter_map.keys()),
            width=220, height=28,
            fg_color=COLOR_BG, button_color=COLOR_BORDER,
            button_hover_color=COLOR_ACCENT,
            dropdown_fg_color=COLOR_CARD,
            dropdown_hover_color=COLOR_ACCENT,
            text_color=COLOR_TEXT,
            font=ctk.CTkFont(size=11),
            command=self._on_quick_filter_changed
        )
        self.quick_filter_menu.grid(row=0, column=1, padx=(0, 8))
        
        # SQL label
        ctk.CTkLabel(
            self.viewer_filter_bar, text="🔍 SQL:",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=2, padx=(0, 5))
        
        # SQL entry
        self.viewer_filter_entry = ctk.CTkEntry(
            self.viewer_filter_bar, placeholder_text="source_cn LIKE '%兰汀%' AND target_en = ''",
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=28
        )
        self.viewer_filter_entry.grid(row=0, column=3, sticky="ew", padx=2)
        self.viewer_filter_entry.bind("<Return>", lambda e: self._viewer_apply_filter())
        
        ctk.CTkButton(
            self.viewer_filter_bar, text="Apply", width=60, height=28,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._viewer_apply_filter
        ).grid(row=0, column=4, padx=2)
        
        ctk.CTkButton(
            self.viewer_filter_bar, text="Clear", width=60, height=28,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_clear_filter
        ).grid(row=0, column=5, padx=(2, 0))
        
        # === ROW 1: ADVANCED FILTER PANEL ===
        self.viewer_advanced_filter = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=6)
        self.viewer_advanced_filter.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 3))
        self.viewer_advanced_filter.grid_columnconfigure(0, weight=1)
        
        # --- Row A: Text search ---
        adv_row_a = ctk.CTkFrame(self.viewer_advanced_filter, fg_color="transparent")
        adv_row_a.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        
        ctk.CTkLabel(
            adv_row_a, text="🔍 Tìm:",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT
        ).pack(side="left", padx=(0, 5))
        
        self.adv_search_entry = ctk.CTkEntry(
            adv_row_a, width=280, height=28,
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, placeholder_text="Nhập text cần tìm..."
        )
        self.adv_search_entry.pack(side="left", padx=5)
        self.adv_search_entry.bind("<Return>", lambda e: self._adv_build_sql())
        
        ctk.CTkLabel(
            adv_row_a, text="Trong:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM
        ).pack(side="left", padx=(15, 5))
        
        self.adv_search_col = tk.StringVar(value="Source CN")
        ctk.CTkOptionMenu(
            adv_row_a, variable=self.adv_search_col,
            values=["Source CN", "Target EN", "Cả hai"],
            width=120, height=28,
            fg_color=COLOR_BG, button_color=COLOR_BORDER,
            button_hover_color=COLOR_ACCENT,
            dropdown_fg_color=COLOR_CARD,
            dropdown_hover_color=COLOR_ACCENT,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11)
        ).pack(side="left")
        
        ctk.CTkLabel(
            adv_row_a, text="💡 Kết hợp với SQL filter bên trên",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=15)
        
        # --- Row B: Checkboxes ---
        adv_row_b = ctk.CTkFrame(self.viewer_advanced_filter, fg_color="transparent")
        adv_row_b.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        
        self.adv_checkboxes = {}
        checkboxes_config = [
            ("undone", "🚫 Chưa dịch"),
            ("done", "✅ Đã dịch"),
            ("long", "📏 Câu dài (>200)"),
            ("short", "📐 Câu ngắn (<10)"),
            ("base", "📁 Base only"),
            ("update", "🔄 Update only"),
            ("duplicates", "📊 Duplicates (freq>1)"),
            ("has_tag", "🎨 Có tag color"),
            ("empty", "❌ Câu rỗng"),
        ]
        
        for i, (key, label) in enumerate(checkboxes_config):
            var = tk.BooleanVar(value=False)
            self.adv_checkboxes[key] = var
            ctk.CTkCheckBox(
                adv_row_b, text=label, variable=var,
                fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
                text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
                checkbox_width=16, checkbox_height=16
            ).pack(side="left", padx=5, pady=2)

        # --- Row B2: EXACT MATCH (MỚI) ---
        adv_row_b2 = ctk.CTkFrame(self.viewer_advanced_filter, fg_color=COLOR_BG, corner_radius=4)
        adv_row_b2.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        
        ctk.CTkLabel(
            adv_row_b2, text="🎯 Exact Match:",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_ACCENT
        ).pack(side="left", padx=(10, 8), pady=8)
        
        ctk.CTkLabel(
            adv_row_b2, text="Source CN =",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).pack(side="left", padx=(0, 3))
        
        self.adv_exact_cn = ctk.CTkEntry(
            adv_row_b2, width=200, height=26,
            fg_color=COLOR_CARD, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, placeholder_text="VD: 你好"
        )
        self.adv_exact_cn.pack(side="left", padx=3)
        self.adv_exact_cn.bind("<Return>", lambda e: self._adv_exact_match())
        
        ctk.CTkLabel(
            adv_row_b2, text="Target EN =",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).pack(side="left", padx=(12, 3))
        
        self.adv_exact_en = ctk.CTkEntry(
            adv_row_b2, width=200, height=26,
            fg_color=COLOR_CARD, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, placeholder_text="VD: Hello"
        )
        self.adv_exact_en.pack(side="left", padx=3)
        self.adv_exact_en.bind("<Return>", lambda e: self._adv_exact_match())
        
        ctk.CTkButton(
            adv_row_b2, text="🎯 Find", height=26, width=80,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._adv_exact_match
        ).pack(side="left", padx=(10, 5))
        
        ctk.CTkButton(
            adv_row_b2, text="↩", height=26, width=35,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._adv_exact_reset
        ).pack(side="left", padx=3)
        
        # Ghi chú
        ctk.CTkLabel(
            adv_row_b2, text="💡 Để trống 1 ô = tìm theo ô còn lại",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=15)
        
        # --- Row C: Buttons ---    
        adv_row_c = ctk.CTkFrame(self.viewer_advanced_filter, fg_color="transparent")
        adv_row_c.grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 8))
        
        ctk.CTkButton(
            adv_row_c, text="🔧 Build SQL", height=28, width=120,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._adv_build_sql
        ).pack(side="left", padx=(0, 5))
        
        ctk.CTkButton(
            adv_row_c, text="↩ Reset", height=28, width=100,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._adv_reset
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            adv_row_c, text="🔄 Replace All", height=28, width=130,
            fg_color="#ff8c42", hover_color="#e67a35",
            text_color="#000000", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._viewer_open_replace_all
        ).pack(side="left", padx=(10, 2))
        
        ctk.CTkLabel(
            adv_row_c, text="→ SQL sẽ được điền vào ô bên trên",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED
        ).pack(side="left", padx=10)
        
        # Hide if Advanced toggle is off
        if not self.advanced_filter_visible.get():
            self.viewer_advanced_filter.grid_remove()
        
        # === ROW 2: CONTENT (Table + Edit Panel) ===
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 3))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        
        # --- TABLE ---
        table_card = ctk.CTkFrame(content, fg_color=COLOR_BG, corner_radius=6)
        table_card.grid(row=0, column=0, sticky="nsew")
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)
        
        style = ttk.Style()
        style.configure(
            "Viewer.Treeview",
            background=COLOR_BG, foreground=COLOR_TEXT,
            fieldbackground=COLOR_BG, bordercolor=COLOR_BORDER,
            rowheight=44, font=("Consolas", 14)
        )
        style.configure(
            "Viewer.Treeview.Heading",
            background=COLOR_CARD, foreground=COLOR_ACCENT,
            font=("Arial", 13, "bold"), borderwidth=0
        )
        style.map("Viewer.Treeview", background=[("selected", COLOR_ACCENT)])
        style.map("Viewer.Treeview", foreground=[("selected", "#000000")])
        
        columns = ("id", "source_cn", "target_en", "frequency", "source_type", "source_file")
        self.viewer_tree = ttk.Treeview(
            table_card, columns=columns, show="headings",
            style="Viewer.Treeview", selectmode="browse"
        )
        
        headers = {
            "id": ("ID", 70),
            "source_cn": ("Source (CN)", 500),
            "target_en": ("Target (EN)", 600),
            "frequency": ("Freq", 80),
            "source_type": ("Type", 120),
            "source_file": ("File", 140),
        }
        for col, (text, width) in headers.items():
            self.viewer_tree.heading(col, text=text, command=lambda c=col: self._viewer_sort_by(c))
            self.viewer_tree.column(col, width=width, anchor="w" if col in ("source_cn", "target_en") else "center")
        
        vsb = ttk.Scrollbar(table_card, orient="vertical", command=self.viewer_tree.yview)
        hsb = ttk.Scrollbar(table_card, orient="horizontal", command=self.viewer_tree.xview)
        self.viewer_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.viewer_tree.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=(4, 0))
        vsb.grid(row=0, column=1, sticky="ns", pady=(4, 0))
        hsb.grid(row=1, column=0, sticky="ew", padx=(4, 0))
        
        self.viewer_tree.bind("<Double-1>", self._viewer_start_edit)
        self.viewer_tree.bind("<<TreeviewSelect>>", self._viewer_on_row_select)
        
        # --- EDIT PANEL ---
        self.viewer_edit_panel = self._build_edit_panel(content)
        self.viewer_edit_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
        self.viewer_edit_panel.grid_remove()
        
        # === ROW 3: STATUS BAR ===
        status = ctk.CTkFrame(parent, fg_color="transparent", height=22)
        status.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 5))
        
        self.viewer_row_count = ctk.CTkLabel(
            status, text="0 rows",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_DIM
        )
        self.viewer_row_count.pack(side="left")
        
        ctk.CTkLabel(
            status, text="💡 Double-click ô để sửa | Chọn row để mở Edit Panel",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED
        ).pack(side="right")
    
    def _build_edit_panel(self, parent):
        """Tạo Edit Panel với cả 2 textbox chia đều không gian."""
        panel = ctk.CTkFrame(parent, fg_color=COLOR_CARD, corner_radius=6, width=420)
        panel.grid_propagate(False)
        panel.grid_columnconfigure(0, weight=1)
        # ⚡ Cả CN (row 3) và EN (row 5) đều weight=1 → chia đều
        panel.grid_rowconfigure(3, weight=1)
        panel.grid_rowconfigure(5, weight=1)
        
        # === HEADER (row 0) ===
        ctk.CTkLabel(
            panel, text="✏️  Edit Entry",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 5))
        
        # === INFO (row 1) ===
        self.viewer_edit_info = ctk.CTkLabel(
            panel, text="Chọn 1 row để sửa",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_DIM,
            justify="left", anchor="w"
        )
        self.viewer_edit_info.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        
        # === CN LABEL (row 2) ===
        ctk.CTkLabel(
            panel, text="🇨🇳  Source (CN):",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=2, column=0, sticky="w", padx=12, pady=(0, 3))
        
        # === CN TEXTBOX (row 3) - weight=1 ===
        self.edit_panel_cn = ctk.CTkTextbox(
            panel, fg_color=COLOR_BG, text_color=COLOR_TEXT,
            font=ctk.CTkFont(family="Consolas", size=13),
            border_width=1, border_color=COLOR_BORDER,
            corner_radius=6, wrap="word"
        )
        self.edit_panel_cn.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 8))
        
        # === EN LABEL (row 4) ===
        ctk.CTkLabel(
            panel, text="🇬🇧  Target (EN):",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=4, column=0, sticky="w", padx=12, pady=(0, 3))
        
        # === EN TEXTBOX (row 5) - weight=1 ===
        self.edit_panel_en = ctk.CTkTextbox(
            panel, fg_color=COLOR_BG, text_color=COLOR_TEXT,
            font=ctk.CTkFont(family="Consolas", size=13),
            border_width=1, border_color=COLOR_BORDER,
            corner_radius=6, wrap="word"
        )
        self.edit_panel_en.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 8))
        
        # === BUTTONS (row 6) ===
        btn_frame = ctk.CTkFrame(panel, fg_color="transparent")
        btn_frame.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 12))
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        
        self.edit_panel_save_btn = ctk.CTkButton(
            btn_frame, text="💾  Save", height=36,
            fg_color=COLOR_SUCCESS, hover_color="#45a049",
            text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._edit_panel_save
        )
        self.edit_panel_save_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        
        ctk.CTkButton(
            btn_frame, text="↩  Reset", height=36,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._edit_panel_reset
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        
        return panel
    
    def _build_viewer_glossary_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        
        # === FILTER BAR (row 0) ===
        filter_bar = ctk.CTkFrame(parent, fg_color="transparent")
        filter_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(5, 5))
        filter_bar.grid_columnconfigure(3, weight=1)
        
        # 🔍 Simple search
        ctk.CTkLabel(
            filter_bar, text="🔍 Search:",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, padx=(0, 5))
        
        self.gloss_search_entry = ctk.CTkEntry(
            filter_bar, placeholder_text="Tìm trong CN hoặc EN...",
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=28, width=300
        )
        self.gloss_search_entry.grid(row=0, column=1, padx=(0, 8))
        self.gloss_search_entry.bind("<KeyRelease>", lambda e: self._viewer_gloss_search())
        
        ctk.CTkLabel(
            filter_bar, text="|  SQL:",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_DIM
        ).grid(row=0, column=2, padx=(0, 5))
        
        self.gloss_viewer_filter = ctk.CTkEntry(
            filter_bar, placeholder_text="category = 'Characters'",
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=28
        )
        self.gloss_viewer_filter.grid(row=0, column=3, sticky="ew", padx=2)
        self.gloss_viewer_filter.bind("<Return>", lambda e: self._viewer_gloss_apply_filter())
        
        ctk.CTkButton(
            filter_bar, text="Apply", width=60, height=28,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._viewer_gloss_apply_filter
        ).grid(row=0, column=4, padx=2)
        
        ctk.CTkButton(
            filter_bar, text="Clear", width=60, height=28,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            command=self._viewer_gloss_clear_filter
        ).grid(row=0, column=5, padx=(2, 0))
        
        # === TABLE (row 1) ===
        table_card = ctk.CTkFrame(parent, fg_color=COLOR_BG, corner_radius=6)
        table_card.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(0, weight=1)
        
        columns = ("id", "source_cn", "target_en", "banned", "category")
        self.gloss_viewer_tree = ttk.Treeview(
            table_card, columns=columns, show="headings",
            style="Viewer.Treeview", selectmode="browse"
        )
        
        headers = {
            "id": ("ID", 60),
            "source_cn": ("Chinese", 250),
            "target_en": ("English", 300),
            "banned": ("Banned", 300),
            "category": ("Category", 150),
        }
        for col, (text, width) in headers.items():
            self.gloss_viewer_tree.heading(col, text=text)
            self.gloss_viewer_tree.column(col, width=width, anchor="w" if col not in ("id",) else "center")
        
        vsb = ttk.Scrollbar(table_card, orient="vertical", command=self.gloss_viewer_tree.yview)
        hsb = ttk.Scrollbar(table_card, orient="horizontal", command=self.gloss_viewer_tree.xview)
        self.gloss_viewer_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.gloss_viewer_tree.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=(4, 0))
        vsb.grid(row=0, column=1, sticky="ns", pady=(4, 0))
        hsb.grid(row=1, column=0, sticky="ew", padx=(4, 0))
        
        self.gloss_viewer_tree.bind("<Double-1>", self._viewer_gloss_start_edit)
        
        # === STATUS BAR (row 2) ===
        status = ctk.CTkFrame(parent, fg_color="transparent", height=22)
        status.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 5))
        
        self.gloss_viewer_count = ctk.CTkLabel(
            status, text="0 rows",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_DIM
        )
        self.gloss_viewer_count.pack(side="left")
        
        ctk.CTkLabel(
            status, text="💡 Gõ vào ô Search để lọc real-time | Double-click để sửa",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED
        ).pack(side="right")
    
    # ==================== PAGE: PATCH UPDATER ====================
    def _create_page_patch(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)
        
        # Page header
        self._add_page_header(
            page,
            "🗓️  Patch Updater",
            "Cập nhật bản dịch cho phiên bản game mới nhất",
            row=0
        )
        
        # Card: Input/Output
        card = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=10)
        card.grid(row=1, column=0, sticky="ew", padx=30, pady=(0, 15))
        card.grid_columnconfigure(1, weight=1)
        
        # Input file
        ctk.CTkLabel(
            card, text="📥  Input Game File (.bytes):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))
        
        self.entry_patch_input = ctk.CTkEntry(
            card, placeholder_text="Chọn file LangPackageTableCnData.bytes mới...",
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=38
        )
        self.entry_patch_input.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 15))
        
        ctk.CTkButton(
            card, text="📁  Browse",
            width=110, height=32,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._browse_patch_input
        ).grid(row=1, column=2, padx=(0, 20), pady=(0, 15))
        
        # Output file
        ctk.CTkLabel(
            card, text="📤  Save Output Mod To:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        ).grid(row=2, column=0, sticky="w", padx=20, pady=(0, 8))
        
        self.entry_patch_output = ctk.CTkEntry(
            card, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=38
        )
        self.entry_patch_output.insert(0, str(Path.cwd() / "output" / "LangPackageTableCnData.bytes"))
        self.entry_patch_output.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 20))
        
        ctk.CTkButton(
            card, text="📂  Choose",
            width=110, height=32,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._browse_patch_output
        ).grid(row=3, column=2, padx=(0, 20), pady=(0, 20))
        
        # Action button
        action_frame = ctk.CTkFrame(page, fg_color="transparent")
        action_frame.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 15))
        
        self.btn_run_pipeline = ctk.CTkButton(
            action_frame,
            text="🚀  RUN FULL UPDATE PIPELINE",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", height=50, corner_radius=10,
            command=self._run_update_pipeline
        )
        self.btn_run_pipeline.pack(fill="x")
        
        # Log console
        log_frame = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=10)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=30, pady=(0, 20))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            log_frame, text="📋  Execution Log",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))
        
        self.log_patch = ctk.CTkTextbox(
            log_frame, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1, border_color=COLOR_BORDER, corner_radius=8
        )
        self.log_patch.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        self.log_patch.insert("0.0", "[Ready] Waiting for input...\n")
        self.log_patch.configure(state="disabled")
        
        return page
    
    # ==================== PAGE: SETUP ====================
    def _create_page_setup(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(3, weight=1)
        
        self._add_page_header(
            page, "⚙️  Import Base Translation",
            "Nhập bản dịch gốc (base.json) hoặc chuyển đổi từ định dạng cũ",
            row=0
        )
        
        # Card
        card = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=10)
        card.grid(row=1, column=0, sticky="ew", padx=30, pady=(0, 15))
        card.grid_columnconfigure(1, weight=1)
        
        # === MODE SELECTOR ===
        ctk.CTkLabel(
            card, text="🎯  Chọn chế độ:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(20, 8))
        
        self.setup_mode = tk.StringVar(value="import")
        
        mode_frame = ctk.CTkFrame(card, fg_color="transparent")
        mode_frame.grid(row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 15))
        
        ctk.CTkRadioButton(
            mode_frame, text="Import base.json (khuyên dùng)",
            variable=self.setup_mode, value="import",
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._toggle_setup_mode
        ).pack(side="left", padx=(0, 20))
        
        ctk.CTkRadioButton(
            mode_frame, text="Convert từ file cũ (ID-keyed)",
            variable=self.setup_mode, value="convert",
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._toggle_setup_mode
        ).pack(side="left")
        
        # === INPUT 1: FILE .BYTES ===
        self.setup_label_cn = ctk.CTkLabel(
            card, text="🇨🇳  Chinese Base File (.bytes):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        )
        self.setup_label_cn.grid(row=2, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 8))
        
        self.entry_setup_cn = ctk.CTkEntry(
            card, placeholder_text="File .bytes gốc tiếng Trung...",
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=38
        )
        self.entry_setup_cn.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 5))
        
        ctk.CTkButton(
            card, text="📁", width=50, height=32,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            command=lambda: self._browse_to(self.entry_setup_cn)
        ).grid(row=3, column=2, padx=(0, 20), pady=(0, 5))
        
        # === INPUT 2: FILE JSON ===
        self.setup_label_en = ctk.CTkLabel(
            card, text="📄  Translation File (.json):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        )
        self.setup_label_en.grid(row=4, column=0, columnspan=2, sticky="w", padx=20, pady=(15, 8))
        
        self.entry_setup_en = ctk.CTkEntry(
            card, placeholder_text="File base.json (hash format)...",
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=38
        )
        self.entry_setup_en.grid(row=5, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 20))
        
        ctk.CTkButton(
            card, text="📁", width=50, height=32,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            command=lambda: self._browse_to(self.entry_setup_en, [("JSON", "*.json")])
        ).grid(row=5, column=2, padx=(0, 20), pady=(0, 20))
        
        # === ACTION BUTTON ===
        self.btn_run_setup = ctk.CTkButton(
            page, text="⚡  IMPORT BASE TRANSLATION",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", height=50, corner_radius=10,
            command=self._run_setup
        )
        self.btn_run_setup.grid(row=2, column=0, sticky="ew", padx=30, pady=(0, 15))
        
        # === LOG ===
        log_frame = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=10)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=30, pady=(0, 20))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            log_frame, text="📋  Log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))
        
        self.log_setup = ctk.CTkTextbox(
            log_frame, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1, border_color=COLOR_BORDER, corner_radius=8
        )
        self.log_setup.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        self.log_setup.insert("0.0", "[Ready] Chọn chế độ và file để bắt đầu...\n")
        self.log_setup.configure(state="disabled")
        
        return page
    
    # ==================== PAGE: GLOSSARY ====================
    def _create_page_glossary(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        
        self._add_page_header(
            page, "📖  Glossary Manager",
            "Quản lý thuật ngữ, tên nhân vật và địa danh",
            row=0
        )
        
        # === TOOLBAR ===
        toolbar = ctk.CTkFrame(page, fg_color=COLOR_CARD, corner_radius=10)
        toolbar.grid(row=1, column=0, sticky="ew", padx=30, pady=(0, 8))
        
        # Search
        ctk.CTkLabel(
            toolbar, text="🔍", font=ctk.CTkFont(size=16),
            text_color=COLOR_TEXT_DIM
        ).pack(side="left", padx=(15, 5), pady=12)
        
        self.glossary_search = ctk.CTkEntry(
            toolbar, placeholder_text="Tìm kiếm thuật ngữ...",
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32, width=250
        )
        self.glossary_search.pack(side="left", padx=(0, 15), pady=12)
        self.glossary_search.bind("<KeyRelease>", lambda e: self._refresh_glossary_table())
        
        # Actions
        ctk.CTkButton(
            toolbar, text="➕  Add Term", height=32,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._glossary_add_term
        ).pack(side="left", padx=4, pady=12)
        
        ctk.CTkButton(
            toolbar, text="🔧  Audit & Auto-Fix", height=32,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._glossary_audit
        ).pack(side="left", padx=4, pady=12)
        
        ctk.CTkButton(
            toolbar, text="💾  Save", height=32,
            fg_color=COLOR_SUCCESS, hover_color="#45a049",
            text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._glossary_save
        ).pack(side="right", padx=(4, 15), pady=12)
        
        ctk.CTkButton(
            toolbar, text="📤  Export", height=32,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._glossary_export
        ).pack(side="right", padx=4, pady=12)
        
        ctk.CTkButton(
            toolbar, text="📥  Import", height=32,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._glossary_import
        ).pack(side="right", padx=4, pady=12)
        
        # === TABLE + LOG ===
        content_split = ctk.CTkFrame(page, fg_color="transparent")
        content_split.grid(row=2, column=0, sticky="nsew", padx=30, pady=(0, 20))
        content_split.grid_columnconfigure(0, weight=3)
        content_split.grid_columnconfigure(1, weight=2)
        content_split.grid_rowconfigure(0, weight=1)
        
        # --- Left: Table ---
        table_card = ctk.CTkFrame(content_split, fg_color=COLOR_CARD, corner_radius=10)
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        table_card.grid_columnconfigure(0, weight=1)
        table_card.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            table_card, text="📋  Danh sách thuật ngữ",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(12, 5))
        
        # Style cho Treeview
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Glossary.Treeview",
            background=COLOR_BG, foreground=COLOR_TEXT,
            fieldbackground=COLOR_BG, bordercolor=COLOR_BORDER,
            rowheight=28, font=("Consolas", 10)
        )
        style.configure(
            "Glossary.Treeview.Heading",
            background=COLOR_CARD, foreground=COLOR_ACCENT,
            font=("Arial", 10, "bold"), borderwidth=0
        )
        style.map("Glossary.Treeview", background=[("selected", COLOR_ACCENT)])
        style.map("Glossary.Treeview", foreground=[("selected", "#000000")])
        
        tree_frame = ctk.CTkFrame(table_card, fg_color=COLOR_BG, corner_radius=8)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)
        
        self.glossary_tree = ttk.Treeview(
            tree_frame,
            columns=("cn", "en", "type", "banned"),
            show="headings",
            style="Glossary.Treeview",
            selectmode="browse"
        )
        self.glossary_tree.heading("cn", text="Chinese")
        self.glossary_tree.heading("en", text="English")
        self.glossary_tree.heading("type", text="Type")
        self.glossary_tree.heading("banned", text="Banned")
        
        self.glossary_tree.column("cn", width=120, anchor="w")
        self.glossary_tree.column("en", width=150, anchor="w")
        self.glossary_tree.column("type", width=80, anchor="center")
        self.glossary_tree.column("banned", width=120, anchor="w")
        
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.glossary_tree.yview)
        self.glossary_tree.configure(yscrollcommand=scrollbar.set)
        
        self.glossary_tree.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=5)
        
        # Double-click để sửa
        self.glossary_tree.bind("<Double-1>", lambda e: self._glossary_edit_term())
        # Right-click menu
        self.glossary_tree.bind("<Button-3>", self._glossary_show_menu)
        
        # Selection info + buttons
        bottom_bar = ctk.CTkFrame(table_card, fg_color="transparent")
        bottom_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        
        self.glossary_count_label = ctk.CTkLabel(
            bottom_bar, text="0 entries",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_DIM
        )
        self.glossary_count_label.pack(side="left", padx=5)
        
        ctk.CTkButton(
            bottom_bar, text="🗑️", width=35, height=30,
            fg_color=COLOR_CARD, hover_color="#8b2c26",
            border_width=1, border_color=COLOR_BORDER,
            command=self._glossary_delete_term
        ).pack(side="right", padx=2)
        
        ctk.CTkButton(
            bottom_bar, text="✏️", width=35, height=30,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            command=self._glossary_edit_term
        ).pack(side="right", padx=2)
        
        # --- Right: Log ---
        log_card = ctk.CTkFrame(content_split, fg_color=COLOR_CARD, corner_radius=10)
        log_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            log_card, text="📋  Log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(12, 5))
        
        self.log_glossary = ctk.CTkTextbox(
            log_card, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=10),
            border_width=1, border_color=COLOR_BORDER, corner_radius=8
        )
        self.log_glossary.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_glossary.insert("0.0", "[Ready] Loading glossary...\n")
        self.log_glossary.configure(state="disabled")
        
        # Load glossary ban đầu
        page.after(100, self._load_glossary)
        
        return page
    
    # ==================== PAGE: TRANSLATE ====================
    def _create_page_translate(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        
        self._add_page_header(
            page, "🌐  Translation Tools",
            "Công cụ dịch tự động, phát hiện lỗi và sửa lỗi",
            row=0
        )
        
        # Sub-tabview
        self.translate_tabs = ctk.CTkTabview(
            page,
            fg_color=COLOR_CONTENT,
            segmented_button_fg_color=COLOR_CARD,
            segmented_button_selected_color=COLOR_ACCENT,
            segmented_button_selected_hover_color=COLOR_ACCENT_HOVER,
            segmented_button_unselected_color=COLOR_CARD,
            text_color=COLOR_TEXT,
            corner_radius=10,
            border_width=1,
            border_color=COLOR_BORDER
        )
        self.translate_tabs.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 20))
        
        # 3 sub-tab
        tab_auto = self.translate_tabs.add("🚀  Auto Translate")
        tab_find = self.translate_tabs.add("🔍  Find Errors")
        tab_apply = self.translate_tabs.add("🔧  Apply Fixes")
        
        self._build_subtab_auto_translate(tab_auto)
        self._build_subtab_find_errors(tab_find)
        self._build_subtab_apply_fixes(tab_apply)
        
        return page
    
    # ==================== SUB-TAB 1: AUTO TRANSLATE ====================
    def _build_subtab_auto_translate(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        # Cột trái: Settings
        left = ctk.CTkScrollableFrame(parent, fg_color=COLOR_CARD, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        
        ctk.CTkLabel(
            left, text="⚙️  Settings",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT
        ).pack(anchor="w", padx=15, pady=(15, 10))
        
        self._add_section(left, "🔑 DeepSeek API")
        self.entry_api_key = self._add_entry(left, "API Key:", "sk-...", show="●")
        self.entry_model = self._add_entry(left, "Model:", "", default="deepseek-chat")
        
        self._add_section(left, "📁 Files")
        self.entry_trans_input = self._add_file_input(left, "Input (update-XXX.json):", [("JSON", "*.json")])
        self.entry_trans_output = self._add_file_input(left, "Output (translated.json):", [("JSON", "*.json")], save=True)
        self.entry_trans_style = self._add_file_input(left, "Style Reference:", [("Text", "*.txt"), ("All", "*.*")])
        self.entry_trans_glossary = self._add_file_input(left, "Glossary:", [("Text", "*.txt"), ("All", "*.*")])
        
        self._add_section(left, "⚡ Performance")
        self.entry_batch_size = self._add_entry(left, "Batch Size:", "", default="30")
        self.entry_concurrent = self._add_entry(left, "Concurrent:", "", default="5")
        self.entry_style_max = self._add_entry(left, "Style Max Chars:", "", default="4000")
        self.entry_glossary_max = self._add_entry(left, "Glossary Max Chars:", "", default="15000")
        self.entry_max_retries = self._add_entry(left, "Max Retries:", "", default="3")
        
        # Cột phải: Action + Log
        right = ctk.CTkFrame(parent, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        
        self.btn_auto_translate = ctk.CTkButton(
            right, text="🚀  START AUTO TRANSLATE", height=50,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            command=self._run_auto_translate
        )
        self.btn_auto_translate.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        
        log_frame = ctk.CTkFrame(right, fg_color=COLOR_CARD, corner_radius=10)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            log_frame, text="📋  Log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(10, 5))
        
        self.log_translate = ctk.CTkTextbox(
            log_frame, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1, border_color=COLOR_BORDER, corner_radius=8
        )
        self.log_translate.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_translate.insert("0.0", "[Ready] Điền settings và nhấn START...\n")
        self.log_translate.configure(state="disabled")
    
    # ==================== SUB-TAB 2: FIND ERRORS ====================
    def _build_subtab_find_errors(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        # Cột trái: Settings
        left = ctk.CTkScrollableFrame(parent, fg_color=COLOR_CARD, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        
        ctk.CTkLabel(
            left, text="⚙️  Find Errors Settings",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT
        ).pack(anchor="w", padx=15, pady=(15, 10))
        
        # Bước 1: Export CN source
        self._add_section(left, "📤 Bước 1: Export CN source (nếu chưa có)")
        self.entry_export_bytes = self._add_file_input(
            left, "File .bytes CN (bản hiện tại):", [("Bytes", "*.bytes"), ("All", "*.*")]
        )
        self.entry_export_output = self._add_file_input(
            left, "Output CN JSON:", [("JSON", "*.json")], save=True
        )
        
        self.btn_export_cn = ctk.CTkButton(
            left, text="📤  EXPORT CN SOURCE", height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER, text_color=COLOR_TEXT,
            command=self._run_export_cn
        )
        self.btn_export_cn.pack(fill="x", padx=15, pady=(5, 10))
        
        # Bước 2: Find errors
        self._add_section(left, "🔍 Bước 2: Quét lỗi")
        self.entry_find_source = self._add_file_input(
            left, "Source (CN gốc):", [("JSON", "*.json")]
        )
        self.entry_find_translated = self._add_file_input(
            left, "Translated (EN đã dịch):", [("JSON", "*.json")]
        )
        self.entry_find_output = self._add_file_input(
            left, "Output (suspicious.json):", [("JSON", "*.json")], save=True
        )
        
        # Cột phải: Action + Log
        right = ctk.CTkFrame(parent, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        
        self.btn_find_errors = ctk.CTkButton(
            right, text="🔍  FIND ERRORS", height=50,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            command=self._run_find_errors
        )
        self.btn_find_errors.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        
        log_frame = ctk.CTkFrame(right, fg_color=COLOR_CARD, corner_radius=10)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            log_frame, text="📋  Log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(10, 5))
        
        self.log_find = ctk.CTkTextbox(
            log_frame, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1, border_color=COLOR_BORDER, corner_radius=8
        )
        self.log_find.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_find.insert("0.0", "[Ready] Chọn file và nhấn FIND ERRORS...\n")
        self.log_find.configure(state="disabled")
    
    # ==================== SUB-TAB 3: APPLY FIXES ====================
    def _build_subtab_apply_fixes(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        
        # Cột trái: Settings
        left = ctk.CTkScrollableFrame(parent, fg_color=COLOR_CARD, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        
        ctk.CTkLabel(
            left, text="⚙️  Apply Fixes Settings",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT
        ).pack(anchor="w", padx=15, pady=(15, 10))
        
        self._add_section(left, "📁 Files")
        self.entry_apply_corrections = self._add_file_input(
            left, "Corrections (suspicious.json):", [("JSON", "*.json")]
        )
        self.entry_apply_translated = self._add_file_input(
            left, "Translated (file cần sửa):", [("JSON", "*.json")]
        )
        
        self._add_section(left, "⚙️ Options")
        
        self.var_auto_backup = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            left, text="Tự động sao lưu trước khi sửa",
            variable=self.var_auto_backup,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12)
        ).pack(anchor="w", padx=15, pady=10)
        
        # Cột phải: Action + Log
        right = ctk.CTkFrame(parent, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        
        self.btn_apply_fixes = ctk.CTkButton(
            right, text="🔧  APPLY FIXES", height=50,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000",
            command=self._run_apply_fixes
        )
        self.btn_apply_fixes.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        
        log_frame = ctk.CTkFrame(right, fg_color=COLOR_CARD, corner_radius=10)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            log_frame, text="📋  Log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(10, 5))
        
        self.log_apply = ctk.CTkTextbox(
            log_frame, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1, border_color=COLOR_BORDER, corner_radius=8
        )
        self.log_apply.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_apply.insert("0.0", "[Ready] Chọn file và nhấn APPLY FIXES...\n")
        self.log_apply.configure(state="disabled")
    # ==================== PAGE: SETTING ====================
    def _create_page_settings(self):
        """Tab Settings: cấu hình GitHub + Google Drive upload."""
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        
        self._add_page_header(
            page, "⚙️  Settings",
            "Cấu hình auto-upload cho GitHub và Google Drive",
            row=0
        )
        
        # Scrollable container
        container = ctk.CTkScrollableFrame(page, fg_color="transparent")
        container.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 20))
        container.grid_columnconfigure(0, weight=1)
        
        # Load config hiện tại
        self.upload_config = uploader.load_config()
        
        # ==================== AUTO-UPLOAD TOGGLE ====================
        toggle_card = ctk.CTkFrame(container, fg_color=COLOR_CARD, corner_radius=8)
        toggle_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        self.auto_upload_var = tk.BooleanVar(value=self.upload_config.get("auto_upload_after_patch", False))
        ctk.CTkCheckBox(
            toggle_card, text="🚀  Tự động upload SAU KHI chạy Patch Updater",
            variable=self.auto_upload_var,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=13, weight="bold"),
            checkbox_width=22, checkbox_height=22,
            command=self._settings_toggle_auto_upload
        ).pack(padx=20, pady=15, anchor="w")
        
        # ==================== GITHUB ====================
        gh_card = ctk.CTkFrame(container, fg_color=COLOR_CARD, corner_radius=8)
        gh_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        gh_card.grid_columnconfigure(1, weight=1)
        
        # Header
        gh_header = ctk.CTkFrame(gh_card, fg_color="transparent")
        gh_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(15, 5))
        gh_header.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(
            gh_header, text="🐙  GitHub Release Upload",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT
        ).grid(row=0, column=0, sticky="w")
        
        gh_enabled = tk.BooleanVar(value=self.upload_config.get("github", {}).get("enabled", False))
        self.gh_enabled_var = gh_enabled
        ctk.CTkCheckBox(
            gh_header, text="Enable",
            variable=gh_enabled,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18,
            command=self._settings_save
        ).grid(row=0, column=1, sticky="e")
        
        # Username
        ctk.CTkLabel(
            gh_card, text="Username:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).grid(row=1, column=0, sticky="w", padx=20, pady=5)
        
        self.gh_username_entry = ctk.CTkEntry(
            gh_card, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32
        )
        self.gh_username_entry.grid(row=1, column=1, sticky="ew", padx=(0, 20), pady=5)
        self.gh_username_entry.insert(0, self.upload_config.get("github", {}).get("username", ""))
        
        # Repo
        ctk.CTkLabel(
            gh_card, text="Repository:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).grid(row=2, column=0, sticky="w", padx=20, pady=5)
        
        self.gh_repo_entry = ctk.CTkEntry(
            gh_card, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32,
            placeholder_text="VD: gfl2-translation-patches"
        )
        self.gh_repo_entry.grid(row=2, column=1, sticky="ew", padx=(0, 20), pady=5)
        self.gh_repo_entry.insert(0, self.upload_config.get("github", {}).get("repo", ""))
        
        # Token
        ctk.CTkLabel(
            gh_card, text="Personal Token:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).grid(row=3, column=0, sticky="w", padx=20, pady=5)
        
        self.gh_token_entry = ctk.CTkEntry(
            gh_card, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32, show="●",
            placeholder_text="ghp_..."
        )
        self.gh_token_entry.grid(row=3, column=1, sticky="ew", padx=(0, 20), pady=5)
        self.gh_token_entry.insert(0, self.upload_config.get("github", {}).get("token", ""))
        
        # Tag prefix
        ctk.CTkLabel(
            gh_card, text="Tag prefix:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).grid(row=4, column=0, sticky="w", padx=20, pady=(5, 15))
        
        self.gh_tag_entry = ctk.CTkEntry(
            gh_card, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32, placeholder_text="patch"
        )
        self.gh_tag_entry.grid(row=4, column=1, sticky="ew", padx=(0, 20), pady=(5, 15))
        self.gh_tag_entry.insert(0, self.upload_config.get("github", {}).get("tag_prefix", "patch"))
        
        # ==================== GOOGLE DRIVE ====================
        gd_card = ctk.CTkFrame(container, fg_color=COLOR_CARD, corner_radius=8)
        gd_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        gd_card.grid_columnconfigure(1, weight=1)
        
        # Header
        gd_header = ctk.CTkFrame(gd_card, fg_color="transparent")
        gd_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(15, 5))
        gd_header.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(
            gd_header, text="📁  Google Drive Upload",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT
        ).grid(row=0, column=0, sticky="w")
        
        gd_enabled = tk.BooleanVar(value=self.upload_config.get("gdrive", {}).get("enabled", False))
        self.gd_enabled_var = gd_enabled
        ctk.CTkCheckBox(
            gd_header, text="Enable",
            variable=gd_enabled,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18,
            command=self._settings_save
        ).grid(row=0, column=1, sticky="e")
        
        # Service Account file
        ctk.CTkLabel(
            gd_card, text="Service Account:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).grid(row=1, column=0, sticky="w", padx=20, pady=5)
        
        sa_frame = ctk.CTkFrame(gd_card, fg_color="transparent")
        sa_frame.grid(row=1, column=1, sticky="ew", padx=(0, 20), pady=5)
        sa_frame.grid_columnconfigure(0, weight=1)
        
        self.gd_sa_entry = ctk.CTkEntry(
            sa_frame, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32,
            placeholder_text="gdrive_service_account.json"
        )
        self.gd_sa_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.gd_sa_entry.insert(0, self.upload_config.get("gdrive", {}).get("service_account_file", "gdrive_service_account.json"))
        
        ctk.CTkButton(
            sa_frame, text="📁", width=40, height=32,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            command=lambda: self._browse_to(self.gd_sa_entry, [("JSON", "*.json")])
        ).grid(row=0, column=1)
        
        # Folder ID
        ctk.CTkLabel(
            gd_card, text="Folder ID:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).grid(row=2, column=0, sticky="w", padx=20, pady=(5, 15))
        
        self.gd_folder_entry = ctk.CTkEntry(
            gd_card, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32,
            placeholder_text="Copy ID từ URL folder Drive"
        )
        self.gd_folder_entry.grid(row=2, column=1, sticky="ew", padx=(0, 20), pady=(5, 15))
        self.gd_folder_entry.insert(0, self.upload_config.get("gdrive", {}).get("folder_id", ""))
        
        # ==================== ACTION BUTTONS ====================
        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        actions.grid_columnconfigure((0, 1, 2), weight=1)
        
        ctk.CTkButton(
            actions, text="💾  Save Config", height=44,
            fg_color=COLOR_SUCCESS, hover_color="#45a049",
            text_color="#000000", font=ctk.CTkFont(size=13, weight="bold"),
            command=self._settings_save
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        ctk.CTkButton(
            actions, text="🧪  Test Upload", height=44,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=13, weight="bold"),
            command=self._settings_test
        ).grid(row=0, column=1, sticky="ew", padx=5)
        
        ctk.CTkButton(
            actions, text="📤  Upload Now", height=44,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=13),
            command=self._settings_upload_now
        ).grid(row=0, column=2, sticky="ew", padx=(5, 0))
        
        # ==================== LOG ====================
        log_frame = ctk.CTkFrame(container, fg_color=COLOR_CARD, corner_radius=8)
        log_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        
        ctk.CTkLabel(
            log_frame, text="📋  Log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).pack(anchor="w", padx=15, pady=(10, 5))
        
        self.log_settings = ctk.CTkTextbox(
            log_frame, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=10),
            border_width=1, border_color=COLOR_BORDER,
            corner_radius=6, height=150
        )
        self.log_settings.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_settings.insert("0.0", "[Ready] Cấu hình và nhấn Save Config...\n")
        self.log_settings.configure(state="disabled")
        
        return page
    
    # ==================== SETTINGS HANDLERS ====================
    def _settings_toggle_auto_upload(self):
        """Toggle auto-upload and auto-save."""
        self._settings_save()
    
    def _settings_save(self):
        """Lưu config vào file."""
        config = {
            "github": {
                "enabled": self.gh_enabled_var.get(),
                "username": self.gh_username_entry.get().strip(),
                "repo": self.gh_repo_entry.get().strip(),
                "token": self.gh_token_entry.get().strip(),
                "tag_prefix": self.gh_tag_entry.get().strip() or "patch",
            },
            "gdrive": {
                "enabled": self.gd_enabled_var.get(),
                "service_account_file": self.gd_sa_entry.get().strip(),
                "folder_id": self.gd_folder_entry.get().strip(),
            },
            "auto_upload_after_patch": self.auto_upload_var.get(),
        }
        
        try:
            uploader.save_config(config)
            self._log(self.log_settings, "[OK] ✅ Đã lưu config vào upload_config.json")
            
            # Log tóm tắt
            gh_status = "✅ ON" if config["github"]["enabled"] else "❌ OFF"
            gd_status = "✅ ON" if config["gdrive"]["enabled"] else "❌ OFF"
            auto_status = "✅ ON" if config["auto_upload_after_patch"] else "❌ OFF"
            
            self._log(self.log_settings, f"     GitHub: {gh_status}")
            self._log(self.log_settings, f"     GDrive: {gd_status}")
            self._log(self.log_settings, f"     Auto-upload sau Patch: {auto_status}")
        except Exception as e:
            self._log(self.log_settings, f"[ERROR] {e}")
    
    def _settings_test(self):
        """Test upload với file dummy."""
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Vui lòng đợi!")
            return
        
        # Save config trước
        self._settings_save()
        
        config = uploader.load_config()
        
        if not config.get("github", {}).get("enabled") and not config.get("gdrive", {}).get("enabled"):
            messagebox.showinfo("Thông báo", "Bật ít nhất 1 trong GitHub/GDrive để test!")
            return
        
        self.pipeline_running = True
        self._log(self.log_settings, "")
        self._log(self.log_settings, "=" * 50)
        self._log(self.log_settings, "[TEST] Bắt đầu test upload...")
        self._log(self.log_settings, "=" * 50)
        
        def worker():
            try:
                results = uploader.test_config(self.log_queue_settings)
                
                self.log_queue_settings.put("")
                self.log_queue_settings.put("=" * 50)
                self.log_queue_settings.put("[TEST] Kết quả:")
                
                if results.get("github"):
                    gh = results["github"]
                    status = "✅ OK" if gh["success"] else "❌ FAIL"
                    self.log_queue_settings.put(f"  GitHub: {status}")
                    if gh["success"]:
                        self.log_queue_settings.put(f"    URL: {gh['msg']}")
                    else:
                        self.log_queue_settings.put(f"    Error: {gh['msg']}")
                
                if results.get("gdrive"):
                    gd = results["gdrive"]
                    status = "✅ OK" if gd["success"] else "❌ FAIL"
                    self.log_queue_settings.put(f"  GDrive: {status}")
                    if gd["success"]:
                        self.log_queue_settings.put(f"    URL: {gd['msg']}")
                    else:
                        self.log_queue_settings.put(f"    Error: {gd['msg']}")
            except Exception as e:
                self.log_queue_settings.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_settings.put(traceback.format_exc())
            finally:
                self.log_queue_settings.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_settings_queue()
    
    def _settings_upload_now(self):
        """Upload file output hiện tại."""
        output_file = "output/LangPackageTableCnData.bytes"
        
        if not Path(output_file).exists():
            messagebox.showerror(
                "Lỗi",
                f"Không tìm thấy file:\n{output_file}\n\n"
                "Hãy chạy Patch Updater trước để tạo file."
            )
            return
        
        if not messagebox.askyesno(
            "Xác nhận",
            f"Upload file:\n{output_file}\n\n"
            f"Size: {Path(output_file).stat().st_size / 1024 / 1024:.2f} MB\n\n"
            "Tiếp tục?"
        ):
            return
        
        if self.pipeline_running:
            return
        self.pipeline_running = True
        
        self._log(self.log_settings, "")
        self._log(self.log_settings, "[INFO] Bắt đầu upload...")
        
        def worker():
            try:
                uploader.auto_upload_after_patch(output_file, self.log_queue_settings)
            except Exception as e:
                self.log_queue_settings.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_settings.put(traceback.format_exc())
            finally:
                self.log_queue_settings.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_settings_queue()
    
    def _poll_settings_queue(self):
        """Poll queue cho Settings tab."""
        try:
            while True:
                line = self.log_queue_settings.get_nowait()
                if line == "__DONE__":
                    self.pipeline_running = False
                    return
                self._log(self.log_settings, line)
        except queue.Empty:
            pass
        self.after(100, self._poll_settings_queue)
    # ==================== PAGE: BACKUP ====================
    def _create_page_backup(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        
        self._add_page_header(
            page, "💾  Backup & Utilities",
            "Sao lưu, phục hồi và các tiện ích hệ thống",
            row=0
        )
        
        # Container 2 cột
        container = ctk.CTkFrame(page, fg_color="transparent")
        container.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 20))
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=1)
        container.grid_rowconfigure(0, weight=1)
        
        # === CỘT TRÁI ===
        left = ctk.CTkScrollableFrame(container, fg_color=COLOR_CARD, corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        
        # --- System Info ---
        self._add_section(left, "📊 Thông tin hệ thống")
        
        self.info_textbox = ctk.CTkTextbox(
            left, fg_color=COLOR_BG, text_color=COLOR_TEXT,
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1, border_color=COLOR_BORDER,
            corner_radius=8, height=180
        )
        self.info_textbox.pack(fill="x", padx=15, pady=(5, 10))
        self.info_textbox.insert("0.0", "Đang tải...")
        self.info_textbox.configure(state="disabled")
        
        ctk.CTkButton(
            left, text="🔄  Refresh Info", height=34,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._backup_refresh_info
        ).pack(fill="x", padx=15, pady=(0, 15))
        
        # --- Backup ---
        self._add_section(left, "💾 Backup")
        
        ctk.CTkButton(
            left, text="📦  Create Backup (zip)", height=40,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._backup_create
        ).pack(fill="x", padx=15, pady=(5, 5))
        
        ctk.CTkButton(
            left, text="📂  Restore from Backup", height=40,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._backup_restore
        ).pack(fill="x", padx=15, pady=(0, 5))
        
        ctk.CTkButton(
            left, text="📋  View Backup List", height=40,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._backup_list
        ).pack(fill="x", padx=15, pady=(0, 15))
        
        # --- Utilities ---
        self._add_section(left, "🔧 Utilities")
        
        ctk.CTkButton(
            left, text="📤  Export All Translations", height=40,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._backup_export_all
        ).pack(fill="x", padx=15, pady=(5, 5))
        
        ctk.CTkButton(
            left, text="🗑️  Clear Temp Files", height=40,
            fg_color=COLOR_CARD, hover_color="#8b2c26",
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=self._backup_clear_temp
        ).pack(fill="x", padx=15, pady=(0, 15))
        
        # --- Open Folders ---
        self._add_section(left, "📁 Open Folders")
        
        folder_frame = ctk.CTkFrame(left, fg_color="transparent")
        folder_frame.pack(fill="x", padx=15, pady=(5, 15))
        folder_frame.grid_columnconfigure((0, 1), weight=1)
        
        for i, (text, path) in enumerate([
            ("📂 translations/", "translations"),
            ("📂 output/", "output"),
            ("📂 backups/", "backups"),
            ("📂 Root folder", "."),
        ]):
            row, col = divmod(i, 2)
            ctk.CTkButton(
                folder_frame, text=text, height=36,
                fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
                border_width=1, border_color=COLOR_BORDER,
                text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
                command=lambda p=path: self._open_folder(p)
            ).grid(row=row, column=col, sticky="ew", padx=3, pady=3)
        
        # === CỘT PHẢI: LOG ===
        right = ctk.CTkFrame(container, fg_color=COLOR_CARD, corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        
        ctk.CTkLabel(
            right, text="📋  Log",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(12, 5))
        
        self.log_backup = ctk.CTkTextbox(
            right, fg_color=COLOR_BG, text_color="#58a6ff",
            font=ctk.CTkFont(family="Consolas", size=10),
            border_width=1, border_color=COLOR_BORDER, corner_radius=8
        )
        self.log_backup.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_backup.insert("0.0", "[Ready] Chọn thao tác...\n")
        self.log_backup.configure(state="disabled")
        
        # Load info sau khi UI render xong
        page.after(200, self._backup_refresh_info)
        
        return page
    
    # ==================== HELPERS ====================
    def _add_page_header(self, parent, title, subtitle, row=0):
        """Thêm header cho page."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=30, pady=(25, 20))
        
        ctk.CTkLabel(
            frame, text=title,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLOR_TEXT, anchor="w"
        ).pack(anchor="w")
        
        ctk.CTkLabel(
            frame, text=subtitle,
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM, anchor="w"
        ).pack(anchor="w", pady=(4, 0))

    def _add_section(self, parent, title):
        """Thêm tiêu đề phân vùng trong settings."""
        ctk.CTkFrame(parent, fg_color=COLOR_BORDER, height=1).pack(
            fill="x", padx=15, pady=(15, 5)
        )
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_ACCENT
        ).pack(anchor="w", padx=15, pady=(5, 5))
    
    def _add_entry(self, parent, label, placeholder, default="", show=None):
        """Thêm entry với label vào settings."""
        ctk.CTkLabel(
            parent, text=label,
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT
        ).pack(anchor="w", padx=15, pady=(5, 2))
        
        entry = ctk.CTkEntry(
            parent, placeholder_text=placeholder,
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32, show=show
        )
        entry.pack(fill="x", padx=15, pady=(0, 5))
        
        if default:
            entry.insert(0, default)
        
        return entry
    
    def _add_file_input(self, parent, label, filetypes, save=False):
        """Thêm file input với nút browse."""
        ctk.CTkLabel(
            parent, text=label,
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT
        ).pack(anchor="w", padx=15, pady=(5, 2))
        
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=15, pady=(0, 5))
        frame.grid_columnconfigure(0, weight=1)
        
        entry = ctk.CTkEntry(
            frame, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=32
        )
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        def browse():
            if save:
                # Lấy đuôi file từ filetypes đầu tiên (ví dụ: "*.json" → ".json")
                default_ext = ""
                if filetypes:
                    first_pattern = filetypes[0][1]
                    if first_pattern.startswith("*"):
                        default_ext = first_pattern[1:]  # "*.json" → ".json"
                
                path = filedialog.asksaveasfilename(
                    filetypes=filetypes,
                    defaultextension=default_ext
                )
            else:
                path = filedialog.askopenfilename(filetypes=filetypes)
            if path:
                entry.delete(0, "end")
                entry.insert(0, path)
        
        ctk.CTkButton(
            frame, text="📁", width=35, height=32,
            fg_color=COLOR_BG, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            command=browse
        ).grid(row=0, column=1)
        
        return entry
    
    def _build_status_bar(self):
        status = ctk.CTkFrame(self, fg_color=COLOR_SIDEBAR, height=28, corner_radius=0)
        status.grid(row=2, column=0, sticky="ew")
        status.grid_propagate(False)
        
        ctk.CTkLabel(
            status, text="● Ready",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=COLOR_SUCCESS
        ).pack(side="left", padx=15)
        
        ctk.CTkLabel(
            status, text=f"{APP_VERSION}  |  Press ESC to exit",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=COLOR_TEXT_MUTED
        ).pack(side="right", padx=15)
    
    def _browse_patch_input(self):
        path = filedialog.askopenfilename(
            title="Chọn file .bytes mới",
            filetypes=[("Bytes files", "*.bytes"), ("All files", "*.*")]
        )
        if path:
            self.entry_patch_input.delete(0, "end")
            self.entry_patch_input.insert(0, path)
    
    def _browse_patch_output(self):
        path = filedialog.asksaveasfilename(
            title="Chọn nơi lưu file output",
            defaultextension=".bytes",
            filetypes=[("Bytes files", "*.bytes")]
        )
        if path:
            self.entry_patch_output.delete(0, "end")
            self.entry_patch_output.insert(0, path)

    def _log(self, textbox, message):
        """Ghi log vào textbox."""
        textbox.configure(state="normal")
        textbox.insert("end", message + "\n")
        textbox.see("end")
        textbox.configure(state="disabled")

    def _browse_to(self, entry_widget, filetypes=None):
        if filetypes is None:
            filetypes = [("Bytes files", "*.bytes"), ("All files", "*.*")]
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, path)

    def _toggle_setup_mode(self):
        """Cập nhật placeholder khi user đổi mode."""
        mode = self.setup_mode.get()
        
        # Clear
        self.entry_setup_en.delete(0, "end")
        
        if mode == "import":
            self.setup_label_en.configure(text="📄  Translation File (.json):")
            self.entry_setup_en.configure(placeholder_text="File base.json (hash format)...")
            self.btn_run_setup.configure(text="⚡  IMPORT BASE TRANSLATION")
        else:  # convert
            self.setup_label_en.configure(text="📄  Old Translation File (.json):")
            self.entry_setup_en.configure(placeholder_text="File translations.json cũ (ID-keyed)...")
            self.btn_run_setup.configure(text="⚡  CONVERT TO NEW FORMAT")    

    def _update_info(self):
        translations_dir = Path("translations")
        if translations_dir.exists():
            files = list(translations_dir.glob("*.json"))
            self.info_label.configure(
                text=f"📁 Thư mục translations: {len(files)} files\n"
                     f"📍 Đường dẫn: {translations_dir.resolve()}"
            )
        else:
            self.info_label.configure(
                text="⚠️ Chưa có thư mục 'translations'.\n"
                     "→ Hãy chạy 'First-Time Setup' trước."
            )
    
    def _update_sidebar_info(self):
        translations_dir = Path("translations")
        if translations_dir.exists():
            files = list(translations_dir.glob("*.json"))
            self.sidebar_info.configure(text=f"📁 {len(files)} translation files")
        else:
            self.sidebar_info.configure(text="📁 No translations yet")

    # ==================== VIEWER HANDLERS ====================

    def _viewer_toggle_toolbar(self):
        """Ẩn/hiện toolbar."""
        if self.toolbar_visible.get():
            self.viewer_toolbar_frame.grid()
        else:
            self.viewer_toolbar_frame.grid_remove()
    
    def _viewer_toggle_filter(self):
        """Ẩn/hiện filter bar."""
        if self.filter_visible.get():
            self.viewer_filter_bar.grid()
        else:
            self.viewer_filter_bar.grid_remove()
    
    def _viewer_toggle_subtab(self):
        """Ẩn/hiện sub-tabview (Translations/Glossary)."""
        if self.subtab_visible.get():
            self.viewer_tabs.grid()
        else:
            self.viewer_tabs.grid_remove()
    def _viewer_subtab_changed(self):
        """Xử lý khi đổi sub-tab."""
        current = self.viewer_tabs.get()
        if "Glossary" in current:
            self.viewer_current_subtab = "glossary"
        else:
            self.viewer_current_subtab = "translations"
    
    def _viewer_load(self):
        """Load tất cả translations vào DB."""
        if self.pipeline_running:
            return
        self.pipeline_running = True
        
        self._log(self.log_viewer, "")
        self._log(self.log_viewer, "=" * 50)
        self._log(self.log_viewer, "[INFO] Đang load translations...")
        self._log(self.log_viewer, "=" * 50)
        
        def worker():
            try:
                # Reset DB
                self.viewer_db = viewer.TranslationViewerDB()
                
                # Load tất cả
                self.viewer_db.load_all_translations("translations", log_queue=self.log_queue_viewer)
                
                # Compute frequency
                self.viewer_db.compute_frequency(self.log_queue_viewer)
                
                # Load glossary vào DB riêng
                meta_entries = gl.load_glossary_meta("glossary_meta.json")
                if not meta_entries:
                    meta_entries = gl.load_glossary_txt("glossary.txt")
                if self.glossary_db.count() == 0:
                    meta_entries = gl.load_glossary_meta("glossary_meta.json")
                    if not meta_entries:
                        meta_entries = gl.load_glossary_txt("glossary.txt")
                    self.glossary_db.load_entries(meta_entries, self.log_queue_viewer)
                
                stats = self.viewer_db.get_stats()
                self.log_queue_viewer.put(f"[OK] Tổng: {stats['total']:,} câu")
                self.log_queue_viewer.put(f"[OK] Đã dịch: {stats['translated']:,}")
                self.log_queue_viewer.put(f"[OK] Còn tiếng Trung: {stats['still_chinese']:,}")
                self.log_queue_viewer.put(f"[OK] Câu độc nhất: {stats['unique_cn']:,}")
                
                # Refresh UI
                self.after(0, lambda: self._viewer_refresh_tables(stats))
            except Exception as e:
                self.log_queue_viewer.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_viewer.put(traceback.format_exc())
            finally:
                self.log_queue_viewer.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_viewer_queue()
    
    def _viewer_refresh_tables(self, stats=None):
        """Refresh cả 2 bảng."""
        if stats:
            self.viewer_stats_label.configure(
                text=f"📊 {stats['total']:,} rows | {stats['still_chinese']:,} còn CN"
            )
        
        # Refresh translations table
        where = self.viewer_filter_entry.get().strip()
        try:
            rows = self.viewer_db.query(where, order_by=f"{self.viewer_sort_column} {self.viewer_sort_order}")
        except Exception as e:
            self._log(self.log_viewer, f"[ERROR] Query: {e}")
            return
        
        for item in self.viewer_tree.get_children():
            self.viewer_tree.delete(item)
        
        for row in rows:
            # Truncate dài
            cn = row["source_cn"][:80] + "..." if len(row["source_cn"]) > 80 else row["source_cn"]
            en = row["target_en"][:80] + "..." if len(row["target_en"]) > 80 else row["target_en"]
            
            self.viewer_tree.insert("", "end", iid=row["hash"], values=(
                row["id"], cn, en, row["frequency"], row["source_type"], row["source_file"]
            ))
        
        self.viewer_row_count.configure(text=f"{len(rows):,} rows")
        
        # Refresh glossary table
        g_where = self.gloss_viewer_filter.get().strip()
        g_rows = self.glossary_db.query(g_where)
        
        for item in self.gloss_viewer_tree.get_children():
            self.gloss_viewer_tree.delete(item)
        
        for row in g_rows:
            self.gloss_viewer_tree.insert("", "end", iid=str(row["id"]), values=(
                row["id"], row["source_cn"], row["target_en"],
                row["banned_translations"], row["category"]
            ))
        
        self.gloss_viewer_count.configure(text=f"{len(g_rows):,} rows")

    # ==================== REPLACE ALL ====================
    def _viewer_open_replace_all(self):
        """Mở dialog Replace All."""
        # Nếu dialog đã mở → focus vào nó
        if self.replace_dialog is not None and self.replace_dialog.winfo_exists():
            self.replace_dialog.focus_force()
            return
        
        dialog = ctk.CTkToplevel(self)
        dialog.title("🔄 Replace All")
        dialog.geometry("720x780")
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        self.replace_dialog = dialog
        
        # === HEADER ===
        ctk.CTkLabel(
            dialog, text="🔄  Replace All",
            font=ctk.CTkFont(size=18, weight="bold"), text_color=COLOR_ACCENT
        ).pack(anchor="w", padx=20, pady=(15, 5))
        
        ctk.CTkLabel(
            dialog, text="Tìm và thay thế hàng loạt trong database (chưa lưu file).\n"
                         "Bạn cần nhấn 'Save Changes' sau khi apply để ghi vào file.",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM,
            justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 15))
        
        # === INPUTS ===
        inputs = ctk.CTkFrame(dialog, fg_color=COLOR_CARD, corner_radius=8)
        inputs.pack(fill="x", padx=20, pady=(0, 10))
        inputs.grid_columnconfigure(1, weight=1)
        
        # Find
        ctk.CTkLabel(
            inputs, text="🔍 Find:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))
        
        find_entry = ctk.CTkEntry(
            inputs, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=36,
            placeholder_text="Text cần tìm (ví dụ: abc)"
        )
        find_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(0, 15), pady=(15, 5))
        
        # Replace with
        ctk.CTkLabel(
            inputs, text="✏️ Replace with:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=1, column=0, sticky="w", padx=15, pady=5)
        
        replace_entry = ctk.CTkEntry(
            inputs, fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=36,
            placeholder_text="Text thay thế (ví dụ: xyz)"
        )
        replace_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 15), pady=5)
        
        # Target column
        ctk.CTkLabel(
            inputs, text="📊 Trong cột:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=2, column=0, sticky="w", padx=15, pady=5)
        
        target_col_var = tk.StringVar(value="Target EN")
        ctk.CTkOptionMenu(
            inputs, variable=target_col_var,
            values=["Target EN", "Source CN", "Cả hai"],
            width=180, height=36,
            fg_color=COLOR_BG, button_color=COLOR_BORDER,
            button_hover_color=COLOR_ACCENT,
            dropdown_fg_color=COLOR_CARD,
            dropdown_hover_color=COLOR_ACCENT,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12)
        ).grid(row=2, column=1, sticky="w", padx=0, pady=5)
        
        # Match mode
        ctk.CTkLabel(
            inputs, text="🎯 Match mode:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).grid(row=3, column=0, sticky="w", padx=15, pady=5)
        
        mode_var = tk.StringVar(value="Contains (substring)")
        ctk.CTkOptionMenu(
            inputs, variable=mode_var,
            values=["Exact match", "Contains (substring)", "Word boundary"],
            width=180, height=36,
            fg_color=COLOR_BG, button_color=COLOR_BORDER,
            button_hover_color=COLOR_ACCENT,
            dropdown_fg_color=COLOR_CARD,
            dropdown_hover_color=COLOR_ACCENT,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12)
        ).grid(row=3, column=1, sticky="w", padx=0, pady=5)
        
        # Case sensitive
        case_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            inputs, text="Case sensitive",
            variable=case_var,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18
        ).grid(row=3, column=2, sticky="w", padx=15, pady=5)
        
        # === PREVIEW AREA HEADER ===
        preview_header = ctk.CTkFrame(dialog, fg_color="transparent")
        preview_header.pack(fill="x", padx=20, pady=(10, 5))
        
        ctk.CTkLabel(
            preview_header, text="📋  Preview:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT
        ).pack(side="left")
        
        # ⚡ Input số rows
        ctk.CTkLabel(
            preview_header, text="Rows:",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_DIM
        ).pack(side="left", padx=(15, 3))
        
        preview_limit_var = tk.StringVar(value="50")
        limit_entry = ctk.CTkEntry(
            preview_header, textvariable=preview_limit_var,
            width=70, height=28,
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11)
        )
        limit_entry.pack(side="left", padx=3)
        
        ctk.CTkLabel(
            preview_header, text="(hoặc 'all')",
            font=ctk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED
        ).pack(side="left")
        
        # Nút Apply limit
        ctk.CTkButton(
            preview_header, text="🔄", width=35, height=28,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            command=lambda: self._replace_do_preview(dialog)
        ).pack(side="left", padx=5)
        
        # ⚡ Toggle Full/Truncate
        full_text_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            preview_header, text="Show full text",
            variable=full_text_var,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=11),
            checkbox_width=18, checkbox_height=18,
            command=lambda: self._replace_do_preview(dialog)
        ).pack(side="right", padx=10)
        
        # Lưu vào dialog
        dialog.full_text_var = full_text_var
        dialog.preview_limit_var = preview_limit_var
        
        preview_frame = ctk.CTkFrame(dialog, fg_color=COLOR_BG, corner_radius=6)
        preview_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        
        preview_text = ctk.CTkTextbox(
            preview_frame, fg_color=COLOR_BG, text_color=COLOR_TEXT,
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=0, corner_radius=6
        )
        preview_text.pack(fill="both", expand=True, padx=5, pady=5)
        preview_text.insert("0.0", "Nhấn 'Preview' để xem trước kết quả.\n")
        preview_text.configure(state="disabled")
        
        # Store preview widget + inputs vào dialog để truy cập từ handler
        dialog.find_entry = find_entry
        dialog.replace_entry = replace_entry
        dialog.target_col_var = target_col_var
        dialog.mode_var = mode_var
        dialog.case_var = case_var
        dialog.preview_text = preview_text
        
        # === BUTTONS ===
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 15))
        
        ctk.CTkButton(
            btn_frame, text="🔍 Preview", height=40, width=140,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._replace_do_preview(dialog)
        ).pack(side="left", padx=(0, 5))
        
        ctk.CTkButton(
            btn_frame, text="🔄 Apply Replace", height=40, width=160,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._replace_do_apply(dialog)
        ).pack(side="left", padx=5)
        
        ctk.CTkButton(
            btn_frame, text="Close", height=40, width=100,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=ctk.CTkFont(size=12),
            command=dialog.destroy
        ).pack(side="right")
    
    def _replace_do_preview(self, dialog):
        """Preview kết quả replace."""
        find_text = dialog.find_entry.get()
        target_col = dialog.target_col_var.get()
        mode = dialog.mode_var.get()
        case_sensitive = dialog.case_var.get()
        
        # ⚡ Lấy toggle Full/Truncate
        show_full = getattr(dialog, "full_text_var", None)
        show_full = show_full.get() if show_full else True
        
        # ⚡ Lấy limit từ input
        limit_str = dialog.preview_limit_var.get().strip().lower() if hasattr(dialog, "preview_limit_var") else "50"
        
        if not find_text:
            messagebox.showwarning("Cảnh báo", "Nhập text cần tìm!", parent=dialog)
            return
        
        # Build WHERE clause
        where = self._build_replace_where(find_text, target_col, mode, case_sensitive)
        
        try:
            cur = self.viewer_db.conn.cursor()
            # Đếm tổng
            cur.execute(f"SELECT COUNT(*) FROM translations WHERE {where}")
            total = cur.fetchone()[0]
            
            # ⚡ Xác định LIMIT
            if limit_str == "all" or limit_str == "":
                limit = total
                limit_display = "ALL"
            else:
                try:
                    limit = max(1, int(limit_str))
                    limit_display = str(limit)
                except ValueError:
                    limit = 50
                    limit_display = "50 (invalid input)"
            
            # ⚡ Warning nếu quá nhiều
            if limit > 500:
                if not messagebox.askyesno(
                    "Cảnh báo",
                    f"Bạn muốn hiển thị {limit} rows.\n"
                    "Nếu quá nhiều có thể mất vài giây và lag tool.\n\n"
                    "Tiếp tục?",
                    parent=dialog
                ):
                    return
            
            # Query
            query_limit = f" LIMIT {limit}" if limit < total else ""
            cur.execute(f"SELECT id, source_cn, target_en FROM translations WHERE {where}{query_limit}")
            rows = cur.fetchall()
            
            # Hiển thị preview
            dialog.preview_text.configure(state="normal")
            dialog.preview_text.delete("0.0", "end")
            
            preview = f"📊 Tổng cộng: {total:,} rows sẽ bị ảnh hưởng\n"
            preview += f"📋 Hiển thị: {len(rows):,} / {total:,} rows"
            if limit_display != "ALL" and limit < total:
                preview += f" (limit: {limit_display})"
            preview += f"\n"
            preview += f"🎨 Mode: {'FULL' if show_full else 'TRUNCATED (60 ký tự)'}\n"
            preview += "=" * 70 + "\n\n"
            
            if total == 0:
                preview += "❌ Không tìm thấy kết quả nào."
            else:
                for i, row in enumerate(rows, 1):
                    if show_full:
                        cn = row["source_cn"]
                        en = row["target_en"]
                    else:
                        cn = row["source_cn"][:60] + ("..." if len(row["source_cn"]) > 60 else "")
                        en = row["target_en"][:60] + ("..." if len(row["target_en"]) > 60 else "")
                    
                    preview += f"{'─' * 70}\n"
                    preview += f"{i}. ID {row['id']}\n"
                    preview += f"CN: {cn}\n"
                    preview += f"EN: {en}\n\n"
                
                if total > len(rows):
                    preview += f"{'─' * 70}\n"
                    preview += f"... và {total - len(rows):,} rows khác chưa hiển thị.\n"
                    preview += f"💡 Tăng giá trị 'Rows' ở trên để xem thêm.\n"
            
            dialog.preview_text.insert("0.0", preview)
            dialog.preview_text.configure(state="disabled")
            
            # Lưu vào dialog
            dialog.preview_total = total
            dialog.preview_where = where
            
        except Exception as e:
            dialog.preview_text.configure(state="normal")
            dialog.preview_text.delete("0.0", "end")
            dialog.preview_text.insert("0.0", f"[ERROR] {e}")
            dialog.preview_text.configure(state="disabled")
    
    def _replace_do_apply(self, dialog):
        """Apply replace."""
        find_text = dialog.find_entry.get()
        replace_text = dialog.replace_entry.get()
        target_col = dialog.target_col_var.get()
        mode = dialog.mode_var.get()
        case_sensitive = dialog.case_var.get()
        
        if not find_text:
            messagebox.showwarning("Cảnh báo", "Nhập text cần tìm!", parent=dialog)
            return
        
        if not hasattr(dialog, "preview_total") or not hasattr(dialog, "preview_where"):
            messagebox.showwarning("Cảnh báo", "Hãy nhấn 'Preview' trước để xem kết quả!", parent=dialog)
            return
        
        total = dialog.preview_total
        where = dialog.preview_where
        
        if total == 0:
            messagebox.showinfo("Thông báo", "Không có row nào để thay thế.", parent=dialog)
            return
        
        if not messagebox.askyesno(
            "Xác nhận Replace",
            f"Sẽ thay thế {total} rows.\n\n"
            f"Tìm: '{find_text}'\n"
            f"Thay bằng: '{replace_text}'\n"
            f"Trong cột: {target_col}\n"
            f"Chế độ: {mode}\n\n"
            f"⚠️ Thay đổi chỉ trong RAM. Nhấn 'Save Changes' sau để ghi vào file.\n\n"
            f"Tiếp tục?",
            parent=dialog
        ):
            return
        
        try:
            # Build SQL UPDATE với SQLite REPLACE function
            # REPLACE(column, find, replace)
            escaped_find = find_text.replace("'", "''")
            escaped_repl = replace_text.replace("'", "''")
            
            cur = self.viewer_db.conn.cursor()
            
            if target_col == "Target EN":
                cur.execute(
                    f"UPDATE translations SET target_en = REPLACE(target_en, ?, ?) WHERE {where}",
                    (find_text, replace_text)
                )
            elif target_col == "Source CN":
                cur.execute(
                    f"UPDATE translations SET source_cn = REPLACE(source_cn, ?, ?) WHERE {where}",
                    (find_text, replace_text)
                )
            else:  # Cả hai
                cur.execute(
                    f"UPDATE translations SET target_en = REPLACE(target_en, ?, ?), "
                    f"source_cn = REPLACE(source_cn, ?, ?) WHERE {where}",
                    (find_text, replace_text, find_text, replace_text)
                )
            
            affected = cur.rowcount
            self.viewer_db.conn.commit()
            
            # Log
            self._log(self.log_viewer, f"[OK] Replace All: đã thay thế {affected} rows")
            self._log(self.log_viewer, f"     '{find_text}' → '{replace_text}' trong {target_col}")
            self._log(self.log_viewer, f"     ⚠️ Nhấn 'Save Changes' để ghi vào file JSON")
            
            # Đóng dialog
            dialog.destroy()
            self.replace_dialog = None
            
            # Refresh bảng
            self._viewer_refresh_tables()
            
            # Thông báo
            messagebox.showinfo(
                "Hoàn tất",
                f"✅ Đã thay thế {affected} rows.\n\n"
                f"Nhấn '💾 Save Changes' để ghi vào file JSON.",
                parent=self
            )
        except Exception as e:
            self._log(self.log_viewer, f"[ERROR] Replace: {e}")
            messagebox.showerror("Lỗi", str(e), parent=dialog)
    
    def _build_replace_where(self, find_text, target_col, mode, case_sensitive):
        """Build WHERE clause cho replace."""
        escaped = find_text.replace("'", "''")
        
        # Xây dựng điều kiện cho từng cột
        def make_cond(col):
            if mode == "Exact match":
                if case_sensitive:
                    return f"{col} = '{escaped}'"
                else:
                    return f"LOWER({col}) = LOWER('{escaped}')"
            elif mode == "Contains (substring)":
                if case_sensitive:
                    return f"{col} LIKE '%{escaped}%'"
                else:
                    return f"LOWER({col}) LIKE LOWER('%{escaped}%')"
            else:  # Word boundary
                # SQLite không hỗ trợ regex native, dùng LIKE với space
                return f"({col} LIKE '{escaped} %' OR {col} LIKE '% {escaped}' OR {col} LIKE '% {escaped} %' OR {col} = '{escaped}' OR {col} LIKE '{escaped}%' OR {col} LIKE '%{escaped}')"
        
        if target_col == "Target EN":
            return make_cond("target_en")
        elif target_col == "Source CN":
            return make_cond("source_cn")
        else:
            return f"({make_cond('target_en')} OR {make_cond('source_cn')})"
    
    def _viewer_apply_filter(self):
        """Apply filter và refresh."""
        self._viewer_refresh_tables()
    
    def _viewer_clear_filter(self):
        """Clear filter."""
        self.viewer_filter_entry.delete(0, "end")
        self._viewer_refresh_tables()
    
    def _viewer_quick_filter(self, where):
        """Áp dụng quick filter."""
        self.viewer_filter_entry.delete(0, "end")
        if where:
            self.viewer_filter_entry.insert(0, where)
        self._viewer_refresh_tables()
    
    def _viewer_sort_by(self, column):
        """Sort theo column."""
        if self.viewer_sort_column == column:
            self.viewer_sort_order = "DESC" if self.viewer_sort_order == "ASC" else "ASC"
        else:
            self.viewer_sort_column = column
            self.viewer_sort_order = "ASC"
        self._viewer_refresh_tables()
    
    def _viewer_start_edit(self, event):
        """Bắt đầu inline edit khi double-click."""
        # Hủy edit cũ nếu có
        if self.viewer_edit_widget:
            try:
                self.viewer_edit_widget.destroy()
            except:
                pass
            self.viewer_edit_widget = None
        
        region = self.viewer_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        
        column = self.viewer_tree.identify_column(event.x)
        row_id = self.viewer_tree.identify_row(event.y)
        
        if not row_id:
            return
        
        # Cột: #1=id, #2=source_cn, #3=target_en, ...
        if column not in ("#2", "#3"):
            return
        
        col_name = "source_cn" if column == "#2" else "target_en"
        
        # Lấy giá trị hiện tại
        values = self.viewer_tree.item(row_id, "values")
        idx = 1 if col_name == "source_cn" else 2
        current_value = values[idx]
        
        # Lấy vị trí cell
        bbox = self.viewer_tree.bbox(row_id, column)
        if not bbox:
            return
        x, y, width, height = bbox
        
        # ⚡ Dùng tk.Entry native thay vì CTkEntry
        entry = tk.Entry(
            self.viewer_tree,
            font=("Consolas", 11),
            bg="#ff8c42",      # Màu cam đặc trưng
            fg="#000000",
            insertbackground="#000000",
            borderwidth=2,
            relief="solid",
            highlightthickness=0
        )
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, current_value)
        entry.select_range(0, "end")
        entry.focus_force()   # ⚡ force thay vì set
        entry.icursor("end")
        
        self.viewer_edit_widget = entry
        
        # Flag để tránh destroy kép
        committed = [False]
        
        def commit(e=None):
            if committed[0]:
                return
            committed[0] = True
            new_value = entry.get()
            try:
                self.viewer_db.update_row(row_id, col_name, new_value)
                new_values = list(values)
                # Truncate để hiển thị trong tree
                display_val = new_value[:80] + "..." if len(new_value) > 80 else new_value
                new_values[idx] = display_val
                self.viewer_tree.item(row_id, values=new_values)
                self._log(self.log_viewer, f"[OK] Đã sửa: {new_value[:50]}...")
            except Exception as ex:
                self._log(self.log_viewer, f"[ERROR] {ex}")
            finally:
                try:
                    entry.destroy()
                except:
                    pass
                self.viewer_edit_widget = None
        
        def cancel(e=None):
            if committed[0]:
                return
            committed[0] = True
            try:
                entry.destroy()
            except:
                pass
            self.viewer_edit_widget = None
        
        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", lambda e: self.after(100, commit))
    
    def _viewer_gloss_start_edit(self, event):
        """Inline edit cho glossary."""
        if self.viewer_edit_widget:
            try:
                self.viewer_edit_widget.destroy()
            except:
                pass
            self.viewer_edit_widget = None
        
        region = self.gloss_viewer_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        
        column = self.gloss_viewer_tree.identify_column(event.x)
        row_id = self.gloss_viewer_tree.identify_row(event.y)
        
        if not row_id:
            return
        
        col_map = {"#2": "source_cn", "#3": "target_en", "#4": "banned_translations", "#5": "category"}
        if column not in col_map:
            return
        
        col_name = col_map[column]
        values = self.gloss_viewer_tree.item(row_id, "values")
        idx_map = {"source_cn": 1, "target_en": 2, "banned_translations": 3, "category": 4}
        idx = idx_map[col_name]
        current_value = values[idx]
        
        bbox = self.gloss_viewer_tree.bbox(row_id, column)
        if not bbox:
            return
        x, y, width, height = bbox
        
        entry = tk.Entry(
            self.gloss_viewer_tree,
            font=("Consolas", 11),
            bg="#ff8c42", fg="#000000",
            insertbackground="#000000",
            borderwidth=2, relief="solid",
            highlightthickness=0
        )
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, current_value)
        entry.select_range(0, "end")
        entry.focus_force()
        entry.icursor("end")
        
        self.viewer_edit_widget = entry
        committed = [False]
        
        def commit(e=None):
            if committed[0]:
                return
            committed[0] = True
            new_value = entry.get()
            try:
                self.glossary_db.update_row(int(row_id), col_name, new_value)
                new_values = list(values)
                new_values[idx] = new_value
                self.gloss_viewer_tree.item(row_id, values=new_values)
                self._log(self.log_viewer, f"[OK] Đã sửa glossary: {col_name}")
            except Exception as ex:
                self._log(self.log_viewer, f"[ERROR] {ex}")
            finally:
                try:
                    entry.destroy()
                except:
                    pass
                self.viewer_edit_widget = None
        
        def cancel(e=None):
            if committed[0]:
                return
            committed[0] = True
            try:
                entry.destroy()
            except:
                pass
            self.viewer_edit_widget = None
        
        entry.bind("<Return>", commit)
        entry.bind("<KP_Enter>", commit)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", lambda e: self.after(100, commit))
    
    def _viewer_save(self):
        """Save tất cả thay đổi."""
        if not messagebox.askyesno(
            "Xác nhận",
            "Lưu TẤT CẢ thay đổi vào file JSON?\n\n"
            "⚠️ Sẽ ghi đè các file trong translations/"
        ):
            return
        
        if self.pipeline_running:
            return
        self.pipeline_running = True
        
        self._log(self.log_viewer, "")
        self._log(self.log_viewer, "[INFO] Đang lưu...")
        
        def worker():
            try:
                # Save translations
                count = self.viewer_db.save_to_files(self.log_queue_viewer)
                
                # Save glossary meta
                entries = self.glossary_db.to_entries_list()
                gl.save_glossary_meta("glossary_meta.json", entries, self.log_queue_viewer)
                gl.save_glossary_txt("glossary.txt", entries, self.log_queue_viewer)
                
                self.log_queue_viewer.put(f"[DONE] Đã lưu {count} files")
            except Exception as e:
                self.log_queue_viewer.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_viewer.put(traceback.format_exc())
            finally:
                self.log_queue_viewer.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_viewer_queue()
    
    def _viewer_export_csv(self):
        """Export CSV."""
        if self.viewer_current_subtab == "translations":
            path = filedialog.asksaveasfilename(
                title="Export translations ra CSV",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
                initialfile="translations_export.csv"
            )
            if not path:
                return
            where = self.viewer_filter_entry.get().strip()
            if self.viewer_db.export_csv(path, where, self.log_queue_viewer):
                self._drain_viewer_queue()
    
    def _viewer_gloss_apply_filter(self):
        """Apply filter cho glossary tab (kết hợp Search + SQL)."""
        # Build điều kiện search đơn giản
        search = self.gloss_search_entry.get().strip()
        sql = self.gloss_viewer_filter.get().strip()
        
        conditions = []
        
        if search:
            escaped = search.replace("'", "''")
            conditions.append(
                f"(source_cn LIKE '%{escaped}%' OR target_en LIKE '%{escaped}%' "
                f"OR banned_translations LIKE '%{escaped}%' OR category LIKE '%{escaped}%')"
            )
        
        if sql:
            conditions.append(f"({sql})")
        
        where = " AND ".join(conditions) if conditions else ""
        
        try:
            rows = self.glossary_db.query(where)
        except Exception as e:
            self._log(self.log_viewer, f"[ERROR] Glossary filter: {e}")
            return
        
        # Refresh tree
        for item in self.gloss_viewer_tree.get_children():
            self.gloss_viewer_tree.delete(item)
        
        for row in rows:
            self.gloss_viewer_tree.insert("", "end", iid=str(row["id"]), values=(
                row["id"], row["source_cn"], row["target_en"],
                row["banned_translations"], row["category"]
            ))
        
        self.gloss_viewer_count.configure(text=f"{len(rows):,} rows")

    def _viewer_gloss_search(self):
        """Search real-time trong Glossary (debounced)."""
        # Debounce: hủy timer cũ nếu có
        if hasattr(self, "_gloss_search_timer"):
            self.after_cancel(self._gloss_search_timer)
        
        # Đặt timer mới, 200ms
        self._gloss_search_timer = self.after(200, self._viewer_gloss_apply_filter)
    
    def _viewer_gloss_clear_filter(self):
        """Clear cả search và SQL filter."""
        self.gloss_search_entry.delete(0, "end")
        self.gloss_viewer_filter.delete(0, "end")
        self._viewer_gloss_apply_filter()
    
    def _poll_viewer_queue(self):
        """Poll queue cho viewer tab."""
        try:
            while True:
                line = self.log_queue_viewer.get_nowait()
                if line == "__DONE__":
                    self.pipeline_running = False
                    return
                self._log(self.log_viewer, line)
        except queue.Empty:
            pass
        self.after(100, self._poll_viewer_queue)
    
    def _drain_viewer_queue(self):
        try:
            while True:
                line = self.log_queue_viewer.get_nowait()
                if line != "__DONE__":
                    self._log(self.log_viewer, line)
        except queue.Empty:
            pass

    # ==================== EDIT PANEL HANDLERS ====================
    def _viewer_toggle_edit_panel(self):
        """Ẩn/hiện Edit Panel."""
        if self.viewer_edit_panel_visible.get():
            self.viewer_edit_panel.grid()
        else:
            self.viewer_edit_panel.grid_remove()
    
    def _viewer_on_row_select(self, event=None):
        """Khi user chọn 1 row → load vào Edit Panel (nếu panel đang mở)."""
        if not self.viewer_edit_panel_visible.get():
            return
        
        sel = self.viewer_tree.selection()
        if not sel:
            return
        
        hash_key = sel[0]
        self.viewer_edit_hash = hash_key
        
        # Query full data từ DB (không lấy từ tree vì có thể bị truncate)
        try:
            cur = self.viewer_db.conn.cursor()
            cur.execute("SELECT * FROM translations WHERE hash = ?", (hash_key,))
            row = cur.fetchone()
            if not row:
                return
            
            row = dict(row)
            
            # Load vào panel
            self.edit_panel_cn.delete("0.0", "end")
            self.edit_panel_cn.insert("0.0", row["source_cn"])
            
            self.edit_panel_en.delete("0.0", "end")
            self.edit_panel_en.insert("0.0", row["target_en"])
            
            # Update info
            self.viewer_edit_info.configure(
                text=f"Hash: {hash_key}\n"
                     f"File: {row['source_file']}  |  Freq: {row['frequency']}"
            )
        except Exception as e:
            self._log(self.log_viewer, f"[ERROR] {e}")
    
    def _edit_panel_save(self):
        """Lưu thay đổi từ Edit Panel vào DB."""
        if not self.viewer_edit_hash:
            messagebox.showwarning("Cảnh báo", "Chưa chọn entry nào!")
            return
        
        new_cn = self.edit_panel_cn.get("0.0", "end").strip()
        new_en = self.edit_panel_en.get("0.0", "end").strip()
        
        if not new_cn:
            messagebox.showerror("Lỗi", "Source (CN) không được để trống!")
            return
        
        try:
            # Update DB
            self.viewer_db.update_row(self.viewer_edit_hash, "source_cn", new_cn)
            self.viewer_db.update_row(self.viewer_edit_hash, "target_en", new_en)
            
            # Update tree display
            values = list(self.viewer_tree.item(self.viewer_edit_hash, "values"))
            values[1] = new_cn[:80] + "..." if len(new_cn) > 80 else new_cn
            values[2] = new_en[:80] + "..." if len(new_en) > 80 else new_en
            self.viewer_tree.item(self.viewer_edit_hash, values=values)
            
            self._log(self.log_viewer, f"[OK] Đã lưu entry: {new_en[:50]}...")
            
            # Flash save button
            self.edit_panel_save_btn.configure(text="✅ Saved!")
            self.after(1000, lambda: self.edit_panel_save_btn.configure(text="💾  Save"))
        except Exception as e:
            self._log(self.log_viewer, f"[ERROR] {e}")
            messagebox.showerror("Lỗi", str(e))
    
    def _edit_panel_reset(self):
        """Reset panel về giá trị hiện tại trong DB."""
        if self.viewer_edit_hash:
            self._viewer_on_row_select()

    # ==================== BACKUP HANDLERS ====================
    def _backup_refresh_info(self):
        """Refresh system info."""
        self._log(self.log_backup, "[INFO] Đang quét hệ thống...")
        
        def worker():
            try:
                info = bk.get_system_info(log_queue=self.log_queue_backup)
                self.log_queue_backup.put("__DONE__")
                self.after(0, lambda: self._update_info_display(info))
            except Exception as e:
                self.log_queue_backup.put(f"[ERROR] {e}")
                self.log_queue_backup.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_backup_queue()
    
    def _update_info_display(self, info):
        """Cập nhật textbox thông tin."""
        text = (
            f"📁 Translations Folder:\n"
            f"   • Files: {info['translations_files']}\n"
            f"   • Size: {info['translations_size_mb']:.2f} MB\n"
            f"   • Total entries: {info['total_translated']:,}\n"
            f"   • Still Chinese: {info['still_chinese']:,}\n\n"
            f"📖 Glossary:\n"
            f"   • Entries: {info['glossary_count']:,}\n\n"
            f"📦 Output:\n"
        )
        if info["output_exists"]:
            text += f"   • File exists ({info['output_size_mb']:.2f} MB)\n"
        else:
            text += f"   • Chưa có (cần chạy pipeline)\n"
        
        self.info_textbox.configure(state="normal")
        self.info_textbox.delete("0.0", "end")
        self.info_textbox.insert("0.0", text)
        self.info_textbox.configure(state="disabled")
    
    def _backup_create(self):
        """Tạo backup zip."""
        if self.pipeline_running:
            return
        self.pipeline_running = True
        
        self._log(self.log_backup, "")
        self._log(self.log_backup, "=" * 50)
        self._log(self.log_backup, "[INFO] Đang tạo backup...")
        self._log(self.log_backup, "=" * 50)
        
        def worker():
            try:
                bk.create_backup(log_queue=self.log_queue_backup)
            except Exception as e:
                self.log_queue_backup.put(f"[ERROR] {e}")
            finally:
                self.log_queue_backup.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_backup_queue()
    
    def _backup_restore(self):
        """Restore từ zip."""
        path = filedialog.askopenfilename(
            title="Chọn file backup",
            filetypes=[("Zip", "*.zip")],
            initialdir="backups"
        )
        if not path:
            return
        
        if not messagebox.askyesno(
            "Xác nhận",
            f"Restore từ:\n{path}\n\n"
            "⚠️ Sẽ GHI ĐÈ các file translations/glossary hiện tại.\n"
            "Bạn có chắc chắn?"
        ):
            return
        
        if self.pipeline_running:
            return
        self.pipeline_running = True
        
        self._log(self.log_backup, "")
        self._log(self.log_backup, "=" * 50)
        self._log(self.log_backup, f"[INFO] Restore từ: {path}")
        self._log(self.log_backup, "=" * 50)
        
        def worker():
            try:
                bk.restore_backup(path, log_queue=self.log_queue_backup)
            except Exception as e:
                self.log_queue_backup.put(f"[ERROR] {e}")
            finally:
                self.log_queue_backup.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_backup_queue()
    
    def _backup_list(self):
        """Hiển thị danh sách backup."""
        backups = bk.list_backups()
        
        if not backups:
            self._log(self.log_backup, "[INFO] Không có backup nào.")
            return
        
        self._log(self.log_backup, "")
        self._log(self.log_backup, "=" * 50)
        self._log(self.log_backup, f"[INFO] {len(backups)} backup(s):")
        self._log(self.log_backup, "=" * 50)
        for b in backups:
            self._log(self.log_backup, f"  • {b['name']}  ({b['size_mb']:.2f} MB, {b['modified']})")
    
    def _backup_export_all(self):
        """Export tất cả translations ra 1 file JSON."""
        path = filedialog.asksaveasfilename(
            title="Lưu file export",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="translations_merged.json"
        )
        if not path:
            return
        
        if self.pipeline_running:
            return
        self.pipeline_running = True
        
        self._log(self.log_backup, "")
        self._log(self.log_backup, "=" * 50)
        self._log(self.log_backup, "[INFO] Đang gộp translations...")
        self._log(self.log_backup, "=" * 50)
        
        def worker():
            try:
                bk.export_all_translations(path, log_queue=self.log_queue_backup)
            except Exception as e:
                self.log_queue_backup.put(f"[ERROR] {e}")
            finally:
                self.log_queue_backup.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_backup_queue()
    
    def _backup_clear_temp(self):
        """Xóa file tạm."""
        if not messagebox.askyesno(
            "Xác nhận",
            "Xóa các file tạm sau?\n\n"
            "• translation_progress.json\n"
            "• glossary_violations.json\n"
            "• corrections_log.json\n"
            "• suspicious_translations.json"
        ):
            return
        
        self._log(self.log_backup, "")
        self._log(self.log_backup, "[INFO] Đang xóa file tạm...")
        bk.clear_temp_files(log_queue=self.log_queue_backup)
        self._drain_backup_queue()
    
    def _open_folder(self, path):
        """Mở folder trong Explorer."""
        p = Path(path)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
        os.startfile(p.resolve())
    
    def _poll_backup_queue(self):
        """Poll queue cho backup tab."""
        try:
            while True:
                line = self.log_queue_backup.get_nowait()
                if line == "__DONE__":
                    self.pipeline_running = False
                    return
                self._log(self.log_backup, line)
        except queue.Empty:
            pass
        self.after(100, self._poll_backup_queue)
    
    def _drain_backup_queue(self):
        """Xả queue ngay (cho thao tác sync)."""
        try:
            while True:
                line = self.log_queue_backup.get_nowait()
                if line != "__DONE__":
                    self._log(self.log_backup, line)
        except queue.Empty:
            pass

    # ==================== GLOSSARY HANDLERS ====================
    def _load_glossary(self):
        """Load glossary từ 2 file: txt + meta json."""
        self.glossary_path = "glossary.txt"
        self.glossary_meta_path = "glossary_meta.json"
        
        # Load metadata (có banned, type)
        meta_entries = gl.load_glossary_meta(self.glossary_meta_path)
        
        if meta_entries:
            self.glossary_entries = meta_entries
            self._log(self.log_glossary, f"[OK] Đã tải {len(self.glossary_entries):,} entries từ {self.glossary_meta_path}")
        elif os.path.exists(self.glossary_path):
            # Fallback: đọc txt cũ, không có metadata
            self.glossary_entries = gl.load_glossary_txt(self.glossary_path)
            self._log(self.log_glossary, f"[OK] Đã tải {len(self.glossary_entries):,} entries từ {self.glossary_path}")
            self._log(self.log_glossary, f"[WARN] Không có metadata (banned/type)")
        else:
            self.glossary_entries = []
            self._log(self.log_glossary, f"[WARN] Chưa có file glossary nào")
        
        self._refresh_glossary_table()
    
    def _refresh_glossary_table(self):
        """Refresh bảng dựa trên search filter."""
        # Clear
        for item in self.glossary_tree.get_children():
            self.glossary_tree.delete(item)
        
        query = self.glossary_search.get().strip().lower()
        
        filtered = []
        for e in self.glossary_entries:
            if query:
                if query not in e["cn"].lower() and query not in e["en"].lower():
                    continue
            filtered.append(e)
        
        # Insert
        for i, e in enumerate(filtered):
            self.glossary_tree.insert("", "end", iid=str(i), values=(
                e["cn"], e["en"], e["type"], e.get("banned", "")
            ))
        
        # Store filtered reference
        self._glossary_filtered = filtered
        self.glossary_count_label.configure(
            text=f"{len(filtered):,} / {len(self.glossary_entries):,} entries"
        )
    
    def _get_selected_glossary_index(self):
        """Lấy index của term đang chọn."""
        sel = self.glossary_tree.selection()
        if not sel:
            return None
        return int(sel[0])
    
    def _glossary_add_term(self):
        """Mở dialog thêm term."""
        self._glossary_edit_dialog(None)
    
    def _glossary_edit_term(self):
        """Mở dialog sửa term đang chọn."""
        idx = self._get_selected_glossary_index()
        if idx is None:
            messagebox.showinfo("Thông báo", "Vui lòng chọn một thuật ngữ!")
            return
        entry = self._glossary_filtered[idx]
        self._glossary_edit_dialog(entry)
    
    def _glossary_delete_term(self):
        """Xóa term đang chọn."""
        idx = self._get_selected_glossary_index()
        if idx is None:
            return
        
        entry = self._glossary_filtered[idx]
        if not messagebox.askyesno("Xác nhận", f"Xóa '{entry['cn']} -> {entry['en']}'?"):
            return
        
        # Tìm trong list gốc và xóa
        for i, e in enumerate(self.glossary_entries):
            if e["cn"] == entry["cn"]:
                del self.glossary_entries[i]
                break
        
        self._log(self.log_glossary, f"[OK] Đã xóa: {entry['cn']}")
        self._refresh_glossary_table()
    
    def _glossary_edit_dialog(self, entry):
        """Dialog thêm/sửa term."""
        is_new = entry is None
        
        dialog = ctk.CTkToplevel(self)
        dialog.title("Thêm thuật ngữ" if is_new else "Sửa thuật ngữ")
        dialog.geometry("500x400")
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()
        
        ctk.CTkLabel(
            dialog, text="🇨🇳  Chinese:", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        ).pack(anchor="w", padx=20, pady=(20, 5))
        
        cn_entry = ctk.CTkEntry(
            dialog, fg_color=COLOR_CARD, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=36
        )
        cn_entry.pack(fill="x", padx=20, pady=(0, 15))
        if not is_new:
            cn_entry.insert(0, entry["cn"])
        
        ctk.CTkLabel(
            dialog, text="🇬🇧  English:", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_TEXT
        ).pack(anchor="w", padx=20, pady=(0, 5))
        
        en_entry = ctk.CTkEntry(
            dialog, fg_color=COLOR_CARD, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=36
        )
        en_entry.pack(fill="x", padx=20, pady=(0, 15))
        if not is_new:
            en_entry.insert(0, entry["en"])
        
        ctk.CTkLabel(
            dialog, text="📂  Type (vd: Character, Location, Organization):",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).pack(anchor="w", padx=20, pady=(0, 5))
        
        type_entry = ctk.CTkEntry(
            dialog, fg_color=COLOR_CARD, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=36
        )
        type_entry.pack(fill="x", padx=20, pady=(0, 15))
        if not is_new:
            type_entry.insert(0, entry.get("type", ""))
        
        ctk.CTkLabel(
            dialog, text="🚫  Banned translations (cách nhau dấu phẩy):",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT
        ).pack(anchor="w", padx=20, pady=(0, 5))
        
        banned_entry = ctk.CTkEntry(
            dialog, fg_color=COLOR_CARD, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, height=36,
            placeholder_text="vd: Awakened Mermaid, Sleeping Mermaid"
        )
        banned_entry.pack(fill="x", padx=20, pady=(0, 20))
        if not is_new:
            banned_entry.insert(0, entry.get("banned", ""))
        
        # Buttons
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        
        def save():
            cn = cn_entry.get().strip()
            en = en_entry.get().strip()
            t = type_entry.get().strip()
            banned = banned_entry.get().strip()
            
            if not cn or not en:
                messagebox.showerror("Lỗi", "CN và EN không được để trống!")
                return
            
            if is_new:
                # Check trùng
                for e in self.glossary_entries:
                    if e["cn"] == cn:
                        messagebox.showerror("Lỗi", f"Thuật ngữ '{cn}' đã tồn tại!")
                        return
                self.glossary_entries.append({
                    "cn": cn, "en": en, "type": t, "banned": banned, "context": "Any"
                })
                self._log(self.log_glossary, f"[OK] Đã thêm: {cn} -> {en}")
            else:
                entry["cn"] = cn
                entry["en"] = en
                entry["type"] = t
                entry["banned"] = banned
                self._log(self.log_glossary, f"[OK] Đã sửa: {cn} -> {en}")
            
            self._refresh_glossary_table()
            dialog.destroy()
        
        ctk.CTkButton(
            btn_frame, text="Cancel", height=36,
            fg_color=COLOR_CARD, hover_color=COLOR_BORDER,
            border_width=1, border_color=COLOR_BORDER, text_color=COLOR_TEXT,
            command=dialog.destroy
        ).pack(side="right", padx=(5, 0))
        
        ctk.CTkButton(
            btn_frame, text="💾  Save", height=36,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER,
            text_color="#000000", font=ctk.CTkFont(weight="bold"),
            command=save
        ).pack(side="right")
    
    def _glossary_show_menu(self, event):
        """Context menu khi right-click."""
        try:
            self.glossary_tree.selection_set(self.glossary_tree.identify_row(event.y))
        except:
            pass
    
    def _glossary_save(self):
        """Lưu CẢ 2 file: txt + meta json."""
        try:
            # 1. Lưu txt (CN -> EN cho AI)
            gl.save_glossary_txt(self.glossary_path, self.glossary_entries, self.log_queue_glossary)
            
            # 2. Lưu meta json (đầy đủ cho UI)
            gl.save_glossary_meta(self.glossary_meta_path, self.glossary_entries, self.log_queue_glossary)
            
            self._drain_glossary_queue()
        except Exception as e:
            self._log(self.log_glossary, f"[ERROR] {e}")

    def _glossary_audit(self):
        """Quét file translations để tìm vi phạm glossary."""
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Vui lòng đợi!")
            return
        
        has_banned = any(e.get("banned", "") for e in self.glossary_entries)
        if not has_banned:
            messagebox.showinfo(
                "Thông báo",
                "Chưa có thuật ngữ nào được cấu hình 'Banned translations'.\n"
                "Hãy thêm banned translations để quét vi phạm."
            )
            return
        
        # ⚡ Chọn file translations cần quét
        path = filedialog.askopenfilename(
            title="Bước 1/2: Chọn file translations (base.json)",
            filetypes=[("JSON", "*.json")],
            initialdir="translations"
        )
        if not path:
            return
        
        # ⚡ Tự động tìm CN source trong cùng thư mục
        cn_source_path = None
        parent_dir = os.path.dirname(path)
        candidates = [
            os.path.join(parent_dir, "cn_source.json"),
            os.path.join(parent_dir, "cn.json"),
            "cn_source.json",
            "cn.json",
        ]
        for c in candidates:
            if os.path.exists(c):
                cn_source_path = c
                break
        
        # Nếu không tìm thấy tự động → hỏi user
        if not cn_source_path:
            if messagebox.askyesno(
                "Không tìm thấy CN source",
                "Không tìm thấy file CN source (cn_source.json) trong thư mục.\n\n"
                "• Yes: Chọn thủ công file CN source\n"
                "• No: Bỏ qua (chỉ check banned, có thể báo sai)\n\n"
                "Bạn có muốn chọn file CN source không?"
            ):
                cn_source_path = filedialog.askopenfilename(
                    title="Bước 2/2: Chọn file CN source gốc",
                    filetypes=[("JSON", "*.json")],
                    initialdir=parent_dir
                )
                if not cn_source_path:
                    cn_source_path = None
        
        self.pipeline_running = True
        self._log(self.log_glossary, "")
        self._log(self.log_glossary, "=" * 50)
        self._log(self.log_glossary, "[INFO] Bắt đầu quét vi phạm glossary...")
        self._log(self.log_glossary, "=" * 50)
        
        def worker():
            try:
                # Load translations
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                texts = data.get("texts", {})
                self.log_queue_glossary.put(f"[INFO] File translations: {len(texts):,} câu")
                
                # Load CN source nếu có
                cn_source = None
                if cn_source_path and os.path.exists(cn_source_path):
                    try:
                        with open(cn_source_path, 'r', encoding='utf-8') as f:
                            cn_data = json.load(f)
                        cn_source = cn_data.get("texts", {})
                        self.log_queue_glossary.put(
                            f"[INFO] File CN source: {len(cn_source):,} câu "
                            f"({os.path.basename(cn_source_path)})"
                        )
                    except Exception as e:
                        self.log_queue_glossary.put(f"[WARN] Không load được CN source: {e}")
                else:
                    self.log_queue_glossary.put(
                        "[WARN] Không có CN source → chỉ check banned (có thể false positive)"
                    )
                
                self.log_queue_glossary.put("")
                
                # Chạy audit
                violations = gl.audit_translations(
                    self.glossary_entries,
                    texts,
                    cn_source=cn_source,
                    log_queue=self.log_queue_glossary
                )
                
                self.log_queue_glossary.put("")
                self.log_queue_glossary.put("=" * 50)
                self.log_queue_glossary.put(f"[DONE] Tìm thấy {len(violations)} vi phạm")
                self.log_queue_glossary.put("=" * 50)
                
                if violations:
                    # Lưu kết quả
                    out_file = "glossary_violations.json"
                    with open(out_file, 'w', encoding='utf-8', newline='\n') as f:
                        json.dump({
                            "total": len(violations),
                            "has_cn_source": cn_source is not None,
                            "violations": violations
                        }, f, ensure_ascii=False, indent=2)
                    
                    self.log_queue_glossary.put(f"[OK] Đã lưu: {out_file}")
                    self.log_queue_glossary.put("")
                    self.log_queue_glossary.put("[INFO] 5 vi phạm đầu tiên:")
                    
                    for v in violations[:5]:
                        self.log_queue_glossary.put(
                            f"\n  • Term: {v['cn_term']} → expected '{v['expected']}'"
                        )
                        self.log_queue_glossary.put(
                            f"    Found: '{v['found']}'"
                        )
                        if v.get('cn_text'):
                            cn_preview = v['cn_text'][:70] + ("..." if len(v['cn_text']) > 70 else "")
                            self.log_queue_glossary.put(f"    CN: {cn_preview}")
                        en_preview = v['en_text'][:70] + ("..." if len(v['en_text']) > 70 else "")
                        self.log_queue_glossary.put(f"    EN: {en_preview}")
                else:
                    self.log_queue_glossary.put("[OK] ✅ Không tìm thấy vi phạm nào!")
            except Exception as e:
                self.log_queue_glossary.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_glossary.put(traceback.format_exc())
            finally:
                self.log_queue_glossary.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_glossary_queue()
    
    def _glossary_import(self):
        """Import từ JSON."""
        path = filedialog.askopenfilename(
            title="Chọn file glossary JSON",
            filetypes=[("JSON", "*.json")]
        )
        if not path:
            return
        
        try:
            new_entries = gl.import_glossary_json(path, self.log_queue_glossary)
            if new_entries:
                if messagebox.askyesno(
                    "Chế độ import",
                    f"Đã tải {len(new_entries)} entries.\n\n"
                    "Yes = Gộp vào danh sách hiện tại\n"
                    "No = Thay thế toàn bộ"
                ):
                    self.glossary_entries = gl.merge_glossaries(self.glossary_entries, new_entries)
                    self._log(self.log_glossary, f"[OK] Đã gộp, tổng: {len(self.glossary_entries)}")
                else:
                    self.glossary_entries = new_entries
                    self._log(self.log_glossary, f"[OK] Đã thay thế: {len(new_entries)}")
                
                self._refresh_glossary_table()
            self._drain_glossary_queue()
        except Exception as e:
            self._log(self.log_glossary, f"[ERROR] {e}")
    
    def _glossary_export(self):
        """Export ra JSON."""
        path = filedialog.asksaveasfilename(
            title="Lưu glossary JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="glossary_export.json"
        )
        if not path:
            return
        
        try:
            gl.export_glossary_json(path, self.glossary_entries, self.log_queue_glossary)
            self._drain_glossary_queue()
        except Exception as e:
            self._log(self.log_glossary, f"[ERROR] {e}")
    
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
    
    def _poll_glossary_queue(self):
        """Poll queue cho glossary tab."""
        try:
            while True:
                line = self.log_queue_glossary.get_nowait()
                if line == "__DONE__":
                    self.pipeline_running = False
                    return
                self._log(self.log_glossary, line)
        except queue.Empty:
            pass
        self.after(100, self._poll_glossary_queue)
    
    def _drain_glossary_queue(self):
        """Xả queue ngay lập tức (cho các thao tác nhanh)."""
        try:
            while True:
                line = self.log_queue_glossary.get_nowait()
                if line == "__DONE__":
                    continue
                self._log(self.log_glossary, line)
        except queue.Empty:
            pass
    
    # ==================== ACTION HANDLERS ====================
    def _run_update_pipeline(self):
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Pipeline đang chạy, vui lòng đợi!")
            return
        
        # Validate inputs
        input_path = self.entry_patch_input.get().strip()
        output_path = self.entry_patch_output.get().strip()
        
        if not input_path or not Path(input_path).exists():
            messagebox.showerror("Lỗi", "Vui lòng chọn file .bytes hợp lệ!")
            return
        
        if not output_path:
            messagebox.showerror("Lỗi", "Vui lòng chọn nơi lưu file output!")
            return
        
        translations_dir = Path("translations")
        if not translations_dir.exists():
            if not messagebox.askyesno(
                "Cảnh báo",
                "Thư mục 'translations' chưa tồn tại.\n"
                "Bạn có muốn tiếp tục không? (Sẽ chỉ export, không có bản dịch cũ)"
            ):
                return
            translations_dir.mkdir(exist_ok=True)
        
        # Chuẩn bị UI
        self.pipeline_running = True
        self.btn_run_pipeline.configure(state="disabled", text="⏳  Processing...")
        self.log_patch.configure(state="normal")
        self.log_patch.delete("0.0", "end")
        self.log_patch.configure(state="disabled")
        
        # Chạy trong thread
        thread = threading.Thread(
            target=self._pipeline_worker,
            args=(Path(input_path), translations_dir, Path(output_path)),
            daemon=True
        )
        thread.start()
        
        # Bắt đầu poll log queue
        self._poll_log_queue("patch")


    def _pipeline_worker(self, source: Path, translations_dir: Path, output: Path):
        """Chạy pipeline trong background thread."""
        pipeline_ok = False
        try:
            for line in run_update_pipeline(source, translations_dir, output):
                self.log_queue_patch.put(line)
            pipeline_ok = True
        except TableError as e:
            self.log_queue_patch.put(f"[ERROR] {e}")
        except Exception as e:
            self.log_queue_patch.put(f"[ERROR] Lỗi không mong đợi: {e}")
            import traceback
            self.log_queue_patch.put(traceback.format_exc())
        finally:
            # ⚡ AUTO-UPLOAD sau khi pipeline thành công
            if pipeline_ok and output.exists():
                config = uploader.load_config()
                if config.get("auto_upload_after_patch"):
                    self.log_queue_patch.put("")
                    self.log_queue_patch.put("=" * 60)
                    self.log_queue_patch.put("[AUTO-UPLOAD] Bắt đầu upload file output...")
                    self.log_queue_patch.put("=" * 60)
                    
                    try:
                        uploader.auto_upload_after_patch(str(output), self.log_queue_patch)
                    except Exception as e:
                        self.log_queue_patch.put(f"[AUTO-UPLOAD ERROR] {e}")
                        import traceback
                        self.log_queue_patch.put(traceback.format_exc())
            
            self.log_queue_patch.put("__DONE__")


    def _poll_log_queue(self, target_tab: str):
        """Đọc log từ queue và cập nhật UI."""
        if target_tab == "patch":
            log_widget = self.log_patch
            queue_obj = self.log_queue_patch
            done_callback = lambda: (
                self.btn_run_pipeline.configure(
                    state="normal",
                    text="🚀  RUN FULL UPDATE PIPELINE"
                ),
                setattr(self, "pipeline_running", False),
                self._update_sidebar_info(),
            )
        else:  # setup
            log_widget = self.log_setup
            queue_obj = self.log_queue_setup
            done_callback = lambda: (
                self.btn_run_setup.configure(
                    state="normal",
                    text="⚡  BUILD TRANSLATION DATABASE"
                ),
                setattr(self, "pipeline_running", False),
                self._update_sidebar_info(),
            )
        
        try:
            while True:
                line = queue_obj.get_nowait()
                if line == "__DONE__":
                    done_callback()
                    return
                self._log(log_widget, line)
        except queue.Empty:
            pass
        
        self.after(100, lambda: self._poll_log_queue(target_tab))
    
    def _run_setup(self):
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Vui lòng đợi thao tác hiện tại hoàn tất!")
            return
        
        mode = self.setup_mode.get()
        cn_path = self.entry_setup_cn.get().strip()
        en_path = self.entry_setup_en.get().strip()
        
        # Validate
        if not cn_path or not Path(cn_path).exists():
            messagebox.showerror("Lỗi", "Vui lòng chọn file .bytes gốc tiếng Trung!")
            return
        if not en_path or not Path(en_path).exists():
            label = "base.json" if mode == "import" else "translations.json cũ"
            messagebox.showerror("Lỗi", f"Vui lòng chọn file {label}!")
            return
        
        translations_dir = Path("translations")
        base_file = translations_dir / "base.json"
        
        if base_file.exists():
            if not messagebox.askyesno(
                "Cảnh báo",
                f"File '{base_file}' đã tồn tại.\n"
                f"Bạn có muốn GHI ĐÈ không?\n\n"
                f"(Nên sao lưu trước khi ghi đè!)"
            ):
                return
        
        # Chuẩn bị UI
        self.pipeline_running = True
        self.btn_run_setup.configure(state="disabled", text="⏳  Processing...")
        self.log_setup.configure(state="normal")
        self.log_setup.delete("0.0", "end")
        self.log_setup.configure(state="disabled")
        
        # Chạy thread theo mode
        if mode == "import":
            thread = threading.Thread(
                target=self._import_base_worker,
                args=(Path(cn_path), Path(en_path), translations_dir),
                daemon=True
            )
        else:  # convert
            thread = threading.Thread(
                target=self._setup_worker,
                args=(Path(cn_path), Path(en_path), translations_dir),
                daemon=True
            )
        thread.start()
        
        self._poll_log_queue("setup")


    def _import_base_worker(self, cn_bytes: Path, base_json: Path, translations_dir: Path):
        """Import base.json có sẵn (đã ở hash format)."""
        try:
            import json
            import shutil
            
            self.log_queue_setup.put(f"[INFO] Mode: IMPORT BASE TRANSLATION")
            self.log_queue_setup.put(f"[INFO] File .bytes: {cn_bytes.name}")
            self.log_queue_setup.put(f"[INFO] File base:  {base_json.name}")
            
            # Validate format
            self.log_queue_setup.put("[INFO] Đang kiểm tra định dạng file JSON...")
            with open(base_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if data.get("format") != "gfl2-langpackage-by-text-1":
                raise ValueError(
                    f"File không phải định dạng 'gfl2-langpackage-by-text-1'.\n"
                    f"Format hiện tại: {data.get('format', '(không có)')}"
                )
            
            texts = data.get("texts", {})
            self.log_queue_setup.put(f"[OK] ✅ Đã xác nhận format mới ({len(texts):,} câu)")
            
            # Copy vào translations/
            translations_dir.mkdir(parents=True, exist_ok=True)
            dest = translations_dir / "base.json"
            
            self.log_queue_setup.put(f"[INFO] Đang copy vào {dest}...")
            shutil.copy2(base_json, dest)
            
            self.log_queue_setup.put("")
            self.log_queue_setup.put("=" * 60)
            self.log_queue_setup.put("[DONE] IMPORT THÀNH CÔNG!")
            self.log_queue_setup.put("=" * 60)
            self.log_queue_setup.put(f"[OK] Đã import {len(texts):,} câu")
            self.log_queue_setup.put(f"[OK] Vị trí: {dest.resolve()}")
            self.log_queue_setup.put(f"[INFO] Bạn có thể chạy 'Patch Updater' ngay.")
        
        except Exception as e:
            self.log_queue_setup.put(f"[ERROR] {e}")
            import traceback
            self.log_queue_setup.put(traceback.format_exc())
        finally:
            self.log_queue_setup.put("__DONE__")


    def _setup_worker(self, cn_bytes: Path, en_json: Path, translations_dir: Path):
        """Chạy setup trong background thread."""
        try:
            for line in run_first_time_setup(cn_bytes, en_json, translations_dir):
                self.log_queue_setup.put(line)
        except TableError as e:
            self.log_queue_setup.put(f"[ERROR] {e}")
        except Exception as e:
            self.log_queue_setup.put(f"[ERROR] {e}")
            import traceback
            self.log_queue_setup.put(traceback.format_exc())
        finally:
            self.log_queue_setup.put("__DONE__")
    
    def _get_translate_config(self):
        """Lấy config từ UI."""
        return {
            "input": self.entry_trans_input.get().strip(),
            "output": self.entry_trans_output.get().strip(),
            "style": self.entry_trans_style.get().strip(),
            "glossary": self.entry_trans_glossary.get().strip(),
            "api_key": self.entry_api_key.get().strip(),
            "model": self.entry_model.get().strip() or "deepseek-chat",
            "batch_size": int(self.entry_batch_size.get() or "30"),
            "concurrent": int(self.entry_concurrent.get() or "5"),
            "style_max": int(self.entry_style_max.get() or "4000"),
            "glossary_max": int(self.entry_glossary_max.get() or "15000"),
            "max_retries": int(self.entry_max_retries.get() or "3"),
        }
    
    def _prepare_translate_ui(self, button, button_text):
        """Chuẩn bị UI trước khi chạy."""
        button.configure(state="disabled", text="⏳\nProcessing...")
        self.log_translate.configure(state="normal")
        self.log_translate.delete("0.0", "end")
        self.log_translate.configure(state="disabled")
    
    def _run_auto_translate(self):
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Vui lòng đợi!")
            return
        
        # Lấy config
        api_key = self.entry_api_key.get().strip()
        input_f = self.entry_trans_input.get().strip()
        output_f = self.entry_trans_output.get().strip()
        
        if not api_key:
            messagebox.showerror("Lỗi", "Vui lòng nhập DeepSeek API Key!")
            return
        if not input_f or not Path(input_f).exists():
            messagebox.showerror("Lỗi", "Chọn file input hợp lệ!")
            return
        if not output_f:
            messagebox.showerror("Lỗi", "Chọn file output!")
            return
        
        self.pipeline_running = True
        self.btn_auto_translate.configure(state="disabled", text="⏳  Processing...")
        self.log_translate.configure(state="normal")
        self.log_translate.delete("0.0", "end")
        self.log_translate.configure(state="disabled")
        
        config = {
            "input": input_f, "output": output_f,
            "progress": "translation_progress.json",
            "style": self.entry_trans_style.get().strip(),
            "glossary": self.entry_trans_glossary.get().strip(),
            "api_key": api_key,
            "model": self.entry_model.get().strip() or "deepseek-chat",
            "style_max": int(self.entry_style_max.get() or "4000"),
            "glossary_max": int(self.entry_glossary_max.get() or "15000"),
            "batch_size": int(self.entry_batch_size.get() or "30"),
            "concurrent": int(self.entry_concurrent.get() or "5"),
            "max_retries": int(self.entry_max_retries.get() or "3"),
        }
        
        def worker():
            try:
                auto_translate.run_auto_translate(
                    config["input"], config["output"], config["progress"],
                    config["style"], config["glossary"],
                    config["api_key"], config["model"],
                    config["style_max"], config["glossary_max"],
                    config["batch_size"], config["concurrent"], config["max_retries"],
                    self.log_queue_translate
                )
            except Exception as e:
                self.log_queue_translate.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_translate.put(traceback.format_exc())
            finally:
                self.log_queue_translate.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_queue(self.log_queue_translate, self.log_translate,
                         self.btn_auto_translate, "🚀  START AUTO TRANSLATE")
    
    def _run_export_cn(self):
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Vui lòng đợi!")
            return
        
        input_bytes = self.entry_export_bytes.get().strip()
        output_json = self.entry_export_output.get().strip()
        
        if not input_bytes or not Path(input_bytes).exists():
            messagebox.showerror("Lỗi", "Chọn file .bytes hợp lệ!")
            return
        if not output_json:
            messagebox.showerror("Lỗi", "Chọn nơi lưu file JSON!")
            return
        
        self.pipeline_running = True
        self.btn_export_cn.configure(state="disabled", text="⏳  Processing...")
        self.log_find.configure(state="normal")
        self.log_find.delete("0.0", "end")
        self.log_find.configure(state="disabled")
        
        def worker():
            try:
                from core.langpackage_export import TableError as TE
                for line in run_export_cn_source(Path(input_bytes), Path(output_json)):
                    self.log_queue_find.put(line)
            except Exception as e:
                self.log_queue_find.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_find.put(traceback.format_exc())
            finally:
                self.log_queue_find.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_queue(self.log_queue_find, self.log_find,
                         self.btn_export_cn, "📤  EXPORT CN SOURCE")
    
    def _run_find_errors(self):
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Vui lòng đợi!")
            return
        
        source = self.entry_find_source.get().strip()
        translated = self.entry_find_translated.get().strip()
        output = self.entry_find_output.get().strip()
        
        if not source or not Path(source).exists():
            messagebox.showerror("Lỗi", "Chọn file Source (CN gốc)!")
            return
        if not translated or not Path(translated).exists():
            messagebox.showerror("Lỗi", "Chọn file Translated (EN)!\nNếu là base.json: chỉ đường dẫn translations/base.json")
            return
        if not output:
            messagebox.showerror("Lỗi", "Chọn nơi lưu file output!")
            return
        
        self.pipeline_running = True
        self.btn_find_errors.configure(state="disabled", text="⏳  Processing...")
        self.log_find.configure(state="normal")
        self.log_find.delete("0.0", "end")
        self.log_find.configure(state="disabled")
        
        def worker():
            try:
                find_errors.run_find_errors(source, translated, output, self.log_queue_find)
            except Exception as e:
                self.log_queue_find.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_find.put(traceback.format_exc())
            finally:
                self.log_queue_find.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_queue(self.log_queue_find, self.log_find,
                         self.btn_find_errors, "🔍  FIND ERRORS")
    
    def _run_apply_fixes(self):
        if self.pipeline_running:
            messagebox.showwarning("Đang chạy", "Vui lòng đợi!")
            return
        
        corrections = self.entry_apply_corrections.get().strip()
        translated = self.entry_apply_translated.get().strip()
        auto_backup = self.var_auto_backup.get()
        
        if not corrections or not Path(corrections).exists():
            messagebox.showerror("Lỗi", "Chọn file corrections (suspicious.json)!")
            return
        if not translated or not Path(translated).exists():
            messagebox.showerror("Lỗi", "Chọn file translated cần sửa!")
            return
        
        self.pipeline_running = True
        self.btn_apply_fixes.configure(state="disabled", text="⏳  Processing...")
        self.log_apply.configure(state="normal")
        self.log_apply.delete("0.0", "end")
        self.log_apply.configure(state="disabled")
        
        def worker():
            try:
                apply_fixes.run_apply_fixes(corrections, translated, auto_backup, self.log_queue_apply)
            except Exception as e:
                self.log_queue_apply.put(f"[ERROR] {e}")
                import traceback
                self.log_queue_apply.put(traceback.format_exc())
            finally:
                self.log_queue_apply.put("__DONE__")
        
        threading.Thread(target=worker, daemon=True).start()
        self._poll_queue(self.log_queue_apply, self.log_apply,
                         self.btn_apply_fixes, "🔧  APPLY FIXES")
    
    def _poll_queue(self, queue_obj, log_widget, button, original_text):
        """Hàm poll queue chung cho mọi tab."""
        try:
            while True:
                line = queue_obj.get_nowait()
                if line == "__DONE__":
                    button.configure(state="normal", text=original_text)
                    self.pipeline_running = False
                    return
                self._log(log_widget, line)
        except queue.Empty:
            pass
        self.after(100, lambda: self._poll_queue(queue_obj, log_widget, button, original_text))
    
    def _poll_translate_queue(self, button, original_text):
        """Poll queue cho tab Translation."""
        try:
            while True:
                line = self.log_queue_translate.get_nowait()
                if line == "__DONE__":
                    button.configure(state="normal", text=original_text)
                    self.pipeline_running = False
                    return
                self._log(self.log_translate, line)
        except queue.Empty:
            pass
        self.after(100, lambda: self._poll_translate_queue(button, original_text))


# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    app = GFL2TranslationTool()
    app.mainloop()