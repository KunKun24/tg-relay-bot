# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Migrate a new isolated copy and compare all original rows/columns without logging data."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relayapp.schema import migrate


def quote(name):
    return '"' + name.replace('"', '""') + '"'


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

def verify(source, target):
    source, target = Path(source).resolve(strict=True), Path(target).resolve()
    if source == target or target.exists():
        raise ValueError('目标必须是尚不存在的隔离副本，不能覆盖数据库')
    target.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    new = sqlite3.connect(target)
    os.chmod(target, 0o600)
    new.row_factory = sqlite3.Row
    try:
        old.backup(new)
        migrate(new)
        checks = {}
        tables = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            columns = [r[1] for r in old.execute(f'PRAGMA table_info({quote(table)})')]
            selection = ','.join(map(quote, columns))
            before = sorted(map(tuple, old.execute(f'SELECT {selection} FROM {quote(table)}')), key=repr)
            after = sorted(map(tuple, new.execute(f'SELECT {selection} FROM {quote(table)}')), key=repr)
            checks[table] = {'rows_before': len(before), 'rows_after': len(after), 'all_original_values_preserved': before == after}
        integrity = new.execute('PRAGMA integrity_check').fetchone()[0]
        new.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # Re-running startup migrations must not duplicate grants, routes, or cases.
        extras = ('relay_routes', 'client_cases', 'entitlement_grants')
        first = {t: new.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in extras}
        migrate(new)
        second = {t: new.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in extras}
        result = {'ok': integrity == 'ok' and all(c['all_original_values_preserved'] for c in checks.values()) and first == second,
                  'integrity': integrity, 'original_tables': checks, 'derived_rows': second, 'repeat_migration_idempotent': first == second,
                  'schema_version': new.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]}
        return result
    finally:
        old.close()
        new.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--report')
    args = parser.parse_args()
    result = verify(args.source, args.target)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        path = Path(args.report)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(text + '\n')
        path.chmod(0o600)
    print(text)
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
