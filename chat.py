"""Persistent chat threads and messages for the recruiting agent."""
from __future__ import annotations

import json

from ats import new_id
from database import Database, utcnow


class ChatService:
    def __init__(self, db: Database):
        self.db = db

    def create_thread(self, organization_id: str, user_id: str | None,
                      title: str = "New conversation") -> str:
        thread_id, now = new_id(), utcnow()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO chat_threads
                (id,organization_id,user_id,title,created_at,updated_at) VALUES (?,?,?,?,?,?)""",
                (thread_id, organization_id, user_id, title.strip() or "New conversation", now, now))
        return thread_id

    def threads(self, organization_id: str, limit: int = 30) -> list[dict]:
        return self.db.rows("""SELECT * FROM chat_threads WHERE organization_id=?
            ORDER BY updated_at DESC LIMIT ?""", (organization_id, limit))

    def thread(self, organization_id: str, thread_id: str) -> dict | None:
        thread = self.db.one("SELECT * FROM chat_threads WHERE id=? AND organization_id=?",
                             (thread_id, organization_id))
        if not thread:
            return None
        thread["messages"] = self.messages(organization_id, thread_id)
        return thread

    def messages(self, organization_id: str, thread_id: str) -> list[dict]:
        return self.db.rows("""SELECT * FROM chat_messages
            WHERE organization_id=? AND thread_id=? ORDER BY created_at""",
            (organization_id, thread_id))

    def add_message(self, organization_id: str, thread_id: str, role: str, content: str,
                    tool_calls: list | None = None) -> str:
        message_id, now = new_id(), utcnow()
        with self.db.transaction() as tx:
            tx.execute("""INSERT INTO chat_messages
                (id,organization_id,thread_id,role,content,tool_calls_json,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (message_id, organization_id, thread_id, role, content,
                 json.dumps(tool_calls) if tool_calls else None, now))
            tx.execute("UPDATE chat_threads SET updated_at=? WHERE id=?", (now, thread_id))
        return message_id

    def rename_from_first_message(self, organization_id: str, thread_id: str, text: str) -> None:
        title = (text or "").strip().replace("\n", " ")[:60] or "New conversation"
        with self.db.transaction() as tx:
            tx.execute("""UPDATE chat_threads SET title=? WHERE id=? AND organization_id=?
                AND title='New conversation'""", (title, thread_id, organization_id))
