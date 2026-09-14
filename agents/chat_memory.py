"""Chat memory -- persistent conversation storage with SQLite.

Stores every user/JARVIS message per conversation.
Gemini gets the last N messages as context for intelligent replies.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from agents.config import OUTPUT_DIR

DB_PATH = OUTPUT_DIR / "memory" / "conversations.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT DEFAULT 'New conversation',
            started_at TEXT NOT NULL,
            session_id TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            action_json TEXT DEFAULT '',
            timestamp TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conv
            ON messages(conversation_id);
    """)
    return conn


class ChatMemory:
    """Manages conversation history for a single conversation."""

    def __init__(self, conversation_id: Optional[int] = None,
                 session_id: str = ""):
        self.conn: Optional[sqlite3.Connection] = None
        self.session_id = session_id
        self._ensure()
        if conversation_id:
            self.conversation_id = conversation_id
        else:
            self.conversation_id = self._create_conversation(session_id)

    def _ensure(self):
        """Re-open the connection if it was closed (e.g. close_memory() ran
        while a live handler still held this instance)."""
        if self.conn is not None:
            try:
                self.conn.execute("SELECT 1")
                return
            except sqlite3.ProgrammingError:
                pass
        self.conn = _get_conn()

    def _create_conversation(self, session_id: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self.conn.execute(
            "INSERT INTO conversations (title, started_at, session_id) VALUES (?, ?, ?)",
            ("New conversation", now, session_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_title(self, title: str):
        self._ensure()
        self.conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title, self.conversation_id),
        )
        self.conn.commit()

    def add_message(self, role: str, content: str, action: dict = None):
        self._ensure()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        action_json = json.dumps(action, ensure_ascii=True) if action else ""
        self.conn.execute(
            "INSERT INTO messages (conversation_id, role, content, action_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.conversation_id, role, content, action_json, now),
        )
        self.conn.commit()

        # Auto-title conversation from first user message
        if role == "user":
            count = self.conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND role = 'user'",
                (self.conversation_id,),
            ).fetchone()[0]
            if count == 1:
                # First user message becomes the title (truncated)
                title = content[:60].strip()
                if len(content) > 60:
                    title += "..."
                self.set_title(title)

    def get_context(self, n: int = 10) -> list[dict]:
        """Return last N messages for Gemini context."""
        self._ensure()
        rows = self.conn.execute(
            "SELECT role, content, action_json, timestamp FROM messages "
            "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (self.conversation_id, n),
        ).fetchall()
        messages = []
        for r in reversed(rows):
            msg = {"role": r["role"], "content": r["content"]}
            if r["action_json"]:
                msg["action"] = json.loads(r["action_json"])
            messages.append(msg)
        return messages

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search across all conversations."""
        self._ensure()
        rows = self.conn.execute(
            "SELECT m.role, m.content, m.timestamp, c.title, c.id as conv_id "
            "FROM messages m JOIN conversations c ON m.conversation_id = c.id "
            "WHERE m.content LIKE ? ORDER BY m.id DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "timestamp": r["timestamp"],
                "conversation": r["title"],
                "conversation_id": r["conv_id"],
            }
            for r in rows
        ]

    def get_recent_conversations(self, limit: int = 10) -> list[dict]:
        self._ensure()
        rows = self.conn.execute(
            "SELECT c.id, c.title, c.started_at, c.session_id, "
            "(SELECT COUNT(*) FROM messages WHERE conversation_id = c.id) as msg_count "
            "FROM conversations c ORDER BY c.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "started_at": r["started_at"],
                "session_id": r["session_id"],
                "message_count": r["msg_count"],
            }
            for r in rows
        ]

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None


# ── Module-level convenience ─────────────────────────────────────────

_current: Optional[ChatMemory] = None


def get_memory(session_id: str = "") -> ChatMemory:
    global _current
    if _current is None:
        _current = ChatMemory(session_id=session_id)
    return _current


def load_conversation(conversation_id: int) -> ChatMemory:
    global _current
    if _current:
        _current.close()
    _current = ChatMemory(conversation_id=conversation_id)
    return _current


def close_memory():
    global _current
    if _current:
        _current.close()
        _current = None
