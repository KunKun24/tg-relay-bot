# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Run as service user to take a consistent private SQLite snapshot."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relayapp.config import DB_PATH, ROOT


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def main():
    folder = ROOT / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = folder / f'relay-{stamp}.sqlite3'
    with target.open('xb'):
        target.chmod(0o600)
    source = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + '?mode=ro', uri=True)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
        integrity = dest.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError('备份完整性检查失败')
    finally:
        dest.close()
        source.close()
    print(json.dumps({'path': str(target), 'bytes': target.stat().st_size, 'integrity': integrity}, ensure_ascii=False))


if __name__ == '__main__':
    main()

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
