import sqlite3
from typing import List, Tuple

class Database:
    def __init__(self, db_path="local_data.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                channel_id TEXT PRIMARY KEY,
                name TEXT,
                avatar_url TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS history (
                video_id TEXT PRIMARY KEY,
                title TEXT,
                timestamp INTEGER,
                position INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS playlist_items (
                playlist_id INTEGER,
                video_id TEXT,
                title TEXT,
                FOREIGN KEY(playlist_id) REFERENCES playlists(id)
            )
        """)
        self.conn.commit()

    def add_subscription(self, channel_id: str, name: str, avatar_url: str):
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO subscriptions VALUES (?, ?, ?)", 
                       (channel_id, name, avatar_url))
        self.conn.commit()

    def get_subscriptions(self) -> List[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM subscriptions")
        return cursor.fetchall()
        
    def close(self):
        self.conn.close()