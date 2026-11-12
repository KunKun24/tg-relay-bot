# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Core invariants against synthetic temporary SQLite only; no Telegram/API calls."""
import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import pytest
import regex

from relayapp import bots, clients, database, payments, schema


@pytest.fixture
def db(tmp_path):
    previous = database._db_path
    path = tmp_path / 'core.sqlite3'
    database.init_db(path)
    try:
        yield database.get_db()
    finally:
        database.configure_database(previous)


@pytest.fixture
def owned_bot(db):
    # Deliberately no bot_token fixture or real configured identity.
    bot_id = db.execute("INSERT INTO bots(owner_id,bot_name,telegram_bot_id) VALUES(?,?,?)", (101, 'Synthetic', 900001)).lastrowid
    db.commit()
    return bot_id


def order(bot_id, name='order-1', plan='1m', amount=5.0):
    payments.create_order(name, bot_id, 101, plan, 'Synthetic plan', amount)
    return name


def evidence(name='order-1', **extra):
    return dict(status=1, unique_id=name, amount='5', currency='USDT', **extra)


def count(db, table, where='', params=()):
    return db.execute('SELECT count(*) FROM ' + table + (' WHERE ' + where if where else ''), params).fetchone()[0]


def test_empty_schema_and_migration_idempotent(db):
    expected = {'bots', 'users', 'messages', 'conversations', 'settings', 'orders',
                'welcome_messages', 'auto_replies', 'relay_routes', 'client_cases',
                'ui_sessions', 'entitlement_grants', 'owner_transfers', 'broadcast_jobs',
                'broadcast_recipients', 'group_bindings', 'commands', 'audit_logs'}
    actual = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert expected <= actual
    database.init_db()
    database.init_db()
    assert count(db, 'schema_migrations', 'version=2') == 1
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not db.in_transaction


def test_legacy_synthetic_migration_preserves_rows_and_scopes(tmp_path):
    previous = database._db_path
    path = tmp_path / 'legacy.sqlite3'
    con = sqlite3.connect(path)
    con.executescript(schema.BASE)
    con.execute('DROP TABLE conversations')
    con.execute('CREATE TABLE conversations(bot_id INTEGER PRIMARY KEY,admin_id INTEGER,current_user_id INTEGER,updated_at TEXT)')
    con.execute("INSERT INTO bots(id,owner_id,bot_name,status) VALUES(1,101,'Synthetic','active')")
    con.execute("INSERT INTO users(bot_id,user_id,username,first_name,verified,blocked,created_at) VALUES(1,301,'synthetic_user','Safe & <Name>',1,0,'2025-01-01 10:00:00')")
    con.execute("INSERT INTO conversations VALUES(1,101,301,'2025-01-01 10:00:00')")
    con.execute("INSERT INTO messages(bot_id,user_id,direction,content,admin_message_id,user_message_id,created_at) VALUES(1,301,'user_to_admin','synthetic <body> & 😀',77,11,'2025-01-01 10:00:00')")
    con.execute("INSERT INTO orders(order_no,bot_id,owner_id,plan_key,amount,status) VALUES('old-paid',1,101,'1m',5,'paid')")
    con.execute("INSERT INTO settings VALUES(1,'safe_setting','value <&>')")
    con.execute("INSERT INTO auto_replies(bot_id,keyword,reply_text) VALUES(1,'old','<b>existing</b>')")
    con.execute("INSERT INTO auto_replies(bot_id,keyword,reply_text) VALUES(1,'draft','')")
    con.execute("INSERT INTO welcome_messages(bot_id,content_type,content_text) VALUES(1,'text','<i>hello</i>')")
    con.commit()
    original = {table: con.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                for table in ('bots', 'users', 'messages', 'orders', 'settings', 'auto_replies', 'welcome_messages')}
    con.close()
    try:
        database.init_db(path)
        migrated = database.get_db()
        database.init_db()
        for table, before in original.items():
            assert count(migrated, table) == before
        assert migrated.execute('SELECT content FROM messages').fetchone()[0] == 'synthetic <body> & 😀'
        assert migrated.execute('SELECT first_name FROM users').fetchone()[0] == 'Safe & <Name>'
        assert migrated.execute('SELECT value FROM settings').fetchone()[0] == 'value <&>'
        assert clients.get_conversation(1, 101)['current_user_id'] == 301
        assert clients.find_user_by_admin_message(1, 77, 101) == 301
        assert clients.find_user_by_admin_message(1, 77, 102) is None
        assert count(migrated, 'entitlement_grants', 'order_no=?', ('old-paid',)) == 1
        assert clients.get_auto_replies(1, enabled_only=True)[0]['keyword'] == 'old'
        assert len(clients.get_auto_replies(1, enabled_only=True)) == 1
        assert migrated.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        database.configure_database(previous)


def test_legacy_empty_welcome_migrates_disabled(tmp_path):
    previous = database._db_path
    path = tmp_path / 'legacy-empty.sqlite3'
    con = sqlite3.connect(path)
    con.executescript(schema.BASE)
    con.execute("INSERT INTO welcome_messages(bot_id,content_type,content_text,file_id) VALUES(1,'text','','')")
    con.commit()
    con.close()
    try:
        database.init_db(path)
        assert database.get_db().execute('SELECT enabled FROM welcome_messages').fetchone()[0] == 0
    finally:
        database.configure_database(previous)


def test_transaction_rollback_nested_guard_and_close_compatibility(db):
    with pytest.raises(RuntimeError, match='abort'):
        with database.transaction() as con:
            con.execute("INSERT INTO settings VALUES(1,'rollback','x')")
            raise RuntimeError('abort')
    assert count(db, 'settings') == 0
    with database.transaction():
        with pytest.raises(RuntimeError, match='Nested database transaction'):
            with database.transaction():
                pass
    db.close()
    assert database.get_db() is db
    assert db.execute('SELECT 1').fetchone()[0] == 1


def test_conversations_isolate_bot_and_admin(db):
    clients.set_conversation(1, 101, 301)
    clients.set_conversation(1, 102, 302)
    clients.set_conversation(2, 101, 303)
    assert clients.get_conversation(1) is None
    assert clients.get_conversation(1, 101)['current_user_id'] == 301
    assert clients.get_conversation(1, 102)['current_user_id'] == 302
    assert clients.get_conversation(2, 101)['current_user_id'] == 303
    clients.set_conversation(1, 101, 304)
    assert clients.get_conversation(1, 101)['current_user_id'] == 304
    assert count(db, 'conversations') == 3


def test_routes_require_chat_scope_and_actual_success(db):
    first = clients.save_message(1, 301, 'user_to_admin', 'synthetic', 77, 11, 101)
    second = clients.save_message(1, 302, 'user_to_admin', 'synthetic', 77, 12, 102)
    third = clients.save_message(2, 303, 'user_to_admin', 'synthetic', 77, 13, 101)
    assert first != second != third
    assert clients.find_user_by_admin_message(1, 77) is None
    assert clients.find_user_by_admin_message(1, 77, 101) == 301
    assert clients.find_user_by_admin_message(1, 77, 102) == 302
    assert clients.find_user_by_admin_message(2, 77, 101) == 303
    assert clients.find_user_by_admin_message(1, 77, 999) is None
    clients.save_message(1, 304, 'user_to_admin', 'synthetic', 78, 14, 101, 'UNKNOWN')
    clients.save_message(1, 305, 'user_to_admin', 'synthetic', 79, 15, 101, 'FAILED')
    clients.save_message(1, 306, 'user_to_admin', 'synthetic', 0, 16, 101)
    clients.save_message(1, 307, 'user_to_admin', 'synthetic', 80, 17, 0)
    clients.save_message(1, 308, 'admin_to_user', 'synthetic', 81, 18, 101)
    assert count(db, 'relay_routes') == 3
    assert count(db, 'client_cases', 'user_id IN (304,305)') == 0


def test_mute_expiry_isolated_and_permanent_persists(db, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(clients.time, 'time', lambda: now[0])
    for bot_id, user_id in ((1, 301), (1, 302), (2, 301)):
        clients.add_user(bot_id, user_id, '', 'Synthetic')
    clients.block_user(1, 301, 'temporary', duration_seconds=10)
    clients.block_user(1, 302, 'permanent')
    clients.block_user(2, 301, 'other bot', duration_seconds=20)
    assert clients.is_blocked(1, 301)
    now[0] = 1010
    assert not clients.is_blocked(1, 301)
    assert clients.get_user(1, 301)['blocked'] == 0
    assert clients.is_blocked(1, 302) and clients.is_blocked(2, 301)
    now[0] = 1021
    assert clients.expire_mutes(1) == 0
    assert clients.expire_mutes(2) == 1
    assert clients.is_blocked(1, 302)
    clients.unblock_user(1, 302)
    assert not clients.is_blocked(1, 302)


@pytest.mark.parametrize('duration', [0, -1])
def test_invalid_mute_duration_does_not_write(db, duration):
    with pytest.raises(ValueError):
        clients.block_user(1, 301, duration_seconds=duration)
    assert count(db, 'blacklist') == 0


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def test_auto_reply_drafts_disabled_ordering_and_payload(db):
    draft = clients.add_auto_reply(1, 'hello')
    assert clients.get_auto_reply(1, draft)['enabled'] == 0
    assert clients.match_auto_reply(1, 'hello') is None
    payload = {'type': 'text', 'text': '😀bold', 'entities': [{'type': 'bold', 'offset': 2, 'length': 4}]}
    clients.update_auto_reply(1, draft, payload=payload, enabled=1, sort_order=10)
    assert json.loads(clients.get_auto_reply(1, draft)['payload']) == payload
    priority = clients.add_auto_reply(1, 'hello')
    clients.update_auto_reply(1, priority, reply_text='priority', enabled=1, sort_order=1)
    assert clients.match_auto_reply(1, 'HELLO')['id'] == priority
    clients.update_auto_reply(1, priority, enabled=0)
    assert clients.match_auto_reply(1, 'HELLO')['id'] == draft
    assert clients.match_auto_reply(2, 'hello') is None
    clients.update_auto_reply(2, draft, enabled=0)
    assert clients.get_auto_reply(1, draft)['enabled'] == 1


def test_auto_reply_regex_invalid_or_expensive_does_not_crash(db):
    with pytest.raises(regex.error):
        clients.add_auto_reply(1, '[', 'regex')
    expensive = clients.add_auto_reply(1, '(a+)+$', 'regex')
    clients.update_auto_reply(1, expensive, enabled=1, reply_text='synthetic')
    assert clients.match_auto_reply(1, 'a' * 9000 + '!') is None
    simple = clients.add_auto_reply(1, '^hello$', 'regex')
    clients.update_auto_reply(1, simple, enabled=1, reply_text='synthetic')
    assert clients.match_auto_reply(1, 'HELLO')['id'] == simple


@pytest.mark.parametrize('_attempt', range(8))
def test_settlement_repeated_and_concurrent_grants_once(db, owned_bot, monkeypatch, _attempt):
    monkeypatch.setattr(payments.time, 'time', lambda: 100000.0)
    name = order(owned_bot)
    barrier = threading.Barrier(6)

    def settle(_):
        barrier.wait(timeout=5)
        return payments.settle_order(name, 101, evidence(name))

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(settle, range(6)))
    assert sum(not result['already_paid'] for result in results) == 1
    assert all(result['status'] == 'paid' for result in results)
    assert count(db, 'entitlement_grants', 'order_no=?', (name,)) == 1
    assert count(db, 'audit_logs', 'action=?', ('SETTLE_ORDER',)) == 1
    expiry = bots.get_bot(owned_bot)['expires_at']
    assert expiry == 100000 + 30 * 86400
    assert payments.settle_order(name, 101, evidence(name))['already_paid'] is True
    assert bots.get_bot(owned_bot)['expires_at'] == expiry


@pytest.mark.parametrize('patch', [
    {'status': 0}, {'status': 'pending'}, {'unique_id': 'wrong'},
    {'out_trade_no': 'wrong'}, {'merchant_order_no': 'wrong'}, {'amount': '6'},
    {'pay_amount': '4'}, {'paid_amount': 'NaN'}, {'amount': 'Infinity'},
    {'amount': 'invalid'}, {'coin': 'BTC'}, {'currency': 'USD'}, {'order_id': 'wrong-provider'},
])
def test_reject_mismatched_evidence_without_partial_settlement(db, owned_bot, patch):
    name = order(owned_bot)
    payments.update_order_pay_info(name, 'https://example.org/synthetic', 'provider-1')
    proof = evidence(name)
    proof.update(patch)
    with pytest.raises(ValueError):
        payments.settle_order(name, 101, proof)
    assert payments.get_order(name)['status'] == 'pending'
    assert count(db, 'entitlement_grants') == 0
    assert bots.get_bot(owned_bot)['version'] == '普通版'


def test_settlement_permission_and_ownership_revalidation(db, owned_bot):
    name = order(owned_bot)
    with pytest.raises(PermissionError):
        payments.settle_order(name, 999, evidence(name))
    db.execute('UPDATE bots SET owner_id=102 WHERE id=?', (owned_bot,))
    db.commit()
    with pytest.raises(ValueError):
        payments.settle_order(name, 101, evidence(name))
    assert payments.get_order(name)['status'] == 'pending'
    assert count(db, 'entitlement_grants') == 0


def test_settlement_rollback_covers_grant_bot_and_order(db, owned_bot, monkeypatch):
    name = order(owned_bot)

    def broken_grant(con, bot_id, plan_key):
        con.execute("UPDATE bots SET version='高级版',expire_time='永久' WHERE id=?", (bot_id,))
        raise RuntimeError('synthetic grant failure')

    monkeypatch.setattr(payments, '_grant', broken_grant)
    with pytest.raises(RuntimeError, match='synthetic grant failure'):
        payments.settle_order(name, 101, evidence(name))
    assert payments.get_order(name)['status'] == 'pending'
    assert count(db, 'entitlement_grants') == 0
    assert count(db, 'audit_logs') == 0
    assert bots.get_bot(owned_bot)['version'] == '普通版'
    assert not db.in_transaction


def test_historical_paid_order_never_regrants(db, owned_bot):
    name = order(owned_bot)
    payments.update_order_status(name, 'paid')
    before = bots.get_bot(owned_bot)
    assert payments.settle_order(name, 101)['already_paid'] is True
    assert bots.get_bot(owned_bot)['expires_at'] == before['expires_at']
    assert count(db, 'entitlement_grants') == 0


def test_permanent_survives_monthly_renewal_and_expiry_sweep(db, owned_bot, monkeypatch):
    monkeypatch.setattr(payments.time, 'time', lambda: 100000.0)
    payments.activate_vip(owned_bot, 'forever')
    payments.activate_vip(owned_bot, '1m')
    permanent = bots.get_bot(owned_bot)
    assert permanent['expire_time'] == '永久' and permanent['expires_at'] is None
    name = order(owned_bot)
    payments.settle_order(name, 101, evidence(name))
    assert bots.get_bot(owned_bot)['expire_time'] == '永久'
    assert payments.check_expired_vips() == []


def test_precise_renewal_extends_existing_deadline(db, owned_bot, monkeypatch):
    monkeypatch.setattr(payments.time, 'time', lambda: 100000.5)
    payments.activate_vip(owned_bot, '1m')
    expiry = bots.get_bot(owned_bot)['expires_at']
    payments.activate_vip(owned_bot, '3m')
    assert bots.get_bot(owned_bot)['expires_at'] == expiry + 90 * 86400


def test_transfer_revalidates_target_and_clears_old_authority(db, owned_bot):
    bots.ensure_owner_admin(owned_bot, 101)
    bots.add_bot_admin(owned_bot, 102, 101)
    bots.touch_main_user(201, 'synthetic_target', 'Target')
    for admin in (101, 102):
        clients.set_conversation(owned_bot, admin, 301)
        db.execute("INSERT INTO ui_sessions(bot_id,user_id,state,data) VALUES(?,?,?,?)", (owned_bot, admin, 'draft', '{}'))
    db.execute('INSERT INTO client_cases(bot_id,user_id,assigned_admin_id) VALUES(?,?,?)', (owned_bot, 301, 102))
    db.commit()
    with pytest.raises(ValueError):
        bots.request_transfer(owned_bot, 102, 201)
    nonce = bots.request_transfer(owned_bot, 101, 201)
    with pytest.raises(ValueError):
        bots.accept_transfer(nonce, 202)
    result = bots.accept_transfer(nonce, 201)
    assert result['from_user_id'] == 101
    assert bots.get_bot(owned_bot)['owner_id'] == 201
    assert bots.get_bot_admins(owned_bot) == [201]
    assert not bots.is_bot_admin(owned_bot, 101) and not bots.is_bot_admin(owned_bot, 102)
    assert count(db, 'conversations', 'bot_id=?', (owned_bot,)) == 0
    assert count(db, 'ui_sessions', 'bot_id=?', (owned_bot,)) == 0
    assert db.execute('SELECT assigned_admin_id FROM client_cases WHERE bot_id=?', (owned_bot,)).fetchone()[0] is None
    with pytest.raises(ValueError):
        bots.accept_transfer(nonce, 201)
    with pytest.raises(ValueError):
        bots.add_bot_admin(owned_bot, 102, 101)


def test_transfer_nonce_cancel_expiry_and_owner_cas(db, owned_bot, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(bots.time, 'time', lambda: now[0])
    for target in (201, 202, 203):
        bots.touch_main_user(target, 'synthetic_target', 'Target')
    first = bots.request_transfer(owned_bot, 101, 201)
    second = bots.request_transfer(owned_bot, 101, 202)
    with pytest.raises(ValueError):
        bots.accept_transfer(first, 201)
    now[0] = 1900
    with pytest.raises(ValueError):
        bots.accept_transfer(second, 202)
    third = bots.request_transfer(owned_bot, 101, 203)
    db.execute('UPDATE bots SET owner_id=999 WHERE id=?', (owned_bot,))
    db.commit()
    with pytest.raises(ValueError):
        bots.accept_transfer(third, 203)
    assert bots.get_bot(owned_bot)['owner_id'] == 999


def test_transfer_requires_target_to_have_started_platform(db, owned_bot):
    nonce = bots.request_transfer(owned_bot, 101, 201)
    with pytest.raises(ValueError):
        bots.accept_transfer(nonce, 201)
    assert bots.get_bot(owned_bot)['owner_id'] == 101
    bots.touch_main_user(201, 'synthetic_target', 'Target')
    bots.accept_transfer(nonce, 201)
    assert bots.get_bot(owned_bot)['owner_id'] == 201


def test_transfer_transaction_rolls_back_owner_admin_and_nonce(db, owned_bot):
    bots.ensure_owner_admin(owned_bot, 101)
    bots.add_bot_admin(owned_bot, 102, 101)
    bots.touch_main_user(201, 'synthetic_target', 'Target')
    db.execute("INSERT INTO ui_sessions(bot_id,user_id,state,data) VALUES(?,?,?,?)", (owned_bot, 101, 'draft', '{}'))
    db.commit()
    nonce = bots.request_transfer(owned_bot, 101, 201)
    db.execute("CREATE TRIGGER reject_session_cleanup BEFORE DELETE ON ui_sessions BEGIN SELECT RAISE(ABORT, 'synthetic transfer failure'); END")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match='synthetic transfer failure'):
        bots.accept_transfer(nonce, 201)
    assert bots.get_bot(owned_bot)['owner_id'] == 101
    assert bots.get_bot_admins(owned_bot) == [101, 102]
    assert count(db, 'ui_sessions') == 1
    assert db.execute('SELECT state FROM owner_transfers WHERE nonce=?', (nonce,)).fetchone()[0] == 'PENDING'
    assert count(db, 'audit_logs', 'action=?', ('ACCEPT_TRANSFER',)) == 0
    assert not db.in_transaction


def test_remove_admin_cannot_remove_owner_and_clears_session(db, owned_bot):
    bots.add_bot_admin(owned_bot, 102, 101)
    clients.set_conversation(owned_bot, 102, 301)
    db.execute("INSERT INTO ui_sessions(bot_id,user_id,state,data) VALUES(?,?,?,?)", (owned_bot, 102, 'draft', '{}'))
    db.commit()
    with pytest.raises(ValueError):
        bots.remove_bot_admin(owned_bot, 101, 101)
    with pytest.raises(ValueError):
        bots.remove_bot_admin(owned_bot, 102, 999)
    bots.remove_bot_admin(owned_bot, 102, 101)
    assert not bots.is_bot_admin(owned_bot, 102)
    assert clients.get_conversation(owned_bot, 102) is None
    assert count(db, 'ui_sessions') == 0

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
