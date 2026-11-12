# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading

from .config import DB_PATH

_db_conn = None
_db_path = str(DB_PATH)
_db_lock = threading.RLock()


class _PersistentConn(sqlite3.Connection):
    def close(self):
        """Compatibility for helpers that historically closed a shared connection."""


def configure_database(path):
    global _db_conn, _db_path
    with _db_lock:
        if _db_conn is not None:
            sqlite3.Connection.close(_db_conn)
        _db_conn = None
        _db_path = str(path)


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def get_db() -> sqlite3.Connection:
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = sqlite3.connect(_db_path, timeout=15, check_same_thread=False, factory=_PersistentConn)
            _db_conn.row_factory = sqlite3.Row
            _db_conn.execute('PRAGMA journal_mode=WAL')
            _db_conn.execute('PRAGMA busy_timeout=15000')
            _db_conn.execute('PRAGMA synchronous=FULL')
        return _db_conn


@contextmanager
def transaction():
    with _db_lock:
        con = get_db()
        if con.in_transaction:
            raise RuntimeError('Nested database transaction is not allowed')
        con.execute('BEGIN IMMEDIATE')
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise


def init_db(path=None):
    if path is not None:
        configure_database(path)
    from .schema import migrate
    migrate(get_db())

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
