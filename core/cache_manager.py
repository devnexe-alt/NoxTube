import os
import shutil
import asyncio
import httpx
from PyQt5.QtGui import QPixmap


class CacheManager:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = cache_dir
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
        os.makedirs(self.cache_dir)
        self._client: httpx.AsyncClient = None

    def _get_client(self) -> httpx.AsyncClient:
        """Ленивая инициализация клиента — создаём только когда цикл уже крутится."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def _url_to_path(self, url: str) -> str:
        safe = "".join(c for c in url if c.isalnum())[:60]
        return os.path.join(self.cache_dir, safe + ".jpg")

    async def get_image(self, url: str) -> QPixmap:
        """Асинхронная загрузка — скачивает если нет в кэше."""
        if not url:
            return QPixmap()

        file_path = self._url_to_path(url)

        if not os.path.exists(file_path):
            try:
                client = self._get_client()
                resp = await client.get(url)
                resp.raise_for_status()
                # Записываем во временный файл, потом переименовываем
                # чтобы не читать частично записанный файл
                tmp_path = file_path + ".tmp"
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
                os.replace(tmp_path, file_path)
            except Exception as e:
                print(f"[Cache] Ошибка загрузки {url[:50]}: {e}")
                return QPixmap()

        px = QPixmap(file_path)
        return px if not px.isNull() else QPixmap()

    def get_image_sync(self, url: str) -> QPixmap | None:
        """Синхронная проверка кэша — только если файл уже есть."""
        if not url:
            return None
        file_path = self._url_to_path(url)
        if os.path.exists(file_path):
            px = QPixmap(file_path)
            return px if not px.isNull() else None
        return None  # Нет в кэше — делегат нарисует заглушку и запустит загрузку

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()