# ui/sidebar.py
"""
Сайдбар в стиле YouTube с поддержкой свёртывания.

Режимы:
  expanded  — ширина 220px, иконка + текст
  collapsed — ширина 72px,  только иконка (как мини-сайдбар YT)

Кнопка-гамбургер (☰) находится в titlebar'е и вызывает toggle().
"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QFrame, QScrollArea, QSizePolicy,
                             QToolTip)
from PyQt5.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QSize
from PyQt5.QtGui import QFont, QPainter, QPainterPath, QColor

# ── Данные пунктов навигации ──────────────────────────────────────────────────
SIDEBAR_SECTIONS = [
    (None, [
        ("\ue88a", "Главная",    "home"),
        ("\ue8f4", "Тренды",     "trending"),
        ("\ue553", "Shorts",     "shorts"),
    ]),
    ("Вы", [
        ("\ue0be", "Подписки",   "subscriptions"),
        ("\ue916", "История",    "history"),
        ("\ue065", "Плейлисты",  "playlists"),
    ]),
    ("Интересное", [
        ("\ue02c", "Фильмы",     "movies"),
        ("\ue627", "Игры",       "gaming"),
        ("\ue030", "Музыка",     "music"),
        ("\ue63a", "Новости",    "news"),
    ]),
]

WIDTH_EXPANDED  = 220
WIDTH_COLLAPSED = 72


class SidebarButton(QWidget):
    """Кнопка сайдбара — иконка + опциональный текст."""

    clicked = pyqtSignal(str)

    def __init__(self, icon: str, label: str, key: str, parent=None):
        super().__init__(parent)
        self.key        = key
        self.icon_char  = icon
        self.label_text = label
        self._active    = False
        self._hovered   = False
        self._expanded  = True

        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip(label)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 0, 12, 0)
        self._layout.setSpacing(14)

        self.icon_lbl = QLabel(icon)
        self.icon_lbl.setFixedSize(26, 26)
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        self.icon_lbl.setFont(QFont("Material Symbols Rounded", 20))
        self.icon_lbl.setStyleSheet("color:#f1f1f1; background:transparent;")

        self.text_lbl = QLabel(label)
        self.text_lbl.setFont(QFont("Segoe UI", 13))
        self.text_lbl.setStyleSheet("color:#f1f1f1; background:transparent;")
        self.text_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._layout.addWidget(self.icon_lbl)
        self._layout.addWidget(self.text_lbl)

        self._refresh()

    # ── Публичный API ──────────────────────────────────────────────────────────

    def set_active(self, active: bool):
        self._active = active
        self._refresh()

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self.text_lbl.setVisible(expanded)
        # В свёрнутом режиме центрируем иконку
        self._layout.setContentsMargins(
            0 if not expanded else 12, 0,
            0 if not expanded else 12, 0
        )
        self._layout.setAlignment(
            Qt.AlignCenter if not expanded else Qt.AlignLeft | Qt.AlignVCenter
        )
        self._refresh()

    # ── Внутренние методы ─────────────────────────────────────────────────────

    def _refresh(self):
        if self._active:
            bg, fw = "#272727", "bold"
        elif self._hovered:
            bg, fw = "#1f1f1f", "normal"
        else:
            bg, fw = "transparent", "normal"
        self.setStyleSheet(f"SidebarButton {{ background:{bg}; border-radius:10px; }}")
        self.text_lbl.setStyleSheet(
            f"color:#f1f1f1; background:transparent; font-weight:{fw};"
        )
        self.icon_lbl.setStyleSheet(
            f"color:{'#ffffff' if self._active else '#f1f1f1'}; background:transparent;"
        )

    def enterEvent(self, e):
        self._hovered = True
        self._refresh()
        if not self._expanded:
            QToolTip.showText(self.mapToGlobal(self.rect().topRight()), self.label_text)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self._refresh()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(e)


class _Divider(QFrame):
    def __init__(self, p=None):
        super().__init__(p)
        self.setFrameShape(QFrame.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet("background:#272727; border:none;")


class _SectionLabel(QLabel):
    def __init__(self, text, p=None):
        super().__init__(text, p)
        self.setFixedHeight(32)
        self.setContentsMargins(16, 0, 0, 0)
        self.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.setStyleSheet("color:#f1f1f1; background:transparent;")


class Sidebar(QWidget):
    """
    Главный виджет сайдбара.
    Вызывай toggle() чтобы свернуть/развернуть.
    Подписывайся на nav_changed(key: str) для навигации.
    """

    nav_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._buttons: dict[str, SidebarButton] = {}
        self._section_labels: list[QWidget] = []
        self._active_key: str = None

        self.setFixedWidth(WIDTH_EXPANDED)
        self.setStyleSheet("background:#0f0f0f;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;}")

        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._inner = QVBoxLayout(self._container)
        self._inner.setContentsMargins(8, 8, 8, 8)
        self._inner.setSpacing(0)

        self._build()
        self._inner.addStretch()
        scroll.setWidget(self._container)
        outer.addWidget(scroll)

        # Анимация ширины
        self._anim = QPropertyAnimation(self, b"minimumWidth")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim2 = QPropertyAnimation(self, b"maximumWidth")
        self._anim2.setDuration(200)
        self._anim2.setEasingCurve(QEasingCurve.InOutQuad)

    def _build(self):
        first = True
        for section_title, items in SIDEBAR_SECTIONS:
            if not first:
                self._inner.addSpacing(4)
                d = _Divider()
                self._section_labels.append(d)
                self._inner.addWidget(d)
                self._inner.addSpacing(4)
            first = False

            if section_title:
                lbl = _SectionLabel(section_title)
                self._section_labels.append(lbl)
                self._inner.addWidget(lbl)

            for icon, label, key in items:
                btn = SidebarButton(icon, label, key)
                btn.clicked.connect(self._on_click)
                self._buttons[key] = btn
                self._inner.addWidget(btn)

        # Активируем первый пункт
        first_key = SIDEBAR_SECTIONS[0][1][0][2]
        self.set_active(first_key)

    # ── Навигация ──────────────────────────────────────────────────────────────

    def _on_click(self, key: str):
        self.set_active(key)
        self.nav_changed.emit(key)

    def set_active(self, key: str):
        if self._active_key and self._active_key in self._buttons:
            self._buttons[self._active_key].set_active(False)
        self._active_key = key
        if key in self._buttons:
            self._buttons[key].set_active(True)

    # ── Сворачивание ───────────────────────────────────────────────────────────

    def toggle(self):
        """Переключить expanded ↔ collapsed."""
        self._expanded = not self._expanded
        target = WIDTH_EXPANDED if self._expanded else WIDTH_COLLAPSED

        # Анимируем min и max width одновременно
        for anim in (self._anim, self._anim2):
            anim.stop()
            anim.setStartValue(self.width())
            anim.setEndValue(target)
            anim.start()

        # Показываем/прячем текст и заголовки секций
        for btn in self._buttons.values():
            btn.set_expanded(self._expanded)
        for lbl in self._section_labels:
            lbl.setVisible(self._expanded)

    @property
    def is_expanded(self) -> bool:
        return self._expanded