# ui/video_player.py
"""
Страница плеера в стиле YouTube:
  ┌─────────────────────────┬──────────────┐
  │  ffplay (встроен)       │  Похожие     │
  │                         │  видео       │
  ├─────────────────────────│  (список)    │
  │  Заголовок / инфо       │              │
  │  Лайки / кнопки         │              │
  └─────────────────────────┴──────────────┘
"""
import subprocess
import sys

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QFrame, QListWidget, QListWidgetItem,
                             QScrollArea, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QProcess, QSize
from PyQt5.QtGui import QFont, QColor, QPainter, QPainterPath, QPixmap, QFontMetrics

if sys.platform == "win32":
    import win32gui
    from PyQt5.QtGui import QWindow


# ── Мини-карточка похожего видео (правая колонка) ────────────────────────────

class RelatedVideoItem(QWidget):
    """Горизонтальная карточка как в правой колонке YouTube."""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.data = data
        self.setFixedHeight(94)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self._hovered = False
        self.setStyleSheet("background: transparent; border-radius: 8px;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Превью (заглушка — серый прямоугольник 16:9)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(168, 94)
        self.thumb_label.setStyleSheet(
            "background-color: #272727; border-radius: 6px;"
        )
        self.thumb_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.thumb_label)

        # Текст
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 4, 0, 4)
        text_layout.setSpacing(2)

        title = data.get('title', 'No Title')
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(44)
        self.title_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.title_label.setStyleSheet("color: #f1f1f1; background: transparent;")

        channel = data.get('channel', 'Unknown')
        self.channel_label = QLabel(channel)
        self.channel_label.setFont(QFont("Segoe UI", 9))
        self.channel_label.setStyleSheet("color: #aaaaaa; background: transparent;")

        duration = data.get('duration', '')
        self.duration_label = QLabel(duration)
        self.duration_label.setFont(QFont("Segoe UI", 9))
        self.duration_label.setStyleSheet("color: #aaaaaa; background: transparent;")

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.channel_label)
        text_layout.addWidget(self.duration_label)
        text_layout.addStretch()

        layout.addWidget(text_widget, stretch=1)

    def set_thumbnail(self, pixmap: QPixmap):
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(168, 94, Qt.KeepAspectRatioByExpanding,
                                   Qt.SmoothTransformation)
            self.thumb_label.setPixmap(scaled)

    def enterEvent(self, e):
        self._hovered = True
        self.setStyleSheet("background: #1f1f1f; border-radius: 8px;")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self.setStyleSheet("background: transparent; border-radius: 8px;")
        super().leaveEvent(e)


# ── Основной виджет плеера ───────────────────────────────────────────────────

class NativePlayer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #0f0f0f;")

        # Текущие данные видео
        self._current_data: dict = {}
        self._related_items: list = []

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 16, 0, 0)
        root.setSpacing(24)

        # ── Левая колонка: видео + инфо ───────────────────────────────────────
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Кнопка назад
        back_row = QHBoxLayout()
        self.back_btn = QPushButton("← Назад")
        self.back_btn.setFixedSize(90, 32)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet('''
            QPushButton {
                background-color: #272727;
                color: #f1f1f1;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-family: 'Segoe UI';
            }
            QPushButton:hover { background-color: #3f3f3f; }
        ''')
        back_row.addWidget(self.back_btn)
        back_row.addStretch()
        left_layout.addLayout(back_row)
        left_layout.addSpacing(8)

        # Контейнер ffplay
        self.video_container = QWidget()
        self.video_container.setStyleSheet("background-color: #000;")
        self.video_container.setMinimumHeight(400)
        self.video_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.video_container, stretch=1)

        # ── Инфо под видео ────────────────────────────────────────────────────
        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        info_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        info_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        info_scroll.setFixedHeight(130)

        info_widget = QWidget()
        info_widget.setStyleSheet("background: transparent;")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 12, 0, 0)
        info_layout.setSpacing(6)

        # Заголовок
        self.title_label = QLabel("Загрузка...")
        self.title_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.title_label.setStyleSheet("color: #f1f1f1;")
        self.title_label.setWordWrap(True)
        info_layout.addWidget(self.title_label)

        # Строка: канал + подписчики
        channel_row = QHBoxLayout()
        channel_row.setSpacing(12)

        # Аватар-заглушка
        self.avatar_label = QLabel("?")
        self.avatar_label.setFixedSize(36, 36)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.avatar_label.setStyleSheet(
            "background-color: #3f3f3f; color: #aaa; border-radius: 18px;"
        )

        channel_col = QVBoxLayout()
        channel_col.setSpacing(0)
        self.channel_label = QLabel("Канал")
        self.channel_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.channel_label.setStyleSheet("color: #f1f1f1;")
        self.subs_label = QLabel("")
        self.subs_label.setFont(QFont("Segoe UI", 9))
        self.subs_label.setStyleSheet("color: #aaaaaa;")
        channel_col.addWidget(self.channel_label)
        channel_col.addWidget(self.subs_label)

        # Кнопки действий
        self.like_btn   = self._action_btn("👍  Нравится")
        self.share_btn  = self._action_btn("↗  Поделиться")
        self.dl_btn     = self._action_btn("⬇  Скачать")

        channel_row.addWidget(self.avatar_label)
        channel_row.addLayout(channel_col)
        channel_row.addStretch()
        channel_row.addWidget(self.like_btn)
        channel_row.addWidget(self.share_btn)
        channel_row.addWidget(self.dl_btn)
        info_layout.addLayout(channel_row)

        # Просмотры / дата
        self.meta_label = QLabel("")
        self.meta_label.setFont(QFont("Segoe UI", 10))
        self.meta_label.setStyleSheet("color: #aaaaaa;")
        info_layout.addWidget(self.meta_label)

        info_scroll.setWidget(info_widget)
        left_layout.addWidget(info_scroll)

        root.addWidget(left, stretch=1)

        # ── Правая колонка: похожие видео ─────────────────────────────────────
        right = QWidget()
        right.setFixedWidth(402)
        right.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 16, 0)
        right_layout.setSpacing(8)

        related_title = QLabel("Похожие видео")
        related_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        related_title.setStyleSheet("color: #f1f1f1;")
        right_layout.addWidget(related_title)

        self.related_scroll = QScrollArea()
        self.related_scroll.setWidgetResizable(True)
        self.related_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.related_scroll.setStyleSheet('''
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 6px; }
            QScrollBar::handle:vertical { background: #3f3f3f; border-radius: 3px; }
        ''')

        self.related_container = QWidget()
        self.related_container.setStyleSheet("background: transparent;")
        self.related_list_layout = QVBoxLayout(self.related_container)
        self.related_list_layout.setContentsMargins(0, 0, 0, 0)
        self.related_list_layout.setSpacing(4)
        self.related_list_layout.addStretch()

        self.related_scroll.setWidget(self.related_container)
        right_layout.addWidget(self.related_scroll, stretch=1)

        root.addWidget(right)

        # ── Логика процесса ───────────────────────────────────────────────────
        self.process = QProcess(self)
        self.embed_timer = QTimer()
        self.embed_timer.setInterval(200)
        self.embed_timer.timeout.connect(self._try_embed)
        self.current_hwnd = None
        self.status_label = QLabel()  # совместимость с main.py

    # ── Кнопки действий ───────────────────────────────────────────────────────
    def _action_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet('''
            QPushButton {
                background-color: #272727;
                color: #f1f1f1;
                border: none;
                border-radius: 17px;
                font-size: 12px;
                font-family: 'Segoe UI';
                padding: 0 14px;
            }
            QPushButton:hover { background-color: #3f3f3f; }
        ''')
        return btn

    # ── Публичный API ─────────────────────────────────────────────────────────

    def set_video_info(self, data: dict):
        """Заполняет инфо-панель данными видео."""
        self._current_data = data
        title = data.get('title', '')
        channel = data.get('channel', '')

        self.title_label.setText(title)
        self.channel_label.setText(channel)
        self.avatar_label.setText(channel[0].upper() if channel else '?')

        views = data.get('view_count', '')
        if views:
            try:
                v = int(views)
                views_str = (f"{v/1_000_000:.1f} млн просмотров" if v >= 1_000_000
                             else f"{v/1_000:.0f} тыс. просмотров" if v >= 1_000
                             else f"{v} просмотров")
            except (ValueError, TypeError):
                views_str = str(views)
            self.meta_label.setText(views_str)

    def set_related(self, items: list):
        """Заполняет список похожих видео."""
        # Очищаем старые
        while self.related_list_layout.count() > 1:
            item = self.related_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._related_items = items
        for data in items[:20]:
            card = RelatedVideoItem(data)
            self.related_list_layout.insertWidget(
                self.related_list_layout.count() - 1, card
            )

    def play_raw_url(self, url: str):
        if not url:
            return
        self.stop()

        args = [
            "-loglevel", "quiet",
            "-noborder",
            "-window_title", "NoxInternalPlayer",
            url
        ]
        self.process.start("ffplay", args)
        self.embed_timer.start()

    def _try_embed(self):
        if sys.platform != "win32":
            self.embed_timer.stop()
            return

        hwnd = win32gui.FindWindow(None, "NoxInternalPlayer")
        if hwnd and hwnd != self.current_hwnd:
            self.current_hwnd = hwnd
            self.embed_timer.stop()

            window = QWindow.fromWinId(hwnd)
            self.video_widget = QWidget.createWindowContainer(
                window, self.video_container
            )

            # Пересоздаём layout контейнера
            old_layout = self.video_container.layout()
            if old_layout:
                try:
                    import sip
                    sip.delete(old_layout)
                except Exception:
                    pass

            v_layout = QVBoxLayout(self.video_container)
            v_layout.setContentsMargins(0, 0, 0, 0)
            v_layout.addWidget(self.video_widget)

    def stop(self):
        self.embed_timer.stop()
        if self.process.state() == QProcess.Running:
            self.process.kill()
            self.process.waitForFinished(1000)
        self.current_hwnd = None

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
