from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtCore import Qt, QRect, QSize, QPoint
from PyQt5.QtGui import QPainter, QColor, QFont, QPixmap, QImage
import asyncio

class VideoDelegate(QStyledItemDelegate):
    def __init__(self, cache_manager, parent=None):
        super().__init__(parent)
        self.cache = cache_manager # Нам нужен кэш для картинок [cite: 3]

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        data = index.data(Qt.UserRole)
        if not data:
            painter.restore()
            return
            
        rect = option.rect
        # Фокус при наведении [cite: 8]
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#222222"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor("#1A1A1A"))

        # --- 1. Отрисовка превью ---
        thumb_rect = QRect(rect.left() + 10, rect.top() + 10, rect.width() - 20, 160)
        
        # Пытаемся достать картинку из кэша [cite: 3]
        pixmap = self.cache.get_image_sync(data.get('thumbnail', '')) # Нужен синхронный метод в Cache
        if pixmap and not pixmap.isNull():
            painter.drawPixmap(thumb_rect, pixmap.scaled(thumb_rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        else:
            painter.fillRect(thumb_rect, QColor("#333333")) # Заглушка

        # --- 2. Текст (Заголовок и Канал) ---
        # Заголовок
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Roboto", 11, QFont.Bold))
        title_rect = QRect(rect.left() + 10, thumb_rect.bottom() + 10, rect.width() - 20, 40)
        title = painter.fontMetrics().elidedText(data.get('title', ''), Qt.ElideRight, title_rect.width() * 2)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, title)

        # Метаданные (Канал) [cite: 4]
        painter.setPen(QColor("#AAAAAA"))
        painter.setFont(QFont("Roboto", 10))
        meta_text = f"{data.get('channel', 'Unknown')}"
        painter.drawText(QRect(rect.left() + 10, title_rect.bottom() + 5, rect.width() - 20, 20), Qt.AlignLeft, meta_text)

        painter.restore()

    def sizeHint(self, option, index):
        # Размер карточки как на YouTube (примерно)
        return QSize(300, 260)