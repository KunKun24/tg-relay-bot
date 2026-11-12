# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Read-only runtime heartbeat and queue health; never prints tokens or message content."""
from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relayapp.config import DB_PATH


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def main():
    con = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        row = con.execute("SELECT value FROM settings WHERE bot_id=0 AND key='runtime_heartbeat'").fetchone()
        heartbeat = json.loads(row[0]) if row else {}
        age = time.time() - heartbeat.get('at', 0)
        states = dict(con.execute('SELECT actual_state,count(*) FROM bots WHERE deleted_at IS NULL GROUP BY actual_state'))
        desired = dict(con.execute('SELECT desired_state,count(*) FROM bots WHERE deleted_at IS NULL GROUP BY desired_state'))
        unknown = con.execute("SELECT count(*) FROM broadcast_recipients WHERE status='UNKNOWN'").fetchone()[0]
        result = {'healthy': 0 <= age < 90, 'heartbeat_age_seconds': round(age, 1), 'pid': heartbeat.get('pid'),
                  'clones_actual': states, 'clones_desired': desired, 'broadcast_unknown': unknown,
                  'schema_version': con.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],
                  'integrity': con.execute('PRAGMA quick_check').fetchone()[0]}
        result['healthy'] = result['healthy'] and result['integrity'] == 'ok'
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['healthy'] else 1
    finally:
        con.close()


if __name__ == '__main__':
    raise SystemExit(main())

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
