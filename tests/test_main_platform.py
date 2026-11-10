# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Main-platform regressions with isolated SQLite and fake Telegram objects only."""
import asyncio
import json
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from telegram import MessageEntity
from telegram.error import NetworkError
from telegram.ext import ApplicationHandlerStop

from relayapp.database import init_db, get_db, transaction
from relayapp.main_sessions import (put_session, get_session, consume_session, validate_session_actor,
                                    owner_bot)
from relayapp.main_settings import MainSettingsMixin
from relayapp.main_actions import MainActionsMixin
from relayapp.main_admin import MainAdminMixin
from relayapp.managed import ManagedMixin
import relayapp.managed as managed
from relayapp.config import MAIN_ADMIN_ID
from relayapp.configuration import get_main_text, get_main_button, set_setting
from relayapp.bots import get_bot, request_transfer, accept_transfer


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path):
    init_db(tmp_path / 'main-isolated.sqlite3')
    with transaction() as con:
        con.execute("INSERT INTO bots(id,bot_token,telegram_bot_id,bot_username,owner_id,actual_state) VALUES(1,'100000:FAKE',100000,'testbot',10,'RUNNING')")
        con.execute("INSERT INTO bots(id,bot_token,telegram_bot_id,bot_username,owner_id,actual_state) VALUES(2,'200000:FAKE',200000,'anotherbot',20,'RUNNING')")
        con.execute("INSERT INTO main_users(user_id) VALUES(10),(20)")


def query(uid=MAIN_ADMIN_ID, data='admin:back'):
    return NS(from_user=NS(id=uid), data=data, edit_message_text=AsyncMock(), answer=AsyncMock(), message=NS(chat_id=uid, message_id=11))


def event(uid=MAIN_ADMIN_ID, text='hello', entities=()):
    user = NS(id=uid, first_name='user', username=None, is_bot=False)
    message = NS(text=text, text_html=None, entities=entities, from_user=user, reply_text=AsyncMock(), reply_to_message=None)
    return NS(effective_user=user, effective_message=message)


def test_persistent_nonce_expires_and_consumes_once():
    nonce = put_session(10, 'owner_confirm', {'bot_id': 1})
    assert get_session(10, nonce)['state'] == 'owner_confirm'
    assert get_session(20, nonce) is None
    assert get_session(10, 'bad') is None
    consume_session(10, nonce)
    with pytest.raises(ValueError):
        consume_session(10, nonce)
    nonce = put_session(10, 'owner_confirm', {'bot_id': 1}, ttl=-1)
    assert get_session(10, nonce) is None


def test_owner_rechecked_after_transfer_and_admin_flag_not_bypass():
    nonce = put_session(10, 'owner_confirm', {'bot_id': 1})
    with transaction() as con:
        con.execute('UPDATE bots SET owner_id=20 WHERE id=1')
    with pytest.raises(PermissionError):
        validate_session_actor(get_session(10, nonce), 10)
    with pytest.raises(PermissionError):
        owner_bot(1, 10, platform=True)
    assert owner_bot(1, MAIN_ADMIN_ID, platform=True)['id'] == 1


def test_settings_preview_does_not_commit_and_duplicate_save_fails():
    handler = MainSettingsMixin()
    nonce = put_session(MAIN_ADMIN_ID, 'setting_input', {'admin': True, 'kind': 'text', 'key': 'welcome', 'field': 'text'})
    original = get_main_text('welcome')
    run(handler._settings_text(event(text='<b>literal</b>'), get_session(MAIN_ADMIN_ID, nonce)))
    assert get_main_text('welcome') == original
    draft = get_session(MAIN_ADMIN_ID)
    assert draft['state'] == 'setting_confirm'
    assert draft['data']['value'] == '&lt;b&gt;literal&lt;/b&gt;'
    q = query(data=f"settings_save:{draft['nonce']}")
    run(handler._settings_callback(q, NS()))
    assert get_main_text('welcome') == '&lt;b&gt;literal&lt;/b&gt;'
    with pytest.raises(ValueError):
        run(handler._settings_callback(q, NS()))


def test_setting_confirm_cannot_be_submitted_by_non_admin():
    nonce = put_session(10, 'setting_confirm', {'admin': True, 'kind': 'text', 'key': 'welcome', 'value': 'bad'})
    with pytest.raises(PermissionError):
        run(MainSettingsMixin()._settings_callback(query(10, f'settings_save:{nonce}'), NS()))


def test_color_only_saved_after_confirmation():
    handler = MainSettingsMixin()
    q = query()
    run(handler._show_color_picker(q, 'btn_add'))
    draft = get_session(MAIN_ADMIN_ID)
    original = get_main_button('btn_add')['color']
    run(handler._settings_callback(query(data=f"settings_color:{draft['nonce']}:danger"), NS()))
    assert get_main_button('btn_add')['color'] == original
    final = get_session(MAIN_ADMIN_ID)
    run(handler._settings_callback(query(data=f"settings_save:{final['nonce']}"), NS()))
    assert get_main_button('btn_add')['color'] == 'danger'


def test_button_emoji_preserves_utf16_offsets_and_plain_label():
    emoji = MessageEntity('custom_emoji', offset=2, length=2, custom_emoji_id='1234')
    nonce = put_session(MAIN_ADMIN_ID, 'setting_input', {'admin': True, 'kind': 'button', 'key': 'btn_add', 'field': 'text'})
    run(MainSettingsMixin()._settings_text(event(text='Hi😀!', entities=(emoji,)), get_session(MAIN_ADMIN_ID, nonce)))
    assert get_session(MAIN_ADMIN_ID)['data']['value'] == 'Hi[emoji:1234]!'


def test_quota_only_changes_after_preview_confirmation():
    nonce = put_session(MAIN_ADMIN_ID, 'setting_input', {'admin': True, 'kind': 'setting', 'key': 'free_bot_limit'})
    handler = MainSettingsMixin()
    with pytest.raises(ValueError):
        run(handler._settings_text(event(text='0'), get_session(MAIN_ADMIN_ID, nonce)))
    run(handler._settings_text(event(text='8'), get_session(MAIN_ADMIN_ID, nonce)))
    assert get_db().execute("SELECT value FROM settings WHERE key='free_bot_limit'").fetchone() is None
    draft = get_session(MAIN_ADMIN_ID)
    run(handler._settings_callback(query(data=f"settings_save:{draft['nonce']}"), NS()))
    assert get_db().execute("SELECT value FROM settings WHERE key='free_bot_limit'").fetchone()[0] == '8'
    assert get_db().execute('SELECT count(*) FROM bots').fetchone()[0] == 2


def test_two_party_transfer_revokes_old_sessions_and_admins():
    with transaction() as con:
        con.execute('INSERT INTO bot_admins(bot_id,admin_id) VALUES(1,99)')
        con.execute("INSERT INTO ui_sessions VALUES(1,99,'draft','{}','old',?)", (time.time() + 900,))
        con.execute('INSERT INTO conversations(bot_id,admin_id,current_user_id) VALUES(1,99,123)')
    token = request_transfer(1, 10, 20)
    assert get_bot(1)['owner_id'] == 10
    with pytest.raises(ValueError):
        accept_transfer(token, 99)
    assert accept_transfer(token, 20)['bot_id'] == 1
    assert get_bot(1)['owner_id'] == 20
    assert get_db().execute('SELECT admin_id FROM bot_admins WHERE bot_id=1').fetchone()[0] == 20
    assert not get_db().execute('SELECT 1 FROM conversations WHERE bot_id=1').fetchone()
    assert not get_db().execute('SELECT 1 FROM ui_sessions WHERE bot_id=1').fetchone()
    with pytest.raises(ValueError):
        accept_transfer(token, 20)


def test_owner_lifecycle_callback_only_prepares_confirmation():
    handler = MainActionsMixin()
    handler._delete_clone_bot = AsyncMock()
    q = query(10, 'bot_delete:1')
    run(handler._owner_callback(q, NS()))
    handler._delete_clone_bot.assert_not_awaited()
    assert get_session(10)['state'] == 'owner_confirm'
    with pytest.raises(PermissionError):
        run(handler._owner_callback(query(20, 'bot_delete:1'), NS()))


def test_admin_pages_reject_non_admin():
    with pytest.raises(PermissionError):
        run(MainAdminMixin()._admin_callback(query(10, 'admin:users:1'), NS()))


def test_timezone_and_time_transfer_are_distinct():
    handler = MainActionsMixin()
    run(handler._owner_callback(query(10, 'bot_timezone:1'), NS()))
    assert get_session(10)['state'] == 'timezone_input'
    run(handler._owner_callback(query(10, 'bot_transfer_time:1'), NS()))
    assert get_session(10)['state'] == 'timezone_input'  # list selection does not mutate entitlement


def test_managed_event_cannot_claim_foreign_owner():
    handler = ManagedMixin()
    handler._jobs_lock = asyncio.Lock()
    update = NS(update_id=100, to_dict=lambda: {'managed_bot': {'user': {'id': 20, 'is_bot': False}, 'bot': {'id': 100000, 'is_bot': True}}})
    with pytest.raises(ApplicationHandlerStop):
        run(handler.handle_managed_bot_update(update, NS(bot=NS(id=999999))))
    assert get_bot(1)['owner_id'] == 10
    assert not get_db().execute('SELECT 1 FROM managed_setup_jobs').fetchone()


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

def test_managed_pending_retries_transient_failure_and_survives_new_handler():
    with transaction() as con:
        con.execute("INSERT INTO managed_setup_jobs(telegram_bot_id,owner_id,update_id) VALUES(300000,10,10)")
    ctx = NS(bot=NS(send_message=AsyncMock()))
    first = ManagedMixin()
    first._jobs_lock = asyncio.Lock()
    first._configure_managed_bot = AsyncMock(side_effect=NetworkError('offline'))
    run(first.retry_managed_jobs(ctx))
    row = dict(get_db().execute('SELECT * FROM managed_setup_jobs').fetchone())
    assert row['state'] == 'pending' and row['attempts'] == 1 and row['next_retry'] > time.time()
    assert row['last_error'] == 'NetworkError'
    with transaction() as con:
        con.execute('UPDATE managed_setup_jobs SET next_retry=0')
    second = ManagedMixin()
    second._jobs_lock = asyncio.Lock()
    second._configure_managed_bot = AsyncMock(return_value=True)
    run(second.retry_managed_jobs(ctx))
    assert get_db().execute('SELECT state FROM managed_setup_jobs').fetchone()[0] == 'done'


def test_managed_stale_generation_or_disconnected_job_is_cancelled():
    with transaction() as con:
        con.execute("INSERT INTO managed_setup_jobs(telegram_bot_id,owner_id,update_id,generation) VALUES(100000,10,10,0)")
        con.execute("UPDATE bots SET desired_state='DISCONNECTED',generation=1 WHERE id=1")
    handler = ManagedMixin()
    handler._jobs_lock = asyncio.Lock()
    handler._configure_managed_bot = AsyncMock()
    run(handler.retry_managed_jobs(NS(bot=NS())))
    handler._configure_managed_bot.assert_not_awaited()
    assert get_db().execute('SELECT state FROM managed_setup_jobs').fetchone()[0] == 'cancelled'


def test_managed_new_bot_notifications_cannot_fake_start_success(monkeypatch):
    class FakeProbe:
        def __init__(self, token):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get_me(self):
            return NS(id=300000, username='thirdbot', first_name='Third')
    monkeypatch.setattr(managed, 'Bot', FakeProbe)
    handler = ManagedMixin()
    handler._managed_sync_lock = asyncio.Lock()
    handler.bot = NS(id=999999)
    handler._start_clone_bot = AsyncMock()
    notify = AsyncMock(side_effect=NetworkError('notification offline'))
    assert not run(handler._setup_new_bot(10, '300000:' + 'A' * 35, notify))
    row = dict(get_db().execute('SELECT * FROM bots WHERE telegram_bot_id=300000').fetchone())
    assert row['actual_state'] == 'STOPPED'
    assert row['status'] != 'active'


def test_main_handler_import_and_private_admin_entry():
    from relayapp.main_ui import MainBotHandlers
    handler = MainBotHandlers()
    update = event(10)
    update.effective_chat = NS(type='private')
    update.callback_query = None
    update.effective_message.chat_id = 10
    context = NS(bot=NS(id=999999))
    run(handler.cmd_admin(update, context))
    update.effective_message.reply_text.assert_not_awaited()
    update.effective_user.id = MAIN_ADMIN_ID
    update.effective_message.from_user.id = MAIN_ADMIN_ID
    run(handler.cmd_admin(update, context))
    update.effective_message.reply_text.assert_awaited_once()


def test_broadcast_confirmation_is_atomic_and_only_main_recipients(monkeypatch):
    from relayapp.main_broadcast import MainBroadcastMixin
    from relayapp.broadcast import broadcasts
    handler = MainBroadcastMixin()
    handler._show_main_job = AsyncMock()
    with transaction() as con:
        con.execute("INSERT INTO users(bot_id,user_id,username,first_name) VALUES(1,123,'client','Client')")
    nonce = put_session(MAIN_ADMIN_ID, 'main_broadcast_confirm', {'admin': True, 'payload': {'type': 'text', 'text': 'hello'}})
    q = query(data=f'main_broadcast_confirm:{nonce}')
    run(handler._main_broadcast_callback(q, NS()))
    assert get_session(MAIN_ADMIN_ID) is None
    rows = get_db().execute('SELECT user_id FROM broadcast_recipients').fetchall()
    assert {row[0] for row in rows} == {10, 20}
    assert get_db().execute('SELECT bot_id FROM broadcast_jobs').fetchone()[0] == 0
    with pytest.raises(ValueError):
        run(handler._main_broadcast_callback(q, NS()))
    assert get_db().execute('SELECT count(*) FROM broadcast_jobs').fetchone()[0] == 1
    nonce = put_session(MAIN_ADMIN_ID, 'main_broadcast_confirm', {'admin': True, 'payload': {'type': 'text', 'text': 'hello'}})
    original = broadcasts.create_in_transaction
    def fail(con, *args, **kwargs):
        original(con, *args, **kwargs)
        raise RuntimeError('forced failure')
    monkeypatch.setattr(broadcasts, 'create_in_transaction', fail)
    with pytest.raises(RuntimeError):
        run(handler._main_broadcast_callback(query(data=f'main_broadcast_confirm:{nonce}'), NS()))
    assert get_session(MAIN_ADMIN_ID, nonce)
    assert get_db().execute('SELECT count(*) FROM broadcast_jobs').fetchone()[0] == 1


def test_historical_paid_order_only_displays_and_never_grants(monkeypatch):
    from relayapp.main_payments import MainPaymentsMixin
    from relayapp.payments import create_order
    import relayapp.main_payments as payment_ui
    create_order('paid-old', 1, 10, '1m', 'one month', 5)
    with transaction() as con:
        con.execute("UPDATE orders SET status='paid' WHERE order_no='paid-old'")
    settle = AsyncMock()
    monkeypatch.setattr(payment_ui, 'settle_order', settle)
    handler = MainPaymentsMixin()
    handler._paid_display = AsyncMock()
    run(handler._payment_callback(query(10, 'vip_check:paid-old'), NS()))
    handler._paid_display.assert_awaited_once()
    assert settle.call_count == 0
    assert not get_db().execute('SELECT 1 FROM entitlement_grants').fetchone()


def test_payment_checks_owner_again_after_network_await(monkeypatch):
    from relayapp.main_payments import MainPaymentsMixin
    from relayapp.payments import create_order
    import relayapp.main_payments as payment_ui
    create_order('race-order', 1, 10, '1m', 'one month', 5)
    async def check(order_no):
        with transaction() as con:
            con.execute('UPDATE bots SET owner_id=20 WHERE id=1')
        return {'code': 200, 'data': {'status': 1, 'amount': 5, 'currency': 'USDT'}}
    monkeypatch.setattr(payment_ui, 'get_okpay_client', lambda: NS(check_deposit=check))
    with pytest.raises(PermissionError):
        run(MainPaymentsMixin()._payment_callback(query(10, 'vip_check:race-order'), NS()))
    assert not get_db().execute('SELECT 1 FROM entitlement_grants').fetchone()


def test_paced_object_degrades_emoji_only_for_permission_error(monkeypatch):
    from telegram.error import BadRequest, NetworkError
    from relayapp.main_sessions import PacedObject
    import relayapp.formatting as formatting
    calls = []
    async def paced(bot, chat_id, method, **kwargs):
        calls.append(chat_id)
        return await method(chat_id=chat_id, **kwargs)
    monkeypatch.setattr(formatting, 'api_call', paced)
    raw = NS(chat_id=10, reply_text=AsyncMock(side_effect=[BadRequest('custom emoji are not allowed'), True]))
    run(PacedObject(raw, NS(id=999)).reply_text('<b>A</b><tg-emoji emoji-id="123">😀</tg-emoji>'))
    assert calls == [10, 10]
    assert raw.reply_text.await_args.args[0] == '<b>A</b>😀'
    raw.reply_text = AsyncMock(side_effect=NetworkError('uncertain'))
    with pytest.raises(NetworkError):
        run(PacedObject(raw, NS(id=999)).reply_text('hello'))
    assert raw.reply_text.await_count == 1


def test_managed_rotation_rebinds_own_generation_for_startup_retry(monkeypatch):
    class Probe:
        def __init__(self, token):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get_me(self):
            return NS(id=100000, username='testbot', first_name='Test')
    monkeypatch.setattr(managed, 'Bot', Probe)
    with transaction() as con:
        con.execute("INSERT INTO managed_setup_jobs(telegram_bot_id,owner_id,update_id,generation) VALUES(100000,10,10,0)")
    token = '100000:' + 'A' * 35
    handler = ManagedMixin()
    handler._jobs_lock = asyncio.Lock()
    handler._managed_sync_lock = asyncio.Lock()
    handler.bot = NS(id=999999)
    async def rotate(bot_id, new_token, actor_id=None):
        assert actor_id == 10
        with transaction() as con:
            con.execute("UPDATE bots SET bot_token=?,generation=generation+1,actual_state='ERROR' WHERE id=?", (new_token, bot_id))
            con.execute("UPDATE managed_setup_jobs SET state='cancelled' WHERE telegram_bot_id=100000")
        raise NetworkError('startup unavailable')
    handler._rotate_clone_token = rotate
    context = NS(bot=NS(id=999999, get_managed_bot_token=AsyncMock(return_value=token), send_message=AsyncMock(return_value=NS(message_id=1))))
    run(handler.retry_managed_jobs(context))
    job = dict(get_db().execute('SELECT * FROM managed_setup_jobs').fetchone())
    assert job['state'] == 'pending' and job['generation'] == 1 and job['attempts'] == 1
    assert get_bot(1)['actual_state'] == 'ERROR'


def test_paced_entry_admin_return_cancels_previous_confirm():
    from relayapp.main_ui import MainBotHandlers
    nonce = put_session(MAIN_ADMIN_ID, 'setting_confirm', {'admin': True, 'kind': 'text', 'key': 'welcome', 'value': 'stale'})
    update = event(MAIN_ADMIN_ID)
    update.effective_chat = NS(type='private')
    update.effective_message.chat_id = MAIN_ADMIN_ID
    update.callback_query = query(data='admin:texts')
    run(MainBotHandlers().callback(update, NS(bot=NS(id=888888))))
    assert get_session(MAIN_ADMIN_ID, nonce) is None

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
