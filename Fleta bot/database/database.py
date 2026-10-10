import sqlite3
import time

from config import DATABASE_PATH, MAX_MEMORY_ITEMS

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.cursor.execute("PRAGMA journal_mode=WAL;")
        self.cursor.execute("PRAGMA busy_timeout=5000;")
        self.create_tables()
        self._migrate_schema()

    def create_tables(self):
        self.cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (discord_id INTEGER PRIMARY KEY, selected_character INTEGER);
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL, name TEXT NOT NULL,
            description TEXT, personality TEXT, speech TEXT, world TEXT, avatar TEXT, is_public INTEGER DEFAULT 0,
            thread_id TEXT
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, character_id INTEGER, memory TEXT
        );
        CREATE TABLE IF NOT EXISTS affection (
            user_id INTEGER, character_id INTEGER, value INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, character_id)
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, character_id INTEGER,
            role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS summaries (
            user_id INTEGER, character_id INTEGER, summary TEXT,
            PRIMARY KEY (user_id, character_id)
        );
        CREATE TABLE IF NOT EXISTS alarms (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL, fire_at REAL NOT NULL,
            note TEXT DEFAULT '', repeat_seconds INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)
        self.conn.commit()

    # --- 알람 ---
    def add_alarm(self, user_id, channel_id, fire_at, note="", repeat_seconds=0):
        self.cursor.execute(
            "INSERT INTO alarms(user_id, channel_id, fire_at, note, repeat_seconds) VALUES (?, ?, ?, ?, ?)",
            (user_id, channel_id, fire_at, note, repeat_seconds),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_due_alarms(self, now):
        self.cursor.execute("SELECT * FROM alarms WHERE fire_at <= ? ORDER BY fire_at ASC", (now,))
        return self.cursor.fetchall()

    def delete_alarm(self, alarm_id):
        self.cursor.execute("DELETE FROM alarms WHERE id = ?", (alarm_id,))
        self.conn.commit()

    def reschedule_alarm(self, alarm_id, fire_at):
        self.cursor.execute("UPDATE alarms SET fire_at = ? WHERE id = ?", (fire_at, alarm_id))
        self.conn.commit()

    def get_user_alarms(self, user_id, channel_id=None):
        """아직 울리지 않은 예약 알람 목록 (곧 울릴 순)."""
        if channel_id is not None:
            self.cursor.execute(
                "SELECT * FROM alarms WHERE user_id = ? AND channel_id = ? AND fire_at > ? ORDER BY fire_at ASC",
                (user_id, channel_id, time.time()),
            )
        else:
            self.cursor.execute(
                "SELECT * FROM alarms WHERE user_id = ? AND fire_at > ? ORDER BY fire_at ASC",
                (user_id, time.time()),
            )
        return self.cursor.fetchall()

    def cancel_user_alarms(self, user_id, channel_id=None):
        """예약 알람을 취소하고 취소된 개수를 반환."""
        if channel_id is not None:
            self.cursor.execute(
                "SELECT id FROM alarms WHERE user_id = ? AND channel_id = ? AND fire_at > ?",
                (user_id, channel_id, time.time()),
            )
        else:
            self.cursor.execute(
                "SELECT id FROM alarms WHERE user_id = ? AND fire_at > ?",
                (user_id, time.time()),
            )
        ids = [row["id"] for row in self.cursor.fetchall()]
        if ids:
            self.cursor.executemany("DELETE FROM alarms WHERE id = ?", [(i,) for i in ids])
            self.conn.commit()
        return len(ids)

    def create_character(self, owner_id, name, description="", personality="", speech="", world="", avatar="", is_public=0):
        self.cursor.execute(
            "INSERT INTO characters(owner_id, name, description, personality, speech, world, avatar, is_public) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, name, description, personality, speech, world, avatar, is_public),
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_user_characters(self, owner_id):
        self.cursor.execute("SELECT * FROM characters WHERE owner_id = ? ORDER BY id DESC", (owner_id,))
        return self.cursor.fetchall()

    def get_public_characters(self):
        self.cursor.execute("SELECT * FROM characters WHERE is_public = 1 ORDER BY id DESC LIMIT 25")
        return self.cursor.fetchall()

    def get_public_characters_with_threads(self):
        self.cursor.execute("SELECT id FROM characters WHERE is_public = 1 AND thread_id IS NOT NULL")
        return self.cursor.fetchall()

    def search_public_characters(self, query):
        query = f"%{query}%"
        self.cursor.execute(
            "SELECT * FROM characters WHERE is_public = 1 AND (name LIKE ? OR description LIKE ? OR personality LIKE ? OR speech LIKE ? OR world LIKE ?) ORDER BY id DESC LIMIT 25",
            (query, query, query, query, query),
        )
        return self.cursor.fetchall()

    def get_character_by_name(self, owner_id, name):
        self.cursor.execute("SELECT * FROM characters WHERE owner_id = ? AND name = ? COLLATE NOCASE", (owner_id, name))
        return self.cursor.fetchone()

    def get_public_character_by_name(self, name):
        self.cursor.execute("SELECT * FROM characters WHERE is_public = 1 AND name = ? COLLATE NOCASE ORDER BY id DESC", (name,))
        return self.cursor.fetchall()

    def get_character(self, character_id):
        self.cursor.execute("SELECT * FROM characters WHERE id = ?", (character_id,))
        return self.cursor.fetchone()

    def delete_character(self, owner_id, name):
        character = self.get_character_by_name(owner_id, name)
        if not character:
            return False
        self.cursor.execute("DELETE FROM characters WHERE id = ?", (character["id"],))
        self.cursor.execute("DELETE FROM memories WHERE character_id = ?", (character["id"],))
        self.cursor.execute("DELETE FROM conversations WHERE character_id = ?", (character["id"],))
        self.cursor.execute("DELETE FROM affection WHERE character_id = ?", (character["id"],))
        self.cursor.execute("UPDATE users SET selected_character = NULL WHERE selected_character = ?", (character["id"],))
        self.conn.commit()
        return True

    def set_character_thread(self, character_id, thread_id):
        self.cursor.execute(
            "UPDATE characters SET thread_id = ? WHERE id = ?",
            (str(thread_id) if thread_id is not None else None, character_id),
        )
        self.conn.commit()

    def update_character_avatar(self, character_id: int, avatar_url: str):
        self.cursor.execute("UPDATE characters SET avatar = ? WHERE id = ?", (avatar_url, character_id))
        self.conn.commit()

    def _migrate_schema(self):
        self.cursor.execute("PRAGMA table_info(characters)")
        columns = [row[1] for row in self.cursor.fetchall()]
        if "thread_id" not in columns:
            self.cursor.execute("ALTER TABLE characters ADD COLUMN thread_id TEXT")
            self.conn.commit()
        self.cursor.execute("PRAGMA table_info(alarms)")
        alarm_columns = [row[1] for row in self.cursor.fetchall()]
        if alarm_columns and "repeat_seconds" not in alarm_columns:
            self.cursor.execute("ALTER TABLE alarms ADD COLUMN repeat_seconds INTEGER DEFAULT 0")
            self.conn.commit()

    def set_selected_character(self, user_id, character_id):
        self.cursor.execute("INSERT INTO users(discord_id, selected_character) VALUES(?, ?) ON CONFLICT(discord_id) DO UPDATE SET selected_character = excluded.selected_character", (user_id, character_id))
        self.conn.commit()

    def get_selected_character(self, user_id):
        self.cursor.execute("SELECT selected_character FROM users WHERE discord_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return self.get_character(row["selected_character"]) if row and row["selected_character"] else None

    def get_setting(self, key, default=None):
        self.cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = self.cursor.fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.cursor.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def add_conversation(self, user_id, character_id, role, content):
        self.cursor.execute("INSERT INTO conversations(user_id, character_id, role, content) VALUES (?, ?, ?, ?)", (user_id, character_id, role, content))
        self.conn.commit()

    def get_conversation(self, user_id, character_id, limit=12):
        self.cursor.execute("SELECT role, content, timestamp FROM conversations WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT ?", (user_id, character_id, limit))
        return list(reversed(self.cursor.fetchall()))

    def count_conversations(self, user_id, character_id):
        self.cursor.execute("SELECT COUNT(*) AS c FROM conversations WHERE user_id = ? AND character_id = ?", (user_id, character_id))
        return self.cursor.fetchone()["c"]

    def get_conversations_for_summary(self, user_id, character_id, keep_recent):
        """최근 keep_recent개를 제외한 오래된 대화 전체 (오래된 순)."""
        total = self.count_conversations(user_id, character_id)
        older_count = total - keep_recent
        if older_count <= 0:
            return []
        self.cursor.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? AND character_id = ? ORDER BY id ASC LIMIT ?",
            (user_id, character_id, older_count),
        )
        return self.cursor.fetchall()

    def delete_oldest_conversations(self, user_id, character_id, keep_recent):
        self.cursor.execute(
            "DELETE FROM conversations WHERE user_id = ? AND character_id = ? AND id NOT IN "
            "(SELECT id FROM conversations WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT ?)",
            (user_id, character_id, user_id, character_id, keep_recent),
        )
        self.conn.commit()

    def get_summary(self, user_id, character_id):
        self.cursor.execute("SELECT summary FROM summaries WHERE user_id = ? AND character_id = ?", (user_id, character_id))
        row = self.cursor.fetchone()
        return row["summary"] if row else ""

    def set_summary(self, user_id, character_id, summary):
        self.cursor.execute(
            "INSERT INTO summaries(user_id, character_id, summary) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, character_id) DO UPDATE SET summary = excluded.summary",
            (user_id, character_id, summary),
        )
        self.conn.commit()

    def add_memory(self, user_id, character_id, memory):
        self.cursor.execute("INSERT INTO memories(user_id, character_id, memory) VALUES (?, ?, ?)", (user_id, character_id, memory))
        self.cursor.execute(
            f"DELETE FROM memories WHERE user_id = ? AND character_id = ? AND id NOT IN "
            f"(SELECT id FROM memories WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT {MAX_MEMORY_ITEMS})",
            (user_id, character_id, user_id, character_id),
        )
        self.conn.commit()

    def get_memories(self, user_id, character_id, limit=None):
        if limit is None: limit = MAX_MEMORY_ITEMS
        self.cursor.execute("SELECT memory FROM memories WHERE user_id = ? AND character_id = ? ORDER BY id DESC LIMIT ?", (user_id, character_id, limit))
        return self.cursor.fetchall()

    def clear_conversation(self, user_id, character_id):
        self.cursor.execute("DELETE FROM conversations WHERE user_id = ? AND character_id = ?", (user_id, character_id))
        self.cursor.execute("DELETE FROM summaries WHERE user_id = ? AND character_id = ?", (user_id, character_id))
        self.conn.commit()


db = Database()
