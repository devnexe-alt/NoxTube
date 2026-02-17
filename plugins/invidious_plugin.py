import asyncio
import json
import httpx
import yt_dlp
from core.interfaces import BasePlugin


class InvidiousPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self._name = "Invidious"
        self._ytdlp_path = "yt-dlp"
        self.client = httpx.AsyncClient(timeout=10.0)

    @property
    def name(self) -> str:
        return self._name

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
            print("[yt-dlp] Не найден. Установи: pip install yt-dlp")
            return False

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
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=30.0
            )
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
        return {
            "id":        e.get("id", ""),
            "title":     e.get("title", "No Title"),
            "channel":   e.get("uploader") or e.get("channel") or "Unknown",
            "duration":  duration_str,
            "thumbnail": e.get("thumbnail", ""),
        }

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
                    return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)['url']
            
            url = await loop.run_in_executor(None, extract)
            print(f"[yt-dlp] Стрим получен для ffplay")
            return url
        except Exception as e:
            print(f"[yt-dlp] Ошибка получения ссылки: {e}")
            return ""