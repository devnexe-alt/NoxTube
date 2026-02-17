from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtCore import Qt, QRect, QSize, QRectF, QModelIndex
from PyQt5.QtGui import QPainter, QColor, QFont, QPixmap, QPainterPath, QFontMetrics
import asyncio


class VideoDelegate(QStyledItemDelegate):
    CARD_W = 320
    CARD_H = 280
    THUMB_H = 180
    AVATAR_SIZE = 36
    RADIUS = 10

    def __init__(self, cache_manager, parent=None):
        super().__init__(parent)
        self.cache = cache_manager
        # URL которые уже загружаются — не дублируем задачи
        self._loading: set = set()

    # ── Вспомогательные методы ────────────────────────────────────────────────

    def _rounded_clip(self, painter, rect, radius):
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.setClipPath(path)

    def _fill_rounded(self, painter, rect, radius, color):
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.fillPath(path, QColor(color))

    def _fill_circle(self, painter, rect, color):
        path = QPainterPath()
        path.addEllipse(QRectF(rect))
        painter.fillPath(path, QColor(color))

    # ── Асинхронная загрузка превью ───────────────────────────────────────────

    def _request_thumbnail(self, url: str, index: QModelIndex):
        """Запускает загрузку картинки если ещё не идёт.
        После завершения — сигнализирует модели перерисовать ячейку."""
        if url in self._loading:
            return
        self._loading.add(url)

        async def _load():
            await self.cache.get_image(url)
            self._loading.discard(url)
            # Перерисовываем только эту ячейку
            model = index.model()
            if model:
                model.dataChanged.emit(index, index, [Qt.DecorationRole])

        try:
            asyncio.create_task(_load())
        except RuntimeError:
            self._loading.discard(url)

    # ── Главный метод отрисовки ───────────────────────────────────────────────

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        data = index.data(Qt.UserRole)
        if not data:
            painter.restore()
            return

        rect = option.rect
        is_hovered = bool(option.state & QStyle.State_MouseOver)

        # Фон при наведении
        if is_hovered:
            self._fill_rounded(painter, rect.adjusted(2, 2, -2, -2), 12, "#1a1a1a")

        # ── 1. ПРЕВЬЮ ──────────────────────────────────────────────────────────
        thumb_rect = QRect(
            rect.left() + 8, rect.top() + 8,
            rect.width() - 16, self.THUMB_H
        )

        thumb_url = data.get('thumbnail', '')
        pixmap = self.cache.get_image_sync(thumb_url)

        if pixmap and not pixmap.isNull():
            painter.save()
            self._rounded_clip(painter, thumb_rect, self.RADIUS)
            painter.drawPixmap(
                thumb_rect,
                pixmap.scaled(thumb_rect.size(), Qt.KeepAspectRatioByExpanding,
                              Qt.SmoothTransformation)
            )
            painter.restore()
        else:
            # Заглушка + запрос загрузки
            self._fill_rounded(painter, thumb_rect, self.RADIUS, "#272727")
            if thumb_url:
                self._request_thumbnail(thumb_url, index)

        # Бейдж длительности
        duration = data.get('duration', '')
        if duration:
            badge_font = QFont("Segoe UI", 9, QFont.Bold)
            fm = QFontMetrics(badge_font)
            badge_w = fm.horizontalAdvance(duration) + 12
            badge_h = 20
            badge_rect = QRect(
                thumb_rect.right() - badge_w - 5,
                thumb_rect.bottom() - badge_h - 5,
                badge_w, badge_h
            )
            path = QPainterPath()
            path.addRoundedRect(QRectF(badge_rect), 4, 4)
            painter.fillPath(path, QColor(0, 0, 0, 210))
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(badge_font)
            painter.drawText(badge_rect, Qt.AlignCenter, duration)

        # ── 2. АВАТАР ─────────────────────────────────────────────────────────
        info_top = thumb_rect.bottom() + 10
        avatar_rect = QRect(rect.left() + 8, info_top, self.AVATAR_SIZE, self.AVATAR_SIZE)

        self._fill_circle(painter, avatar_rect, "#3f3f3f")
        channel = data.get('channel', '?')
        painter.setPen(QColor("#AAAAAA"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(avatar_rect, Qt.AlignCenter, channel[0].upper() if channel else '?')

        # ── 3. ЗАГОЛОВОК ───────────────────────────────────────────────────────
        text_x = avatar_rect.right() + 10
        text_w = rect.right() - text_x - 28

        title = data.get('title', 'No Title')
        title_font = QFont("Segoe UI", 10, QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor("#FFFFFF"))

        fm = QFontMetrics(title_font)
        line_h = fm.height() + 2

        # Двухстрочный перенос
        words = title.split()
        line1, line2_words = "", []
        for i, word in enumerate(words):
            test = (line1 + " " + word).strip()
            if fm.horizontalAdvance(test) <= text_w:
                line1 = test
            else:
                line2_words = words[i:]
                break

        painter.drawText(
            QRect(text_x, info_top, text_w, line_h),
            Qt.AlignLeft | Qt.AlignVCenter, line1
        )
        if line2_words:
            line2 = fm.elidedText(" ".join(line2_words), Qt.ElideRight, text_w)
            painter.drawText(
                QRect(text_x, info_top + line_h, text_w, line_h),
                Qt.AlignLeft | Qt.AlignVCenter, line2
            )

        # ── 4. МЕТАДАННЫЕ ──────────────────────────────────────────────────────
        meta_top = info_top + line_h * 2 + 4
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("#AAAAAA"))

        painter.drawText(
            QRect(text_x, meta_top, text_w, 18),
            Qt.AlignLeft | Qt.AlignVCenter, channel
        )

        views = data.get('view_count', '')
        if views:
            try:
                v = int(views)
                if v >= 1_000_000:
                    views_str = f"{v / 1_000_000:.1f}M просмотров"
                elif v >= 1_000:
                    views_str = f"{v / 1_000:.0f}K просмотров"
                else:
                    views_str = f"{v} просмотров"
            except (ValueError, TypeError):
                views_str = str(views)
            painter.drawText(
                QRect(text_x, meta_top + 18, text_w, 18),
                Qt.AlignLeft | Qt.AlignVCenter, views_str
            )

        # ── 5. КНОПКА "⋮" ─────────────────────────────────────────────────────
        dots_rect = QRect(rect.right() - 26, info_top + 2, 22, 22)
        painter.setPen(QColor("#FFFFFF" if is_hovered else "#AAAAAA"))
        painter.setFont(QFont("Segoe UI", 14))
        painter.drawText(dots_rect, Qt.AlignCenter, "⋮")

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(self.CARD_W, self.CARD_H)