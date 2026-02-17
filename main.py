import sys
import asyncio
import os

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QListWidget, QLabel,
                             QListWidgetItem, QStackedWidget, QFrame, QSizePolicy)
from PyQt5.QtCore import Qt, QFileSystemWatcher, QSize
from PyQt5.QtGui import QFontDatabase

os.environ["PATH"] = os.path.dirname(os.path.abspath(__file__)) + os.pathsep + os.environ["PATH"]

from qasync import QEventLoop
from qframelesswindow import FramelessMainWindow
from core.plugin_manager import PluginManager
from core.database import Database
from ui.delegates import VideoDelegate
from core.cache_manager import CacheManager
from ui.video_player import NativePlayer
from ui.titlebar import CustomTitleBar
from ui.sidebar import Sidebar

TITLEBAR_HEIGHT = 33
FILTER_CHIPS = ["Все", "Видеоигры", "Minecraft", "Музыка", "Новости", "Недавно", "Просмотрено"]


class MainWindow(FramelessMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NoxTube")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        self.custom_title_bar = CustomTitleBar(self)
        self.setTitleBar(self.custom_title_bar)
        # Подключаем гамбургер
        self.custom_title_bar.sidebar_toggle.connect(self._toggle_sidebar)

        if sys.platform == "win32":
            try:
                from ctypes import windll
                windll.dwmapi.DwmSetWindowAttribute(
                    int(self.winId()), 20, bytes([1]), 4
                )
            except Exception:
                pass

        self.db = Database()
        self.cache = CacheManager()
        self.plugin_manager = PluginManager()
        self.plugin_manager.load_plugins()

        self.setup_ui()
        self.setup_styles()
        self.custom_title_bar.raise_()

    # ── Window controls ───────────────────────────────────────────────────────

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.WindowStateChange:
            if hasattr(self, 'custom_title_bar'):
                self.custom_title_bar.update_maximize_button()

    def _toggle_sidebar(self):
        self.sidebar.toggle()

    # ── UI Setup ──────────────────────────────────────────────────────────────

    def setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, TITLEBAR_HEIGHT, 0, 0)
        root_layout.setSpacing(0)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root_layout.addWidget(body, stretch=1)

        # ── Sidebar ───────────────────────────────────────────────────────────
        self.sidebar = Sidebar()
        self.sidebar.nav_changed.connect(self.on_nav_changed)
        body_layout.addWidget(self.sidebar)

        # ── Right side ────────────────────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        body_layout.addWidget(right, stretch=1)

        # Search bar
        search_bar = QWidget()
        search_bar.setObjectName("searchBar")
        search_bar.setFixedHeight(64)
        sb_layout = QHBoxLayout(search_bar)
        sb_layout.setContentsMargins(16, 8, 16, 8)
        sb_layout.setSpacing(8)
        sb_layout.addStretch(1)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText("Введите запрос...")
        self.search_input.setFixedHeight(40)
        self.search_input.setMinimumWidth(400)
        self.search_input.setMaximumWidth(700)
        self.search_input.returnPressed.connect(self.on_search)

        btn_search = QPushButton("Поиск")
        btn_search.setObjectName("searchBtn")
        btn_search.setFixedHeight(40)
        btn_search.clicked.connect(self.on_search)

        sb_layout.addWidget(self.search_input)
        sb_layout.addWidget(btn_search)
        sb_layout.addStretch(1)
        right_layout.addWidget(search_bar)

        # Filter chips
        filter_bar = QWidget()
        filter_bar.setFixedHeight(52)
        filter_bar.setStyleSheet(
            "background:#0f0f0f; border-bottom: 1px solid #272727;"
        )
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(8)

        self.filter_buttons = []
        for i, chip_text in enumerate(FILTER_CHIPS):
            btn = QPushButton(chip_text)
            btn.setFixedHeight(32)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._chip_style(active=(i == 0)))
            btn.clicked.connect(lambda _checked, b=btn: self._on_chip_clicked(b))
            self.filter_buttons.append(btn)
            fl.addWidget(btn)
        fl.addStretch()
        right_layout.addWidget(filter_bar)

        # Content stack: 0=grid, 1=player
        self.content_stack = QStackedWidget()
        right_layout.addWidget(self.content_stack, stretch=1)

        # Video grid
        self.video_list = QListWidget()
        self.video_list.setObjectName("videoList")
        self.video_list.setViewMode(QListWidget.IconMode)
        self.video_list.setResizeMode(QListWidget.Adjust)
        self.video_list.setSpacing(16)
        self.video_list.setMovement(QListWidget.Static)
        self.video_list.setFocusPolicy(Qt.NoFocus)
        self.video_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.video_list.setItemDelegate(VideoDelegate(self.cache, self.video_list))
        self.video_list.itemClicked.connect(self.on_video_clicked)

        # Player
        try:
            self.player = NativePlayer()
            self.player.back_btn.clicked.connect(self.show_list)
        except Exception as e:
            print(f"Player init error: {e}")
            self.player = QFrame()
            self.player.setStyleSheet("background:black;")

        self.content_stack.addWidget(self.video_list)
        self.content_stack.addWidget(self.player)

        # Status bar
        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setFixedHeight(24)
        right_layout.addWidget(self.status_label)

    # ── Chip styles ───────────────────────────────────────────────────────────

    def _chip_style(self, active=False):
        if active:
            return ("QPushButton{background:#f1f1f1;color:#0f0f0f;border:none;"
                    "border-radius:8px;font-size:13px;font-weight:bold;padding:0 14px;}")
        return ("QPushButton{background:#272727;color:#f1f1f1;border:none;"
                "border-radius:8px;font-size:13px;padding:0 14px;}"
                "QPushButton:hover{background:#3f3f3f;}")

    def _on_chip_clicked(self, clicked):
        for btn in self.filter_buttons:
            btn.setChecked(btn is clicked)
            btn.setStyleSheet(self._chip_style(active=(btn is clicked)))

    # ── Navigation ────────────────────────────────────────────────────────────

    def on_nav_changed(self, key: str):
        search_map = {
            'gaming': 'gaming',
            'music':  'music',
            'news':   'news',
            'movies': 'movies',
        }
        if key in ('home', 'trending'):
            asyncio.create_task(self.load_trending())
        elif key in search_map:
            asyncio.create_task(self.perform_search(search_map[key]))
        self.show_list()

    # ── Video interaction ─────────────────────────────────────────────────────

    def on_video_clicked(self, item):
        data = item.data(Qt.UserRole)
        v_id = data.get('id')
        self.status_label.setText("Получение ссылки...")
        self.content_stack.setCurrentIndex(1)

        # Передаём метаданные в плеер сразу
        if hasattr(self.player, 'set_video_info'):
            self.player.set_video_info(data)

        asyncio.create_task(self.resolve_and_play(v_id, data))

    async def resolve_and_play(self, v_id: str, data: dict):
        try:
            # Параллельно: получаем стрим и загружаем похожие
            stream_task   = asyncio.create_task(
                self.plugin_manager.active_plugin.get_stream_url(v_id)
            )
            related_task  = asyncio.create_task(
                self.plugin_manager.active_plugin.search(
                    data.get('title', '')[:40]
                )
            )

            stream_url = await stream_task
            if stream_url and hasattr(self.player, 'play_raw_url'):
                self.player.play_raw_url(stream_url)
                self.status_label.setText("Воспроизведение...")
            else:
                self.status_label.setText("Ошибка: не удалось получить поток")

            related = await related_task
            # Убираем само видео из похожих
            related = [r for r in related if r.get('id') != v_id]
            if hasattr(self.player, 'set_related'):
                self.player.set_related(related)

        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")
            print(f"[Player] {e}")

    def show_list(self):
        if hasattr(self.player, 'stop'):
            self.player.stop()
        self.content_stack.setCurrentIndex(0)
        self.status_label.setText("Готово")

    # ── Styles ────────────────────────────────────────────────────────────────

    def setup_styles(self):
        style_path = os.path.join("assets", "style.qss")
        os.makedirs("assets", exist_ok=True)
        if not os.path.exists(style_path):
            with open(style_path, "w", encoding="utf-8") as f:
                f.write("QMainWindow{background:#0f0f0f;}")
        self.style_watcher = QFileSystemWatcher([style_path])
        self.style_watcher.fileChanged.connect(self.apply_styles)
        self.apply_styles()

    def apply_styles(self):
        path = os.path.join("assets", "style.qss")
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
            print("[UI] Styles reloaded")
        except Exception as e:
            print(f"[UI] Style error: {e}")

    # ── Plugin & data ─────────────────────────────────────────────────────────

    async def init_plugins(self):
        self.status_label.setText("Подключение...")
        try:
            await self.plugin_manager.set_active_plugin("Invidious")
            self.status_label.setText("Invidious: Online")
            await self.load_trending()
        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")

    def on_search(self):
        query = self.search_input.text().strip()
        if query:
            self.status_label.setText("Поиск...")
            asyncio.create_task(self.perform_search(query))

    async def perform_search(self, query: str):
        if not self.plugin_manager.active_plugin:
            return
        try:
            results = await self.plugin_manager.active_plugin.search(query)
            self.update_video_list(results)
            self.status_label.setText(f"Найдено: {len(results)}")
        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")

    async def load_trending(self):
        if not self.plugin_manager.active_plugin:
            return
        try:
            results = await self.plugin_manager.active_plugin.get_trending()
            self.update_video_list(results)
        except Exception as e:
            self.status_label.setText(f"Ошибка трендов: {e}")

    def update_video_list(self, items):
        self.video_list.clear()
        for item in items:
            li = QListWidgetItem()
            li.setData(Qt.UserRole, item)
            li.setSizeHint(QSize(320, 280))
            self.video_list.addItem(li)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    font_path = os.path.join("fonts", "MaterialSymbolsRounded.ttf")
    fid = QFontDatabase.addApplicationFont(font_path)
    if fid == -1:
        print("[Font] Не удалось загрузить Material Symbols Rounded!")
    else:
        print(f"[Font] OK — {QFontDatabase.applicationFontFamilies(fid)}")

    nid = QFontDatabase.addApplicationFont(os.path.join("fonts", "Nunito.ttf"))
    if nid != -1:
        print("[Font] Nunito OK")

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()
    asyncio.ensure_future(window.init_plugins())

    with loop:
        loop.run_forever()