import sys
import asyncio
import os

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QListWidget, 
                             QLabel, QListWidgetItem, QStackedWidget, QFrame )
from PyQt5.QtCore import Qt, QFileSystemWatcher, QSize

os.environ["PATH"] = os.path.dirname(os.path.abspath(__file__)) + os.pathsep + os.environ["PATH"]

from qasync import QEventLoop
from qframelesswindow import FramelessMainWindow
from core.plugin_manager import PluginManager
from core.database import Database
from ui.delegates import VideoDelegate
from core.cache_manager import CacheManager
from ui.video_player import NativePlayer

from ui.titlebar import CustomTitleBar

class MainWindow(FramelessMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NoxTube (Private Client)")
        self.resize(1200, 800)

        self.custom_title_bar = CustomTitleBar(self)
        self.setTitleBar(self.custom_title_bar)
        
        # 3. Применяем темную тему для Win10/11 (как в твоем IDE)
        if sys.platform == "win32":
            from ctypes import windll
            windll.dwmapi.DwmSetWindowAttribute(
                int(self.winId()), 20, bytes([1]), 4
            )

        # Core Components
        self.db = Database()
        self.cache = CacheManager()
        self.plugin_manager = PluginManager()
        self.plugin_manager.load_plugins() 
        
        # UI Setup
        self.setup_ui()
        self.setup_styles()
        
        # ВАЖНО: Мы НЕ вызываем asyncio.create_task здесь, 
        # так как цикл событий еще не крутится.

    def toggleMaximized(self):
        """Переключение между полным экраном и обычным размером"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event):
        # Позволяет перетаскивать окно, если нажата левая кнопка мыши
        if event.button() == Qt.LeftButton:
            self.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.content_area = QWidget()
        self.content_layout = QHBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        # --- 1. Sidebar (Левая панель) ---
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(200)
        self.sidebar.addItems(["Trending", "Subscriptions", "History", "Playlists"])
        self.content_layout.addWidget(self.sidebar)

        # --- 2. Right Side (Правая часть с контентом) ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container) # Вот определение той самой переменной
        main_layout.addWidget(right_container)

        # Поиск (в верхней части правой стороны)
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search on YouTube...")
        btn_search = QPushButton("Search")
        btn_search.clicked.connect(self.on_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(btn_search)
        right_layout.addLayout(search_layout)

        # Стек контента (Список видео или Плеер)
        self.content_stack = QStackedWidget()
        
        # Список видео
        self.video_list = QListWidget()
        self.video_list.setViewMode(QListWidget.IconMode) # Режим сетки 
        self.video_list.setResizeMode(QListWidget.Adjust) # Авто-подстройка колонок 
        self.video_list.setSpacing(20)                    # Промежутки между видео 
        self.video_list.setMovement(QListWidget.Static)   # Запрет перетаскивания карточек 
        self.video_list.setStyleSheet("background-color: transparent; border: none;") # 
        
        # Применяем новый делегат, который мы сейчас создадим 
        self.video_list.setItemDelegate(VideoDelegate(self.cache, self.video_list))
        
        self.video_list.itemClicked.connect(self.on_video_clicked)

        try:
            self.player = NativePlayer()
            # Подключаем сигнал "Назад" от плеера (реализуем ниже)
            self.player.back_btn.clicked.connect(self.show_list)
        except Exception as e:
            print(f"Player init error: {e}")
            self.player = QFrame()
            self.player.setStyleSheet("background-color: black;")
        
        self.content_stack.addWidget(self.video_list)       # Индекс 0
        self.content_stack.addWidget(self.player) # Индекс 1
        
        right_layout.addWidget(self.content_stack)

        # Статус-бар внизу
        self.status_label = QLabel("Ready")
        right_layout.addWidget(self.status_label)

        main_layout.addWidget(self.content_area)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.WindowStateChange:
            if hasattr(self, 'custom_title_bar'):
                self.custom_title_bar.update_maximize_button()

    def on_video_clicked(self, item):
        data = item.data(Qt.UserRole)
        v_id = data.get('id')  # <-- сюда приходит ID канала из тренда
        
        self.status_label.setText("Получение прямой ссылки...")
        self.content_stack.setCurrentIndex(1)
        
        # Запускаем получение ссылки в фоне
        asyncio.create_task(self.resolve_and_play(v_id))

    async def resolve_and_play(self, v_id):
        try:
            # Получаем прямую ссылку из активного плагина
            stream_url = await self.plugin_manager.active_plugin.get_stream_url(v_id)
            if stream_url:
                self.player.play_raw_url(stream_url)
                self.status_label.setText("Воспроизведение...")
            else:
                self.status_label.setText("Ошибка: не удалось получить поток")
        except Exception as e:
            self.status_label.setText(f"Ошибка плеера: {e}")
    def show_list(self):
        """Возврат к списку видео."""
        self.player.stop() # Останавливаем видео
        self.content_stack.setCurrentIndex(0) # Возвращаем слой списка
        self.status_label.setText("Ready")

    async def async_play(self, v_id):
        # Т.к. yt-dlp блокирующий, лучше вынести его в отдельный поток 
        # или просто вызвать метод плеера
        self.player.play_video(v_id)

    def setup_styles(self):
        """Загрузка QSS с Hot-Reload."""
        style_path = os.path.join("assets", "style.qss")
        
        if not os.path.exists("assets"):
            os.makedirs("assets")
        
        # Создаем файл, если нет
        if not os.path.exists(style_path):
            with open(style_path, "w", encoding="utf-8") as f:
                f.write("/* Base styles */\nQMainWindow { background-color: #222; }")

        self.style_watcher = QFileSystemWatcher([style_path])
        self.style_watcher.fileChanged.connect(self.apply_styles)
        self.apply_styles()

    def apply_styles(self):
        path = os.path.join("assets", "style.qss")
        try:
            # ИСПРАВЛЕНИЕ 1: Явное указание кодировки utf-8
            with open(path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
            print("[UI] Styles reloaded")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[UI] Style load error: {e}")

    async def init_plugins(self):
        self.status_label.setText("Подключение к Invidious...")
        try:
            # Теперь используем имя нового плагина
            await self.plugin_manager.set_active_plugin("Invidious")
            self.status_label.setText("Invidious: Online")
            await self.load_trending()
        except Exception as e:
            self.status_label.setText(f"Ошибка: {e}")

    def on_search(self):
        query = self.search_input.text()
        if query:
            self.status_label.setText("Searching...")
            # create_task работает здесь корректно, так как цикл уже запущен (кнопка нажата пользователем)
            asyncio.create_task(self.perform_search(query))

    async def perform_search(self, query):
        if not self.plugin_manager.active_plugin:
            self.status_label.setText("No plugin active")
            return
        
        try:
            results = await self.plugin_manager.active_plugin.search(query)
            self.update_video_list(results)
            self.status_label.setText(f"Found {len(results)} results")
        except Exception as e:
            self.status_label.setText(f"Search Error: {e}")
            print(f"[Search Error] {e}")

    async def load_trending(self):
        if not self.plugin_manager.active_plugin:
            return
        try:
            results = await self.plugin_manager.active_plugin.get_trending()
            self.update_video_list(results)
        except Exception as e:
            print(f"Trending Error: {e}")
            self.status_label.setText(f"Trending Error: {e}")

    def update_video_list(self, items):
        self.video_list.clear()
        for item in items:
            # 1. Создаем объект элемента (а не просто строку)
            list_item = QListWidgetItem()
            
            # 2. Кладем туда "сырые" данные (словарь), чтобы делегат мог их достать
            list_item.setData(Qt.UserRole, item)
            
            # 3. ВАЖНО: Задаем высоту элемента, иначе он будет высотой 0 пикселей!
            list_item.setSizeHint(QSize(0, 80)) 
            
            # 4. Добавляем в список
            self.video_list.addItem(list_item)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Интеграция asyncio + Qt
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    window = MainWindow()
    window.show()
    
    # ИСПРАВЛЕНИЕ 2: Планируем запуск init_plugins ДО запуска цикла, 
    # но задача выполнится, когда цикл (run_forever) стартанет.
    asyncio.ensure_future(window.init_plugins())
    
    with loop:
        loop.run_forever()