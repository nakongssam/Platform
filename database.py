"""
database.py
-----------
프롬프트 기반 파이썬 코드 생성 + 블로그 플랫폼의 데이터 계층.

테이블 구성
  users           : 사용자 등록/로그인 (비밀번호는 PBKDF2 해시 + salt)
  prompts         : 사용자가 입력한 프롬프트 (= 공유가치, value unit)
  generated_codes : 생성된 파이썬 코드 (prompts 와 연결)
  blogs           : 생성된 코드를 설명하는 블로그 글
  comments        : 블로그에 달린 댓글 (로그인 사용자만)
  ratings         : 블로그 별점 1~5 (로그인 사용자당 1개)

Streamlit 은 상호작용마다 스크립트를 재실행하므로,
각 함수는 연결을 열고 닫는 방식으로 스레드 안전성을 확보한다.
"""

import os
import sqlite3
import hashlib
from datetime import datetime

DB_PATH = "platform.db"


# ---------------------------------------------------------------------------
# 연결 / 초기화
# ---------------------------------------------------------------------------
def get_conn():
    """행을 dict 처럼 접근할 수 있는 SQLite 연결 반환."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """앱 시작 시 호출. 테이블이 없으면 모두 생성한다."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            salt          TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prompts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            title       TEXT,
            prompt_text TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_codes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id  INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            code_text  TEXT    NOT NULL,
            model      TEXT,
            created_at TEXT    NOT NULL,
            FOREIGN KEY (prompt_id) REFERENCES prompts (id),
            FOREIGN KEY (user_id)   REFERENCES users (id)
        );
        """
    )

    # --- 추가 기능: 블로그 ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blogs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            prompt_id  INTEGER,
            title      TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            code_text  TEXT,
            created_at TEXT    NOT NULL,
            FOREIGN KEY (user_id)   REFERENCES users (id),
            FOREIGN KEY (prompt_id) REFERENCES prompts (id)
        );
        """
    )

    # --- 추가 기능: 댓글 ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            blog_id      INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            comment_text TEXT    NOT NULL,
            created_at   TEXT    NOT NULL,
            FOREIGN KEY (blog_id) REFERENCES blogs (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )

    # --- 추가 기능: 별점 (사용자당 블로그 1개) ---
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ratings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            blog_id    INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            stars      INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
            created_at TEXT    NOT NULL,
            UNIQUE (blog_id, user_id),
            FOREIGN KEY (blog_id) REFERENCES blogs (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 비밀번호 해싱 (표준 라이브러리만 사용)
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256 으로 비밀번호를 해싱한다. (hash, salt) 반환."""
    if salt is None:
        salt = os.urandom(16).hex()
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100_000
    ).hex()
    return pwd_hash, salt


# ---------------------------------------------------------------------------
# 사용자: 등록 / 인증
# ---------------------------------------------------------------------------
def create_user(username: str, password: str) -> tuple[bool, str]:
    """신규 사용자 등록. 성공 여부와 메시지를 반환한다."""
    username = username.strip()
    if not username or not password:
        return False, "아이디와 비밀번호를 모두 입력해 주세요."

    conn = get_conn()
    try:
        pwd_hash, salt = _hash_password(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, created_at) "
            "VALUES (?, ?, ?, ?)",
            (username, pwd_hash, salt, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return True, "회원가입이 완료되었습니다. 로그인해 주세요."
    except sqlite3.IntegrityError:
        return False, "이미 사용 중인 아이디입니다."
    finally:
        conn.close()


def verify_user(username: str, password: str):
    """로그인 검증. 성공 시 {'id','username'}, 실패 시 None 반환."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        if row is None:
            return None
        check_hash, _ = _hash_password(password, row["salt"])
        if check_hash == row["password_hash"]:
            return {"id": row["id"], "username": row["username"]}
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 프롬프트 + 생성 코드
# ---------------------------------------------------------------------------
def save_prompt_and_code(
    user_id: int, title: str, prompt_text: str, code_text: str, model: str
) -> int:
    """프롬프트와 생성 코드를 한 트랜잭션으로 저장하고 prompt_id 반환."""
    conn = get_conn()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO prompts (user_id, title, prompt_text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, title.strip() or None, prompt_text, now),
        )
        prompt_id = cur.lastrowid
        cur.execute(
            "INSERT INTO generated_codes "
            "(prompt_id, user_id, code_text, model, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (prompt_id, user_id, code_text, model, now),
        )
        conn.commit()
        return prompt_id
    finally:
        conn.close()


def get_user_history(user_id: int):
    """로그인한 사용자의 프롬프트 + 코드 기록을 최신순으로 반환."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.id          AS prompt_id,
                   p.title       AS title,
                   p.prompt_text AS prompt_text,
                   p.created_at  AS created_at,
                   g.code_text   AS code_text,
                   g.model       AS model
            FROM prompts p
            JOIN generated_codes g ON g.prompt_id = p.id
            WHERE p.user_id = ?
            ORDER BY p.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_shared_prompts(limit: int = 100):
    """모든 사용자가 공유하는 프롬프트 목록 (= 공유가치). 최신순."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.id          AS prompt_id,
                   p.title       AS title,
                   p.prompt_text AS prompt_text,
                   p.created_at  AS created_at,
                   u.username    AS author
            FROM prompts p
            JOIN users u ON u.id = p.user_id
            ORDER BY p.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 블로그
# ---------------------------------------------------------------------------
def create_blog(
    user_id: int, prompt_id: int | None, title: str, content: str, code_text: str
) -> int:
    """블로그 글을 저장하고 blog_id 반환."""
    conn = get_conn()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO blogs (user_id, prompt_id, title, content, code_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, prompt_id, title.strip(), content, code_text, now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_blogs(limit: int = 100):
    """블로그 목록 (작성자, 평균 별점, 별점 수, 댓글 수 포함). 최신순."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT b.id, b.title, b.created_at, b.content,
                   u.username AS author,
                   (SELECT ROUND(AVG(stars), 1) FROM ratings r WHERE r.blog_id = b.id) AS avg_rating,
                   (SELECT COUNT(*)             FROM ratings r WHERE r.blog_id = b.id) AS rating_count,
                   (SELECT COUNT(*)             FROM comments c WHERE c.blog_id = b.id) AS comment_count
            FROM blogs b
            JOIN users u ON u.id = b.user_id
            ORDER BY b.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_blog(blog_id: int):
    """블로그 단건 조회 (작성자 포함)."""
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT b.*, u.username AS author
            FROM blogs b
            JOIN users u ON u.id = b.user_id
            WHERE b.id = ?
            """,
            (blog_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 댓글
# ---------------------------------------------------------------------------
def add_comment(blog_id: int, user_id: int, comment_text: str):
    """댓글 추가."""
    text = comment_text.strip()
    if not text:
        return
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO comments (blog_id, user_id, comment_text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (blog_id, user_id, text, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def get_comments(blog_id: int):
    """블로그의 댓글 목록 (작성자 포함). 오래된 순."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT c.comment_text, c.created_at, u.username AS author
            FROM comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.blog_id = ?
            ORDER BY c.id ASC
            """,
            (blog_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 별점
# ---------------------------------------------------------------------------
def set_rating(blog_id: int, user_id: int, stars: int):
    """별점 등록/수정 (사용자당 블로그 1개, upsert)."""
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO ratings (blog_id, user_id, stars, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (blog_id, user_id)
            DO UPDATE SET stars = excluded.stars, created_at = excluded.created_at
            """,
            (blog_id, user_id, stars, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_rating(blog_id: int, user_id: int):
    """해당 사용자가 이 블로그에 준 별점. 없으면 None."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT stars FROM ratings WHERE blog_id = ? AND user_id = ?",
            (blog_id, user_id),
        ).fetchone()
        return row["stars"] if row else None
    finally:
        conn.close()


def get_rating_summary(blog_id: int) -> tuple[float, int]:
    """(평균 별점, 별점 개수) 반환."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT ROUND(AVG(stars), 1) AS avg, COUNT(*) AS cnt "
            "FROM ratings WHERE blog_id = ?",
            (blog_id,),
        ).fetchone()
        return (row["avg"] or 0.0, row["cnt"] or 0)
    finally:
        conn.close()
