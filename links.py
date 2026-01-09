import sqlite3
import uuid

conn = sqlite3.connect("brain.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_links (
  chat_id TEXT PRIMARY KEY,
  link_id TEXT NOT NULL
)
""")
conn.commit()


def get_namespace_for_chat(chat_id: int) -> str:
    cursor.execute("SELECT link_id FROM chat_links WHERE chat_id = ?", (str(chat_id),))
    row = cursor.fetchone()
    if row and row[0]:
        return f"link:{row[0]}"
    return f"tg:{chat_id}"


def create_link_for_chat(chat_id: int) -> str:
    link_id = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT OR REPLACE INTO chat_links (chat_id, link_id) VALUES (?, ?)",
        (str(chat_id), link_id),
    )
    conn.commit()
    return link_id


def join_link_for_chat(chat_id: int, link_id: str) -> None:
    cursor.execute(
        "INSERT OR REPLACE INTO chat_links (chat_id, link_id) VALUES (?, ?)",
        (str(chat_id), link_id),
    )
    conn.commit()


def unlink_chat(chat_id: int) -> None:
    cursor.execute("DELETE FROM chat_links WHERE chat_id = ?", (str(chat_id),))
    conn.commit()
