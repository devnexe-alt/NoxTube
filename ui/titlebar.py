# ui/titlebar.py
"""
Кастомный заголовок окна с кнопкой-гамбургером для сайдбара.
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from core.constants import MaterialIcon
from utils.resources import resource_path


class CustomTitleBar(QWidget):
    # Сигнал — клик по гамбургеру
    sidebar_toggle = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.main_window = parent
        self.setFixedHeight(33)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(0)

        # ── Кнопка гамбургер (☰) ──────────────────────────────────────────────
        self.hamburger_btn = self._make_btn(MaterialIcon.SIDE_BAR, "sidebar")
        self.hamburger_btn.clicked.connect(self.sidebar_toggle.emit)
        layout.addWidget(self.hamburger_btn)

        # ── Иконка приложения ─────────────────────────────────────────────────
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(18, 18)
        self.icon_label.setContentsMargins(4, 0, 0, 0)
        pixmap = QPixmap(resource_path("icon.ico")).scaled(
            18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        if not pixmap.isNull():
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setScaledContents(True)
        layout.addWidget(self.icon_label)
        layout.addSpacing(6)

        # ── Центральная область (перетаскивание) ──────────────────────────────
        center = QWidget()
        center.setObjectName("centerWidget")
        layout.addWidget(center, stretch=1)

        # ── Кнопки управления окном ───────────────────────────────────────────
        right = QWidget()
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 2, 2, 0)
        right_layout.setSpacing(0)

        self.minimize_btn = self._make_btn(MaterialIcon.MINIMIZE, "minimize")
        self.maximize_btn = self._make_btn(MaterialIcon.MAXIMIZE, "maximize")
        self.close_btn    = self._make_btn(MaterialIcon.CLOSE,    "close")

        right_layout.addWidget(self.minimize_btn)
        right_layout.addWidget(self.maximize_btn)
        right_layout.addWidget(self.close_btn)
        layout.addWidget(right)

        # Подключаем события
        self.minimize_btn.clicked.connect(self.main_window.showMinimized)
        self.maximize_btn.clicked.connect(self.toggle_maximize)
        self.close_btn.clicked.connect(self.main_window.close)

        self.setStyleSheet("""
            CustomTitleBar {
                background-color: #0f0f0f;
                border-bottom: 1px solid #272727;
            }
            #centerWidget { background-color: transparent; }
        """)

    def _make_btn(self, icon: str, btn_type: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setFixedSize(30, 30)
        btn.setCursor(Qt.PointingHandCursor)

        if btn_type == "close":
            style = """
                QPushButton {
                    background: transparent;
                    border: none;
                    border-radius: 6px;
                    color: #cccccc;
                    font-family: 'Material Symbols Rounded';
                    font-size: 18px;
                }
                QPushButton:hover  { background-color: #e81123; color: #fff; }
                QPushButton:pressed{ background-color: #f1707a; }
            """
        else:
            fs = 14 if btn_type == "maximize" else 18
            style = f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 6px;
                    color: #cccccc;
                    font-family: 'Material Symbols Rounded';
                    font-size: {fs}px;
                }}
                QPushButton:hover  {{ background-color: rgba(255,255,255,0.1); color:#fff; }}
                QPushButton:pressed{{ background-color: rgba(255,255,255,0.15); }}
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