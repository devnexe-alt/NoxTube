import asyncio
import json
import re
import httpx
import yt_dlp
from core.interfaces import BasePlugin


# Headers имитируют обычный браузер — без этого YouTube отдаёт пустую страницу
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class InvidiousPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self._name = "Invidious"
        self._ytdlp_path = "yt-dlp"
        self.client = httpx.AsyncClient(timeout=15.0, headers=_HEADERS,
                                        follow_redirects=True)

    @property
    def name(self) -> str:
        return self._name

    # ── Инициализация ─────────────────────────────────────────────────────────

    async def initialize(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._ytdlp_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            print(f"[yt-dlp] Версия: {stdout.decode().strip()}")
            return proc.returncode == 0
        except FileNotFoundError:
            print("[yt-dlp] Не найден.")
            return False

    # ── Парсинг аватарки через bs4 ────────────────────────────────────────────

    async def get_channel_avatar(self, channel_id: str) -> str:
        """
        Парсит страницу канала YouTube и извлекает URL аватарки.
        YouTube кладёт все данные в window.ytInitialData — парсим его через re+json.
        """
        if not channel_id:
            return ""
        if channel_id in self._avatar_cache:
            return self._avatar_cache[channel_id]

        url = f"https://www.youtube.com/channel/{channel_id}"
        try:
            r = await self.client.get(url)
            if r.status_code != 200:
                print(f"[Avatar] HTTP {r.status_code} для {channel_id}")
                return ""

            html = r.text

            # Ищем ytInitialData — большой JSON объект в теге <script>
            match = re.search(
                r"var ytInitialData\s*=\s*(\{.+?\});</script>",
                html, re.DOTALL
            )
            if not match:
                # Альтернативный паттерн
                match = re.search(
                    r"ytInitialData\s*=\s*(\{.+?\});\s*(?:var |window\[)",
                    html, re.DOTALL
                )
            if not match:
                print(f"[Avatar] ytInitialData не найден для {channel_id}")
                return ""

            data = json.loads(match.group(1))

            # Путь: header → c4TabbedHeaderRenderer → avatar → thumbnails[]
            avatar_url = self._extract_avatar_from_data(data)

            if avatar_url:
                # URL может быть без схемы: //yt3.ggpht.com/...
                if avatar_url.startswith("//"):
                    avatar_url = "https:" + avatar_url
                self._avatar_cache[channel_id] = avatar_url
                print(f"[Avatar] ✓ {channel_id[:20]}: {avatar_url[:60]}")
                return avatar_url
            else:
                print(f"[Avatar] Не найден в ytInitialData для {channel_id}")

        except json.JSONDecodeError as e:
            print(f"[Avatar] JSON ошибка для {channel_id}: {e}")
        except Exception as e:
            print(f"[Avatar] {channel_id}: {type(e).__name__}: {e}")

        return ""

    def _extract_avatar_from_data(self, data: dict) -> str:
        """Рекурсивно ищет аватарку в ytInitialData."""
        try:
            # Путь 1: header → c4TabbedHeaderRenderer → avatar
            header = (data.get("header", {})
                      .get("c4TabbedHeaderRenderer", {}))
            thumbs = header.get("avatar", {}).get("thumbnails", [])
            if thumbs:
                best = max(thumbs, key=lambda t: t.get("width", 0))
                return best.get("url", "")

            # Путь 2: microformat → microformatDataRenderer → thumbnail
            microformat = (data.get("microformat", {})
                           .get("microformatDataRenderer", {}))
            thumbs = microformat.get("thumbnail", {}).get("thumbnails", [])
            if thumbs:
                best = max(thumbs, key=lambda t: t.get("width", 0))
                return best.get("url", "")

            # Путь 3: рекурсивный поиск ключа "avatar" в header
            header_raw = data.get("header", {})
            return self._find_avatar_recursive(header_raw, depth=0)

        except Exception:
            return ""

    def _find_avatar_recursive(self, obj, depth: int) -> str:
        """Рекурсивно ищет thumbnails[] с width в любом месте объекта."""
        if depth > 6:
            return ""
        if isinstance(obj, dict):
            if "avatar" in obj:
                thumbs = obj["avatar"].get("thumbnails", [])
                if thumbs:
                    best = max(thumbs, key=lambda t: t.get("width", 0))
                    url = best.get("url", "")
                    if url:
                        return url
            for v in obj.values():
                result = self._find_avatar_recursive(v, depth + 1)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_avatar_recursive(item, depth + 1)
                if result:
                    return result
        return ""

    # ── Обогащение результатов аватарками ─────────────────────────────────────

    async def _enrich_with_avatars(self, results: list[dict], cache_manager=None):
        """Параллельно подгружает аватарки для всех уникальных каналов."""
        unique_ids = {
            r["channel_id"] for r in results
            if r.get("channel_id") and r["channel_id"] not in self._avatar_cache
        }

        if unique_ids:
            tasks = [self.get_channel_avatar(cid) for cid in unique_ids]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Проставляем avatar_url в каждый результат
        for r in results:
            cid = r.get("channel_id", "")
            r["avatar_url"] = self._avatar_cache.get(cid, "")

        # Скачиваем все аватарки через cache_manager и ждём завершения
        if cache_manager:
            download_tasks = [
                cache_manager.get_image(r["avatar_url"])
                for r in results if r.get("avatar_url")
            ]
            if download_tasks:
                await asyncio.gather(*download_tasks, return_exceptions=True)

        # Только теперь сигналим — все картинки уже в кэше
        self._signaller.avatars_ready.emit()

    # ── yt-dlp ────────────────────────────────────────────────────────────────

    async def _run_flat(self, *args) -> list[dict]:
        cmd = [
            self._ytdlp_path,
            "--dump-single-json",
            "--flat-playlist",
            "--no-warnings",
            "--quiet",
            *args
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            print("[yt-dlp] Таймаут")
            return []

        if stderr:
            err = stderr.decode(errors="replace").strip()
            if err:
                print(f"[yt-dlp] stderr: {err}")

        try:
            data = json.loads(stdout.decode(errors="replace"))
            return data.get("entries", []) or []
        except (json.JSONDecodeError, AttributeError):
            print("[yt-dlp] Ошибка парсинга JSON")
            return []

    def _parse_entry(self, e: dict) -> dict:
        duration_sec = e.get("duration") or 0
        m, s = divmod(int(duration_sec), 60)
        h, m = divmod(m, 60)
        duration_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

        video_id = e.get("id", "")
        thumbnail = (f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                     if video_id and not video_id.startswith("UC") else "")

        channel_id = e.get("channel_id") or e.get("uploader_id") or ""

        return {
            "id":          video_id,
            "title":       e.get("title", "No Title"),
            "channel":     e.get("uploader") or e.get("channel") or "Unknown",
            "channel_id":  channel_id,
            "avatar_url":  "",
            "duration":    duration_str,
            "thumbnail":   thumbnail,
            "view_count":  e.get("view_count", ""),
        }

    # ── Публичный API ─────────────────────────────────────────────────────────

    async def search(self, query: str) -> list[dict]:
        print(f"[yt-dlp] Поиск: {query}")
        entries = await self._run_flat(f"ytsearch20:{query}")
        results = [
            self._parse_entry(e) for e in entries
            if not e.get("id", "").startswith("UC")
        ]
        print(f"[yt-dlp] Найдено: {len(results)}")
        return results

    async def get_trending(self) -> list[dict]:
        print("[yt-dlp] Загрузка трендов...")
        return await self.search("trending today")

    async def get_stream_url(self, video_id: str) -> str:
        try:
            loop = asyncio.get_event_loop()
            def extract():
                with yt_dlp.YoutubeDL({'format': 'best[ext=mp4]', 'quiet': True}) as ydl:
                    return ydl.extract_info(
                        f"https://www.youtube.com/watch?v={video_id}",
                        download=False
                    )['url']
            url = await loop.run_in_executor(None, extract)
            print(f"[yt-dlp] Стрим получен")
            return url
        except Exception as e:
            print(f"[yt-dlp] Ошибка получения ссылки: {e}")
            return ""