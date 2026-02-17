import os
import shutil
import httpx
from PyQt5.QtGui import QPixmap

class CacheManager:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = cache_dir
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir) # Чистим старый кэш при старте
        os.makedirs(self.cache_dir)
        self.client = httpx.AsyncClient()

    async def get_image(self, url: str) -> QPixmap:
        """Качает картинку или берет из папки."""
        if not url: return QPixmap()
        
        file_name = "".join([c for c in url if c.isalnum()])[:50] + ".jpg"
        file_path = os.path.join(self.cache_dir, file_name)

        if not os.path.exists(file_path):
            try:
                resp = await self.client.get(url)
                with open(file_path, "wb") as f:
                    f.write(resp.content)
            except:
                return QPixmap()

        return QPixmap(file_path)

    def get_image_sync(self, url: str) -> QPixmap:
        if not url: return QPixmap()
        file_name = "".join([c for c in url if c.isalnum()])[:50] + ".jpg"
        file_path = os.path.join(self.cache_dir, file_name)
        if os.path.exists(file_path):
            return QPixmap(file_path)
        return None # Если нет, делегат нарисует заглушку