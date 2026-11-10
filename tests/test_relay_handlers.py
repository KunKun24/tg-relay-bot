# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""No polling, no tokens, no production DB: handler regressions against fakes."""
import asyncio
import json
import time
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, NetworkError

from relayapp.database import init_db, get_db, transaction
from relayapp.clients import add_user, get_user, get_conversation, set_conversation, is_blocked
from relayapp.configuration import set_setting
from relayapp.relay import RelayBotHandlers
import relayapp.relay as relay


@pytest.fixture
def handler(tmp_path, monkeypatch):
    init_db(tmp_path / 'isolated.sqlite3')
    with transaction() as db:
        db.execute("INSERT INTO bots(id,bot_token,owner_id,version,status) VALUES(1,'100:FAKE',10,'高级版','active')")
        db.execute("INSERT INTO bots(id,bot_token,owner_id,version,status) VALUES(2,'200:FAKE',20,'高级版','active')")
        db.execute('INSERT INTO bot_admins(bot_id,admin_id) VALUES(1,11)')
    async def call(bot, chat_id, method, **kwargs):
        return await (method if callable(method) else getattr(bot, method))(chat_id=chat_id, **kwargs)
    monkeypatch.setattr(relay, 'api_call', call)
    monkeypatch.setattr('relayapp.formatting.api_call', call)
    return RelayBotHandlers(1)


def event(uid=100, text='hello', mid=50, chat_id=None, reply=None):
    user = NS(id=uid, first_name=f'U{uid}', username=None)
    message = NS(text=text, caption=None, entities=(), caption_entities=(), chat=NS(id=chat_id or uid), message_id=mid, reply_to_message=reply, from_user=user, reply_text=AsyncMock())
    return NS(effective_user=user, effective_message=message, message=message)


def context():
    bot = NS(id=100, copy_message=AsyncMock(return_value=NS(message_id=500)), send_message=AsyncMock(return_value=NS(message_id=501)), get_chat_member=AsyncMock(return_value=NS(status='member')), get_chat=AsyncMock(return_value=NS(id=-100, title='Group', type='supergroup')))
    return NS(bot=bot)


def run(awaitable):
    return asyncio.run(awaitable)


def test_gate_fail_closed_and_revokes_old_verified(handler):
    add_user(1, 100, '', 'u', verified=1)
    with transaction() as db:
        db.execute("UPDATE bots SET channel_id='@required' WHERE id=1")
    ctx = context()
    ctx.bot.get_chat_member.side_effect = NetworkError('offline')
    assert not run(handler._gate(event(), ctx))
    assert get_user(1, 100)['verified'] == 0
    assert not handler._pending()
    ctx.bot.copy_message.assert_not_awaited()


def test_gate_configuration_change_and_short_cache(handler):
    with transaction() as db:
        db.execute("UPDATE bots SET channel_id='@required' WHERE id=1")
    ctx = context()
    assert run(handler._gate(event(), ctx))
    assert run(handler._gate(event(), ctx))
    assert ctx.bot.get_chat_member.await_count == 1
    set_setting(1, 'verification_revision', 'new')
    ctx.bot.get_chat_member.return_value = NS(status='left')
    assert not run(handler._gate(event(), ctx))
    assert ctx.bot.get_chat_member.await_count == 2


@pytest.mark.parametrize('method', ['cmd_start', 'cmd_admin', 'cmd_users', 'cmd_clear', 'handle_private_message'])
def test_all_user_entries_enforce_gate(handler, method):
    with transaction() as db:
        db.execute("UPDATE bots SET channel_id='@required' WHERE id=1")
    ctx = context()
    ctx.bot.get_chat_member.return_value = NS(status='left')
    run(getattr(handler, method)(event(), ctx))
    ctx.bot.copy_message.assert_not_awaited()
    assert not handler._pending()


def test_dynamic_removed_admin_cannot_reply(handler):
    add_user(1, 100, '', 'u')
    handler._save_route(11, 33, 100, 88)
    with transaction() as db:
        db.execute('DELETE FROM bot_admins WHERE bot_id=1 AND admin_id=11')
    ctx = context()
    run(handler.handle_admin_message(event(11, reply=NS(message_id=33)), ctx))
    ctx.bot.copy_message.assert_not_awaited()


def test_scoped_routes_and_no_forward_origin_guess(handler):
    add_user(1, 100, '', 'u')
    handler._save_route(10, 33, 100, 88)
    handler._save_route(11, 33, 101, 89)
    assert handler._route(10, 33) == 100
    assert handler._route(11, 33) == 101
    assert RelayBotHandlers(2)._route(10, 33) is None
    ctx = context()
    reply = NS(message_id=33, forward_origin=NS(sender_user=NS(id=100)))
    run(handler.handle_admin_message(event(10, chat_id=99, reply=reply), ctx))
    ctx.bot.copy_message.assert_not_awaited()


def test_independent_conversation_and_clear(handler):
    add_user(1, 100, '', 'a')
    add_user(1, 101, '', 'b')
    set_conversation(1, 10, 100)
    set_conversation(1, 11, 101)
    handler._draft(10, 'payload', {'kind': 'welcome'})
    handler._draft(11, 'payload', {'kind': 'welcome'})
    run(handler.cmd_clear(event(10), context()))
    assert get_conversation(1, 10) is None
    assert get_conversation(1, 11)['current_user_id'] == 101
    assert handler._session(10) is None
    assert handler._session(11)


@pytest.mark.parametrize('error', [NetworkError('unknown'), BadRequest('cannot copy')])
def test_failed_reply_no_success_accounting(handler, error):
    add_user(1, 100, '', 'u')
    with transaction() as db:
        db.execute('INSERT INTO client_cases(bot_id,user_id,last_inbound_at) VALUES(1,100,?)', (time.time(),))
    ctx = context()
    ctx.bot.copy_message.side_effect = error
    run(handler._reply_customer(event(10), ctx, 100))
    assert get_db().execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    assert handler._case(100)['last_outbound_at'] is None
    assert len(handler._pending()) == 1
    assert ctx.bot.copy_message.await_count == 1
    unknown = get_db().execute("SELECT count(*) FROM audit_logs WHERE action='outbound_delivery_unknown'").fetchone()[0]
    assert unknown == (0 if isinstance(error, BadRequest) else 1)


def test_copy_success_records_exact_message_and_pending(handler, monkeypatch):
    add_user(1, 100, '', 'u')
    set_setting(1, 'visitor_notify', '0')
    monkeypatch.setattr(relay, 'should_send_welcome', lambda *a: False)
    ctx = context()
    ctx.bot.copy_message.side_effect = [NS(message_id=700), NS(message_id=701)]
    run(handler._customer_message(event(), ctx))
    assert handler._route(10, 700) == 100
    assert handler._route(11, 701) == 100
    assert len(handler._pending()) == 1
    run(handler._reply_customer(event(10), context(), 100))
    assert not handler._pending()


def test_nonce_single_use_and_transaction_rollback(handler):
    draft = {'kind': 'routing', 'mode': 'balanced'}
    nonce = handler._draft(10, 'confirm', draft)
    handler._consume(10, nonce, lambda db, d: handler._apply_config(db, 10, d))
    with pytest.raises(ValueError, match='已过期或已处理'):
        handler._consume(10, nonce, lambda db, d: handler._apply_config(db, 10, d))
    nonce = handler._draft(10, 'confirm', draft)
    def fail(db, data):
        db.execute("INSERT INTO settings VALUES(1,'rollback_test','1')")
        raise ValueError('simulate crash')
    with pytest.raises(ValueError, match='simulate crash'):
        handler._consume(10, nonce, fail)
    assert handler._session(10)['nonce'] == nonce
    assert get_db().execute("SELECT 1 FROM settings WHERE key='rollback_test'").fetchone() is None
    assert RelayBotHandlers(2)._session(10) is None


def test_nonce_expiry_and_removed_admin_on_submit(handler):
    nonce = handler._draft(11, 'confirm', {'kind': 'routing', 'mode': 'balanced'})
    with transaction() as db:
        db.execute('DELETE FROM bot_admins WHERE bot_id=1 AND admin_id=11')
    with pytest.raises(ValueError, match='无权'):
        handler._consume(11, nonce, lambda db, d: handler._apply_config(db, 11, d))
    assert handler._session(11)
    with transaction() as db:
        db.execute('UPDATE ui_sessions SET expires_at=?', (time.time()-1,))
    assert handler._session(11) is None


@pytest.mark.parametrize('seconds', [86400, 604800, 2592000, None])
def test_mute_durations_and_automatic_expiry(handler, seconds):
    add_user(1, 100, '', 'u')
    with transaction() as db:
        handler._apply_case(db, 10, {'op': 'mute', 'user_id': 100, 'seconds': seconds})
    row = get_db().execute('SELECT expires_at FROM blacklist WHERE bot_id=1').fetchone()
    assert is_blocked(1, 100)
    if seconds is None:
        assert row[0] is None
    else:
        assert row[0] == pytest.approx(time.time()+seconds, abs=2)
        with transaction() as db:
            db.execute('UPDATE blacklist SET expires_at=? WHERE bot_id=1', (time.time()-1,))
        assert not is_blocked(1, 100)
        assert get_user(1, 100)['blocked'] == 0
    assert not is_blocked(2, 100)


def test_case_claim_transfer_close_and_notes(handler):
    add_user(1, 100, '', 'u')
    with transaction() as db:
        handler._apply_case(db, 10, {'op': 'claim', 'user_id': 100})
    with pytest.raises(ValueError, match='其他客服'):
        with transaction() as db:
            handler._apply_case(db, 11, {'op': 'claim', 'user_id': 100})
    with transaction() as db:
        handler._apply_case(db, 10, {'op': 'transfer', 'user_id': 100, 'target': 11})
        handler._apply_case(db, 10, {'op': 'note', 'user_id': 100, 'notes': 'VIP'})
        handler._apply_case(db, 10, {'op': 'close', 'user_id': 100})
    assert handler._case(100)['assigned_admin_id'] == 11
    assert handler._case(100)['notes'] == 'VIP'
    assert handler._case(100)['state'] == 'CLOSED'


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

def test_group_rights_fail_closed_and_nonstaff_ignored(handler):
    ctx = context()
    ctx.bot.get_chat_member.side_effect = [NS(status='administrator'), NS(status='member')]
    with pytest.raises(ValueError, match='管理员'):
        run(handler._check_group(ctx, -100, 10))
    with transaction() as db:
        db.execute("INSERT INTO group_bindings(bot_id,chat_id,title,kind,staff_group) VALUES(1,-100,'G','supergroup',0)")
    handler._save_route(-100, 20, 100, 1)
    run(handler.handle_group_message(event(10, chat_id=-100, reply=NS(message_id=20)), context()))
    assert not handler._pending()


def test_welcome_and_auto_reply_keep_inline_and_bottom(handler, monkeypatch):
    calls = []
    async def capture(bot, uid, payload, reply_markup=None):
        calls.append((payload, reply_markup))
    monkeypatch.setattr(relay, 'send_payload', capture)
    monkeypatch.setattr(relay, 'build_reply_keyboard', lambda *a: 'BOTTOM')
    payload = {'type': 'text', 'text': 'hello', 'entities': [], 'buttons': [[{'text': 'link', 'url': 'https://example.com'}]]}
    run(handler.send_auto_reply(context(), 100, {'payload': json.dumps(payload)}))
    assert calls[0] == (payload, None)
    assert calls[1][1] == 'BOTTOM'


def test_filter_regex_and_bot_isolation(handler):
    add_user(1, 100, '', 'u')
    with transaction() as db:
        db.execute("INSERT INTO filter_rules(bot_id,pattern,mode,action,duration_seconds) VALUES(1,'spam','contains','mute',3600)")
    assert run(handler._filter_message(event(text='SPAM'), context(), 'SPAM'))
    assert is_blocked(1, 100)
    assert not is_blocked(2, 100)
    assert not run(RelayBotHandlers(2)._filter_message(event(), context(), 'SPAM'))


def query_event(data, actor=10):
    query = NS(data=data, from_user=NS(id=actor), message=NS(chat=NS(id=actor), message_id=90), answer=AsyncMock(), edit_message_text=AsyncMock())
    return NS(callback_query=query), query


@pytest.mark.parametrize('data', ['cad:back_panel', 'cad:cad_clients', 'cad:cad_stats', 'list:welcome', 'list:ar', 'list:command', 'list:filter', 'menu:keyboard', 'menu:visitor', 'menu:admins', 'menu:verification', 'menu:routing', 'menu:blacklist', 'menu:groups', 'menu:broadcast'])
def test_every_admin_menu_opens(handler, data):
    update, query = query_event(data)
    run(handler.callback_handler(update, context()))
    query.edit_message_text.assert_awaited()
    text = query.edit_message_text.await_args.args[0]
    assert '无效' not in text and '无权' not in text


def test_config_json_cannot_override_operation(handler):
    handler._draft(10, 'json', {'kind': 'routing', 'op': 'save'})
    update = event(10, text='{"kind":"admins","add":[999]}')
    run(handler._config_input(update, context()))
    assert handler._session(10)['state'] == 'json'
    assert not handler._admin(999)
    assert '内部操作字段' in update.effective_message.reply_text.await_args.args[0]


def test_resource_draft_not_live_until_confirmation(handler):
    update, query = query_event('cfg:ar:add')
    ctx = context()
    run(handler.callback_handler(update, ctx))
    assert get_db().execute('SELECT count(*) FROM auto_replies').fetchone()[0] == 0
    run(handler._config_input(event(10, 'exact|hello'), ctx))
    assert handler._session(10)['state'] == 'payload'
    run(handler._config_input(event(10, 'answer'), ctx))
    assert get_db().execute('SELECT count(*) FROM auto_replies').fetchone()[0] == 0
    nonce = handler._session(10)['nonce']
    update, query = query_event(f'cfg:confirm:{nonce}')
    run(handler.callback_handler(update, ctx))
    row = dict(get_db().execute('SELECT * FROM auto_replies').fetchone())
    assert row['enabled'] == 1 and row['keyword'] == 'hello'
    assert json.loads(row['payload'])['text'] == 'answer'
    run(handler.callback_handler(update, ctx))
    assert get_db().execute('SELECT count(*) FROM auto_replies').fetchone()[0] == 1


def test_broadcast_confirmation_creates_once(handler):
    add_user(1, 100, '', 'u')
    nonce = handler._draft(10, 'confirm', {'kind': 'broadcast', 'op': 'save', 'payload': {'type': 'text', 'text': 'notice'}})
    update, query = query_event(f'cfg:confirm:{nonce}')
    run(handler.callback_handler(update, context()))
    assert get_db().execute('SELECT count(*) FROM broadcast_jobs').fetchone()[0] == 1
    assert get_db().execute('SELECT count(*) FROM broadcast_recipients').fetchone()[0] == 1
    run(handler.callback_handler(update, context()))
    assert get_db().execute('SELECT count(*) FROM broadcast_jobs').fetchone()[0] == 1


def test_group_reply_requires_current_admin_and_scoped_route(handler):
    add_user(1, 100, '', 'u')
    with transaction() as db:
        db.execute("INSERT INTO group_bindings(bot_id,chat_id,title,kind,staff_group) VALUES(1,-100,'G','supergroup',1)")
    handler._save_route(-100, 20, 100, 1)
    ctx = context()
    run(handler.handle_group_message(event(999, chat_id=-100, reply=NS(message_id=20)), ctx))
    ctx.bot.copy_message.assert_not_awaited()
    run(handler.handle_group_message(event(10, chat_id=-100, reply=NS(message_id=20)), ctx))
    ctx.bot.copy_message.assert_awaited_once()
    assert ctx.bot.copy_message.await_args.kwargs['chat_id'] == 100


def test_group_welcome_only_bound_chat(handler, monkeypatch):
    import relayapp.clone_groups as groups
    send = AsyncMock()
    monkeypatch.setattr(groups, 'send_payload', send)
    with transaction() as db:
        db.execute("INSERT INTO group_bindings(bot_id,chat_id,title,kind,welcome_enabled,welcome_payload) VALUES(1,-100,'G','supergroup',1,?)", (json.dumps({'type': 'text', 'text': 'welcome'}),))
    update = event(chat_id=-100)
    update.effective_message.new_chat_members = [NS(id=123)]
    run(handler.handle_new_members(update, context()))
    assert send.await_args.args[1] == -100
    assert send.await_count == 1
    update.effective_message.chat.id = -101
    run(handler.handle_new_members(update, context()))
    assert send.await_count == 1


def test_bot_admin_removal_disables_group_binding(handler):
    with transaction() as db:
        db.execute("INSERT INTO group_bindings(bot_id,chat_id,title,kind) VALUES(1,-100,'G','supergroup')")
    run(handler.handle_chat_member(NS(my_chat_member=NS(chat=NS(id=-100), new_chat_member=NS(status='left'))), context()))
    assert handler._row('SELECT enabled FROM group_bindings WHERE bot_id=? AND chat_id=?', (-100,))['enabled'] == 0


def test_welcome_order_and_trial_only_free(handler, monkeypatch):
    calls = []
    async def capture(bot, uid, payload, reply_markup=None):
        calls.append((payload['text'], reply_markup))
    monkeypatch.setattr(relay, 'send_payload', capture)
    monkeypatch.setattr(relay, 'build_reply_keyboard', lambda *a: 'BOTTOM')
    monkeypatch.setattr(relay, 'get_main_text', lambda *a: 'TRIAL')
    add_user(1, 100, '', 'u')
    with transaction() as db:
        db.execute("INSERT INTO welcome_messages(bot_id,content_type,content_text,sort_order) VALUES(1,'text','second',2)")
        db.execute("INSERT INTO welcome_messages(bot_id,content_type,content_text,sort_order) VALUES(1,'text','first',1)")
    run(handler.send_welcome_to_user(context(), 100, force=True))
    assert calls == [('first', None), ('second', 'BOTTOM')]
    calls.clear()
    with transaction() as db:
        db.execute("UPDATE bots SET version='普通版' WHERE id=1")
    run(handler.send_welcome_to_user(context(), 100, force=True))
    assert calls == [('first', None), ('second', None), ('TRIAL', 'BOTTOM')]


def test_admin_revoked_while_outbound_waits_is_not_sent(handler, monkeypatch):
    add_user(1, 100, '', 'u')
    set_conversation(1, 11, 100)
    async def delayed(bot, chat_id, method, **kwargs):
        with transaction() as db:
            db.execute('DELETE FROM bot_admins WHERE bot_id=1 AND admin_id=11')
        return await method(chat_id=chat_id, **kwargs)
    monkeypatch.setattr(relay, 'api_call', delayed)
    ctx = context()
    run(handler.handle_admin_message(event(11), ctx))
    ctx.bot.copy_message.assert_not_awaited()
    assert get_db().execute('SELECT count(*) FROM messages').fetchone()[0] == 0


def test_failed_automation_does_not_drop_customer_inbound(handler, monkeypatch):
    monkeypatch.setattr(handler, 'send_welcome_to_user', AsyncMock(side_effect=BadRequest('bad old welcome')))
    ctx = context()
    run(handler.handle_private_message(event(), ctx))
    assert ctx.bot.copy_message.await_count == 2
    assert handler._pending()[0]['user_id'] == 100
    assert get_db().execute("SELECT count(*) FROM audit_logs WHERE action='customer_automation_failed'").fetchone()[0] == 1


def test_auto_reply_independent_keyboard_and_legacy_list(handler, monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(relay, 'send_payload', send)
    monkeypatch.setattr(relay, 'build_reply_keyboard', lambda *a: None)
    run(handler.send_auto_reply(context(), 100, {'reply_type': 'text', 'reply_text': 'ok', 'reply_kb': json.dumps([{'text': '咨询', 'color': 'primary', 'emoji_id': '123'}])}))
    keyboard = send.await_args.kwargs['reply_markup'].keyboard
    assert keyboard[0][0].text == '咨询'
    assert keyboard[0][0].style == 'primary'
    assert keyboard[0][0].icon_custom_emoji_id == '123'


def test_group_rights_api_failure_is_clear_and_does_not_bind(handler):
    ctx = context()
    ctx.bot.get_chat_member.side_effect = NetworkError('offline')
    with pytest.raises(ValueError, match='无法确认'):
        run(handler._check_group(ctx, -100, 10))
    assert not handler._rows('SELECT * FROM group_bindings WHERE bot_id=?')


def test_ui_send_edit_and_answer_share_limiter(handler, monkeypatch):
    calls = []
    async def paced(bot, chat_id, method, **kwargs):
        calls.append(chat_id)
        return await method(chat_id=chat_id, **kwargs)
    monkeypatch.setattr('relayapp.formatting.api_call', paced)
    run(handler.cmd_admin(event(10), context()))
    update, query = query_event('cad:back_panel')
    run(handler.callback_handler(update, context()))
    assert calls == [10, 10, 10]


def test_group_confirmation_rechecks_both_admins(handler):
    ctx = context()
    ctx.bot.get_chat_member.return_value = NS(status='member')
    nonce = handler._draft(10, 'confirm', {'kind': 'group', 'op': 'bind', 'chat_id': -100, 'title': 'G', 'chat_kind': 'supergroup'})
    update, query = query_event(f'cfg:confirm:{nonce}')
    run(handler.callback_handler(update, ctx))
    assert not handler._rows('SELECT * FROM group_bindings WHERE bot_id=?')
    assert handler._session(10)['nonce'] == nonce
    assert '管理员' in query.edit_message_text.await_args.args[0]


def test_inbound_wait_does_not_send_to_revoked_admin(handler, monkeypatch):
    async def delayed(bot, chat_id, method, **kwargs):
        with transaction() as db:
            db.execute('DELETE FROM bot_admins WHERE bot_id=1 AND admin_id=11')
        return await method(chat_id=chat_id, **kwargs)
    monkeypatch.setattr(relay, 'api_call', delayed)
    ctx = context()
    with pytest.raises(relay.Forbidden):
        run(handler._staff_send(ctx.bot, 11, 'send_message', text='private client data'))
    ctx.bot.send_message.assert_not_awaited()

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
