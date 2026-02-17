from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BasePlugin(ABC):
    """
    Абстрактный базовый класс для всех плагинов-источников.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def initialize(self) -> bool:
        """Инициализация (например, выбор лучшего инстанса)."""
        pass

    @abstractmethod
    async def search(self, query: str) -> List[Dict[str, Any]]:
        """Поиск видео. Возвращает список словарей с метаданными."""
        pass

    @abstractmethod
    async def get_trending(self) -> List[Dict[str, Any]]:
        """Получение трендов."""
        pass

    @abstractmethod
    async def get_stream_url(self, video_id: str) -> str:
        """Получение прямой ссылки на поток (для mpv)."""
        pass