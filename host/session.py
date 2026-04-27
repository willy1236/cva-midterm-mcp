import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class SessionStore:
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._file_path.exists():
            self._sessions = {}
            return

        raw = self._file_path.read_text(encoding="utf-8").strip()
        if not raw:
            self._sessions = {}
            return

        payload = json.loads(raw)
        sessions = payload.get("sessions", {}) if isinstance(payload, dict) else {}
        self._sessions = sessions if isinstance(sessions, dict) else {}

    def _save(self) -> None:
        self._file_path.write_text(
            json.dumps({"sessions": self._sessions}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create(self, *, context_id: str = "general") -> dict[str, Any]:
        with self._lock:
            session_id = str(uuid4())
            now = datetime.now(UTC).isoformat()
            record: dict[str, Any] = {
                "session_id": session_id,
                "context_id": context_id,
                "created_at": now,
                "updated_at": now,
                "messages": [],
            }
            self._sessions[session_id] = record
            self._save()
            return record

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._sessions.get(session_id)
            if not isinstance(record, dict):
                return None
            return record.copy()

    def set_context(self, session_id: str, context_id: str) -> None:
        with self._lock:
            record = self._sessions.get(session_id)
            if not isinstance(record, dict):
                raise KeyError("session not found")
            record["context_id"] = context_id
            record["updated_at"] = datetime.now(UTC).isoformat()
            self._save()

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        with self._lock:
            record = self._sessions.get(session_id)
            if not isinstance(record, dict):
                raise KeyError("session not found")

            messages = record.setdefault("messages", [])
            if not isinstance(messages, list):
                messages = []
                record["messages"] = messages

            messages.append(message)
            record["updated_at"] = datetime.now(UTC).isoformat()
            self._save()


class SessionStartRequest(BaseModel):
    context_id: str = Field(default="general")


class SessionContextRequest(BaseModel):
    session_id: str
    context_id: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
