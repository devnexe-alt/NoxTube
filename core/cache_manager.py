# core/cache_manager.py
"""
Менеджер кэша на asyncio + httpx.
Загрузка картинок через create_task — без QThread, без конфликтов.
После загрузки эмитит image_ready(url) через маленький QObject-сигналлер.
"""
import os
import shutil
import hashlib
import asyncio

import httpx
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QPixmap


class _Signaller(QObject):
    image_ready = pyqtSignal(str)   # url


class CacheManager:
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
        os.makedirs(self.cache_dir)

        self._signaller = _Signaller()
        self.image_ready = self._signaller.image_ready   # пробрасываем наружу

        self._client: httpx.AsyncClient | None = None
        self._pending: set[str] = set()   # URL которые сейчас качаются

    # ── httpx клиент (ленивая инициализация) ─────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
            )
        return self._client

    # ── Путь к файлу кэша ────────────────────────────────────────────────────

    def _path(self, url: str) -> str:
        h = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(self.cache_dir, h + ".jpg")

    # ── Синхронная проверка (вызывается из paint()) ───────────────────────────

    def get_image_sync(self, url: str) -> QPixmap | None:
        """Возвращает QPixmap если файл уже есть в кэше, иначе None."""
        if not url:
            return None
        path = self._path(url)
        if os.path.exists(path):
            px = QPixmap(path)
            return px if not px.isNull() else None
        return None

    # ── Запрос загрузки (вызывается из paint()) ───────────────────────────────

    def request_download(self, url: str):
        """Запускает asyncio-задачу если URL ещё не качается."""
        if not url or url in self._pending:
            return
        if os.path.exists(self._path(url)):
            return
        self._pending.add(url)
        try:
            asyncio.create_task(self._download(url))
        except RuntimeError:
            # Цикл ещё не запущен — маловероятно, но на всякий случай
            self._pending.discard(url)

    # ── Заголовки в зависимости от домена ────────────────────────────────────

    def _headers_for(self, url: str) -> dict:
        """Google блокирует запросы к yt3.googleusercontent.com без Referer."""
        if "googleusercontent.com" in url or "ggpht.com" in url:
            return {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.youtube.com/",
                "Origin":  "https://www.youtube.com",
                "Accept":  "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            }
        return {"User-Agent": "Mozilla/5.0"}

    # ── Асинхронная загрузка ──────────────────────────────────────────────────

    async def _download(self, url: str):
        path = self._path(url)
        try:
            client = self._get_client()
            resp = await client.get(url, headers=self._headers_for(url))
            resp.raise_for_status()
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(resp.content)
            os.replace(tmp, path)
            # Сигналим из главного потока — asyncio всегда в main thread
            self._signaller.image_ready.emit(url)
        except Exception as e:
            print(f"[Cache] ✗ {url[-50:]}: {e}")
        finally:
            self._pending.discard(url)

    # ── Async API (для совместимости с плагином) ──────────────────────────────

    async def get_image(self, url: str) -> QPixmap:
        """Скачивает если нет, возвращает QPixmap."""
        if not url:
            return QPixmap()
        path = self._path(url)
        if not os.path.exists(path):
            await self._download(url)
        px = QPixmap(path)
        return px if not px.isNull() else QPixmap()

    # ── Закрытие ──────────────────────────────────────────────────────────────

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()