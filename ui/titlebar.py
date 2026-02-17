# ui/titlebar.py
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit)
from core.constants import MaterialIcon
from utils.resources import resource_path

TITLEBAR_HEIGHT = 36


class CustomTitleBar(QWidget):
    sidebar_toggle = pyqtSignal()
    search_requested = pyqtSignal(str)   # текст поиска

    def __init__(self, parent):
        super().__init__(parent)
        self.main_window = parent
        self.setFixedHeight(TITLEBAR_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(0)

        # ── Левая часть: гамбургер + иконка ──────────────────────────────────
        self.hamburger_btn = self._make_btn(MaterialIcon.SIDE_BAR, "sidebar")
        self.hamburger_btn.clicked.connect(self.sidebar_toggle.emit)
        layout.addWidget(self.hamburger_btn)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(20, 20)
        self.icon_label.setContentsMargins(6, 0, 12, 0)
        pixmap = QPixmap(resource_path("icon.ico")).scaled(
            20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        if not pixmap.isNull():
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setScaledContents(True)
        layout.addWidget(self.icon_label)

        # ── Центр: строка поиска ──────────────────────────────────────────────
        search_widget = QWidget()
        search_widget.setObjectName("titleSearchWidget")
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("titleSearchInput")
        self.search_input.setPlaceholderText("Введите запрос...")
        self.search_input.setFixedHeight(26)
        self.search_input.setMinimumWidth(200)
        self.search_input.setMaximumWidth(600)
        self.search_input.returnPressed.connect(self._on_search)
        # Запрещаем перетаскивание окна при клике на поиск
        self.search_input.mousePressEvent = self._search_click

        self.search_btn = QPushButton(MaterialIcon.SEARCH)
        self.search_btn.setObjectName("titleSearchBtn")
        self.search_btn.setFixedSize(26, 26)
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.clicked.connect(self._on_search)
        self.search_btn.setStyleSheet("""
            QPushButton {
                background: #272727;
                border: 1px solid transparent;
                border-left: none;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                color: #f1f1f1;
                font-family: 'Material Symbols Rounded';
                font-size: 18px;
            }
            QPushButton:hover { background: #3f3f3f; }
        """)

        search_layout.addStretch()
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        search_layout.addStretch()

        layout.addWidget(search_widget, stretch=1)

        # ── Правая часть: кнопки окна ─────────────────────────────────────────
        right = QWidget()
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 2, 0)
        right_layout.setSpacing(0)

        self.minimize_btn = self._make_btn(MaterialIcon.MINIMIZE, "minimize")
        self.maximize_btn = self._make_btn(MaterialIcon.MAXIMIZE, "maximize")
        self.close_btn    = self._make_btn(MaterialIcon.CLOSE,    "close")

        right_layout.addWidget(self.minimize_btn)
        right_layout.addWidget(self.maximize_btn)
        right_layout.addWidget(self.close_btn)
        layout.addWidget(right)

        self.minimize_btn.clicked.connect(self.main_window.showMinimized)
        self.maximize_btn.clicked.connect(self.toggle_maximize)
        self.close_btn.clicked.connect(self.main_window.close)

        self.setStyleSheet("""
            CustomTitleBar {
                background-color: #0f0f0f;
                border-bottom: 1px solid #272727;
            }
            QLineEdit#titleSearchInput {
                background: #272727;
                border: 1px solid transparent;
                border-right: none;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                padding: 0 8px;
                color: #f1f1f1;
                font-size: 14px;
                font-family: 'Segoe UI';
            }
            QLineEdit#titleSearchInput:focus {
                border-color: transparent;
                background: rgba(255,255,255,0.15);
            }
        """)

    def _search_click(self, event):
        """Перехватываем click на поиск — не даём окну начать перетаскивание."""
        QLineEdit.mousePressEvent(self.search_input, event)

    def _on_search(self):
        text = self.search_input.text().strip()
        if text:
            self.search_requested.emit(text)

    def set_search_text(self, text: str):
        self.search_input.setText(text)

    def _make_btn(self, icon: str, btn_type: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setFixedSize(30, 30)
        btn.setCursor(Qt.PointingHandCursor)
        if btn_type == "close":
            style = """
                QPushButton {
                    background: transparent; border: none; border-radius: 6px;
                    color: #cccccc; font-family: 'Material Symbols Rounded'; font-size: 18px;
                }
                QPushButton:hover   { background: #e81123; color: #fff; }
                QPushButton:pressed { background: #f1707a; }
            """
        else:
            fs = 14 if btn_type == "maximize" else 18
            style = f"""
                QPushButton {{
                    background: transparent; border: none; border-radius: 6px;
                    color: #cccccc; font-family: 'Material Symbols Rounded'; font-size: {fs}px;
                }}
                QPushButton:hover   {{ background: rgba(255,255,255,0.1); color: #fff; }}
                QPushButton:pressed {{ background: rgba(255,255,255,0.15); }}
            """
        btn.setStyleSheet(style)
        return btn

    def toggle_maximize(self):
        if self.main_window.isMaximized():
            self.main_window.showNormal()
        else:
            self.main_window.showMaximized()

    def update_maximize_button(self):
        self.maximize_btn.setText(
            MaterialIcon.RESTORE if self.main_window.isMaximized() else MaterialIcon.MAXIMIZE
        )

    def mouseDoubleClickEvent(self, event):
        self.toggle_maximize()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.main_window.windowHandle().startSystemMove()
        super().mousePressEvent(event)