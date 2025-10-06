import sqlite3
import time
import asyncio
from typing import Optional, Tuple, List


def get_conn(db_path: str):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    return conn


def init_db(conn: sqlite3.Connection):
    # Yuklashlar tarixi (statistika uchun)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            url TEXT,
            bytes_sent INTEGER,
            ok INTEGER,
            ts INTEGER
        )
    """)

    # Foydalanuvchilar
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at INTEGER
        )
    """)

    # Ish navbati (queue) — 5 ta worker parallel ishlaydi
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            reply_to INTEGER,
            url TEXT,
            status TEXT,               -- queued | running | done | error
            created_at INTEGER,
            started_at INTEGER,
            finished_at INTEGER,
            bytes_sent INTEGER,
            error TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at)")

    conn.commit()


# ---------- STAT ----------
def add_user(conn: sqlite3.Connection, user_id: int,
             username: Optional[str], first_name: Optional[str], last_name: Optional[str]):
    ts = int(time.time())
    conn.execute(
        """
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, username, first_name, last_name, ts),
    )
    conn.commit()


def add_download(conn: sqlite3.Connection, user_id: int, chat_id: int,
                 url: str, bytes_sent: int, ok: bool):
    ts = int(time.time())
    conn.execute(
        """
        INSERT INTO downloads (user_id, chat_id, url, bytes_sent, ok, ts)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, chat_id, url, bytes_sent, int(ok), ts),
    )
    conn.commit()


def user_stats(conn: sqlite3.Connection, user_id: int) -> Tuple[int, int]:
    cur = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(bytes_sent),0) FROM downloads WHERE user_id=? AND ok=1",
        (user_id,),
    )
    row = cur.fetchone()
    return (row[0] or 0, row[1] or 0)


def chat_stats(conn: sqlite3.Connection, chat_id: int) -> Tuple[int, int]:
    cur = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(bytes_sent),0) FROM downloads WHERE chat_id=? AND ok=1",
        (chat_id,),
    )
    row = cur.fetchone()
    return (row[0] or 0, row[1] or 0)


def top_users(conn: sqlite3.Connection, chat_id: Optional[int], limit: int = 10) -> List[tuple]:
    if chat_id is None:
        cur = conn.execute(
            """
            SELECT user_id, COUNT(*) AS c, COALESCE(SUM(bytes_sent),0) AS s
            FROM downloads WHERE ok=1
            GROUP BY user_id
            ORDER BY c DESC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        cur = conn.execute(
            """
            SELECT user_id, COUNT(*) AS c, COALESCE(SUM(bytes_sent),0) AS s
            FROM downloads
            WHERE ok=1 AND chat_id=?
            GROUP BY user_id
            ORDER BY c DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
    return cur.fetchall()


def total_users(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0


def group_active_users(conn: sqlite3.Connection, chat_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM downloads WHERE chat_id=? AND ok=1",
        (chat_id,),
    ).fetchone()[0] or 0


# ---------- QUEUE ----------
def enqueue_job(conn: sqlite3.Connection, user_id: int, chat_id: int, reply_to: int, url: str) -> tuple[int, int]:
    """
    Navbatga qo'shadi, (job_id, position) qaytaradi.
    position = sizdan oldingi 'queued' soni + 1
    """
    now = int(time.time())
    conn.execute(
        "INSERT INTO jobs (user_id, chat_id, reply_to, url, status, created_at) VALUES (?, ?, ?, ?, 'queued', ?)",
        (user_id, chat_id, reply_to, url, now),
    )
    job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    ahead = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='queued' AND id < ?",
        (job_id,)
    ).fetchone()[0] or 0
    conn.commit()
    return job_id, ahead + 1


def queued_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0] or 0


def running_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0] or 0


def claim_next_job(conn: sqlite3.Connection) -> Optional[tuple]:
    """
    Navbatdan navbatdagi ishni 'running' holatiga o'tkazib, detallarini qaytaradi.
    (id, user_id, chat_id, reply_to, url)
    Yo'q bo'lsa None.
    """
    while True:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, user_id, chat_id, reply_to, url FROM jobs WHERE status='queued' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if not row:
                conn.commit()
                return None
            jid = row[0]
            now = int(time.time())
            conn.execute(
                "UPDATE jobs SET status='running', started_at=? WHERE id=?",
                (now, jid)
            )
            conn.commit()
            return row
        except sqlite3.OperationalError:
            time.sleep(0.03)


def finish_job(conn: sqlite3.Connection, job_id: int, ok: bool, bytes_sent: int = 0, error: Optional[str] = None):
    now = int(time.time())
    conn.execute(
        "UPDATE jobs SET status=?, finished_at=?, bytes_sent=?, error=? WHERE id=?",
        ("done" if ok else "error", now, bytes_sent, error, job_id)
    )
    conn.commit()
