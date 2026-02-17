from PyQt5.QtWidgets import QStyledItemDelegate, QStyle
from PyQt5.QtCore import Qt, QRect, QSize, QRectF
from PyQt5.QtGui import QPainter, QColor, QFont, QPainterPath, QFontMetrics


class VideoDelegate(QStyledItemDelegate):
    CARD_W  = 320
    CARD_H  = 280
    THUMB_H = 180
    AVATAR  = 36
    RADIUS  = 10

    def __init__(self, cache_manager, parent=None):
        super().__init__(parent)
        self.cache = cache_manager

        # Подписываемся на сигнал «картинка готова» — перерисовываем viewport
        self.cache.image_ready.connect(self._on_image_ready)

    def _on_image_ready(self, url: str):
        """Вызывается из главного потока когда картинка скачана."""
        widget = self.parent()
        if widget and hasattr(widget, 'viewport'):
            widget.viewport().update()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fill_rounded(self, painter, rect, radius, color):
        p = QPainterPath()
        p.addRoundedRect(QRectF(rect), radius, radius)
        painter.fillPath(p, QColor(color))

    def _fill_rounded_rgba(self, painter, rect, radius, r, g, b, a):
        p = QPainterPath()
        p.addRoundedRect(QRectF(rect), radius, radius)
        painter.fillPath(p, QColor(r, g, b, a))

    def _fill_circle(self, painter, rect, color):
        p = QPainterPath()
        p.addEllipse(QRectF(rect))
        painter.fillPath(p, QColor(color))

    def _clip_rounded(self, painter, rect, radius):
        p = QPainterPath()
        p.addRoundedRect(QRectF(rect), radius, radius)
        painter.setClipPath(p)

    # ── Paint ─────────────────────────────────────────────────────────────────

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

        if is_hovered:
            self._fill_rounded(painter, rect.adjusted(2, 2, -2, -2), 12, "#1a1a1a")

        # ── 1. ПРЕВЬЮ ─────────────────────────────────────────────────────────
        thumb_rect = QRect(
            rect.left() + 8, rect.top() + 8,
            rect.width() - 16, self.THUMB_H
        )
        thumb_url = data.get('thumbnail', '')
        pixmap = self.cache.get_image_sync(thumb_url) if thumb_url else None

        if pixmap and not pixmap.isNull():
            painter.save()
            self._clip_rounded(painter, thumb_rect, self.RADIUS)
            painter.drawPixmap(
                thumb_rect,
                pixmap.scaled(thumb_rect.size(),
                              Qt.KeepAspectRatioByExpanding,
                              Qt.SmoothTransformation)
            )
            painter.restore()
        else:
            self._fill_rounded(painter, thumb_rect, self.RADIUS, "#272727")
            if thumb_url:
                self.cache.request_download(thumb_url)

        # Бейдж длительности
        duration = data.get('duration', '')
        if duration:
            bf = QFont("Segoe UI", 9, QFont.Bold)
            fm = QFontMetrics(bf)
            bw = fm.horizontalAdvance(duration) + 12
            bh = 20
            badge = QRect(thumb_rect.right() - bw - 5,
                          thumb_rect.bottom() - bh - 5, bw, bh)
            self._fill_rounded_rgba(painter, badge, 4, 0, 0, 0, 210)
            painter.setPen(QColor("#FFF"))
            painter.setFont(bf)
            painter.drawText(badge, Qt.AlignCenter, duration)

        # ── 2. ИНФО ───────────────────────────────────────────────────────────
        info_top = thumb_rect.bottom() + 10
        channel = data.get('channel', '')

        # ── 3. ЗАГОЛОВОК ──────────────────────────────────────────────────────
        tx = rect.left() + 8
        tw = rect.right() - tx - 28
        title = data.get('title', 'No Title')
        tf = QFont("Segoe UI", 10, QFont.Bold)
        fm = QFontMetrics(tf)
        lh = fm.height() + 2
        painter.setFont(tf)
        painter.setPen(QColor("#FFF"))

        words = title.split()
        line1, rest = "", []
        for i, w in enumerate(words):
            t = (line1 + " " + w).strip()
            if fm.horizontalAdvance(t) <= tw:
                line1 = t
            else:
                rest = words[i:]
                break

        painter.drawText(QRect(tx, info_top, tw, lh),
                         Qt.AlignLeft | Qt.AlignVCenter, line1)
        if rest:
            line2 = fm.elidedText(" ".join(rest), Qt.ElideRight, tw)
            painter.drawText(QRect(tx, info_top + lh, tw, lh),
                             Qt.AlignLeft | Qt.AlignVCenter, line2)

        # ── 4. МЕТАДАННЫЕ ─────────────────────────────────────────────────────
        meta_top = info_top + lh * 2 + 4
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("#AAA"))
        painter.drawText(QRect(tx, meta_top, tw, 18),
                         Qt.AlignLeft | Qt.AlignVCenter, channel)

        views = data.get('view_count', '')
        if views:
            try:
                v = int(views)
                vs = (f"{v/1_000_000:.1f}M" if v >= 1_000_000
                      else f"{v/1_000:.0f}K" if v >= 1_000
                      else str(v))
                views_str = f"{vs} просмотров"
            except (ValueError, TypeError):
                views_str = str(views)
            painter.drawText(QRect(tx, meta_top + 18, tw, 18),
                             Qt.AlignLeft | Qt.AlignVCenter, views_str)

        # ── 5. КНОПКА ⋮ ───────────────────────────────────────────────────────
        painter.setPen(QColor("#FFF" if is_hovered else "#AAA"))
        painter.setFont(QFont("Segoe UI", 14))
        painter.drawText(QRect(rect.right() - 26, info_top + 2, 22, 22),
                         Qt.AlignCenter, "⋮")

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(self.CARD_W, self.CARD_H)