# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Clone-scoped SQL state and single-use configuration drafts."""
from __future__ import annotations

import json
import secrets
import time
from functools import wraps
from .common import get_db, transaction


class _PacedObject:
    def __init__(self, original, bot, guard=None):
        self._original, self._bot, self._guard = original, bot, guard

    def __getattr__(self, name):
        value = getattr(self._original, name)
        if name not in ('reply_text', 'edit_message_text', 'answer'):
            return value
        async def call(*args, **kwargs):
            from .formatting import api_call
            message = getattr(self._original, 'message', self._original)
            chat_id = message.chat.id
            async def bound_call(chat_id, **unused):
                if self._guard and not self._guard():
                    return None
                return await value(*args, **kwargs)
            return await api_call(self._bot, chat_id, bound_call)
        return call


class _PacedUpdate:
    def __init__(self, original, bot, handler):
        self._original = original
        message = getattr(original, 'effective_message', None)
        query = getattr(original, 'callback_query', None)
        actor = getattr(query, 'from_user', None) or getattr(original, 'effective_user', None)
        guard = (lambda: handler._admin(actor.id)) if actor and handler._admin(actor.id) else None
        self.effective_message = _PacedObject(message, bot, guard) if message else None
        self.callback_query = _PacedObject(query, bot, guard) if query else None

    def __getattr__(self, name):
        return getattr(self._original, name)


def paced_entry(method):
    @wraps(method)
    async def wrapped(self, update, context, *args, **kwargs):
        if not isinstance(update, _PacedUpdate):
            update = _PacedUpdate(update, context.bot, self)
        return await method(self, update, context, *args, **kwargs)
    return wrapped


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

class CloneStateMixin:
    def _rows(self, sql, args=()):
        return [dict(row) for row in get_db().execute(sql, (self.bot_id, *args)).fetchall()]

    def _row(self, sql, args=()):
        rows = self._rows(sql, args)
        return rows[0] if rows else None

    def _write(self, sql, args=()):
        with transaction() as db:
            return db.execute(sql, (self.bot_id, *args)).rowcount

    def _draft(self, actor, state, data=None):
        nonce = secrets.token_hex(10)
        self._write('INSERT OR REPLACE INTO ui_sessions(bot_id,user_id,state,data,nonce,expires_at) VALUES(?,?,?,?,?,?)',
                    (actor, state, json.dumps(data or {}, ensure_ascii=False), nonce, time.time() + 900))
        return nonce

    def _session(self, actor):
        row = self._row('SELECT * FROM ui_sessions WHERE bot_id=? AND user_id=? AND expires_at>?', (actor, time.time()))
        if row:
            row['data'] = json.loads(row['data'])
        return row

    def _cancel(self, actor):
        self._write('DELETE FROM ui_sessions WHERE bot_id=? AND user_id=?', (actor,))

    def _consume(self, actor, nonce, apply):
        # Mutation and nonce consumption commit together: double clicks cannot apply twice.
        with transaction() as db:
            row = db.execute("SELECT * FROM ui_sessions WHERE bot_id=? AND user_id=? AND nonce=? AND state='confirm' AND expires_at>?",
                             (self.bot_id, actor, nonce, time.time())).fetchone()
            if not row:
                raise ValueError('确认已过期或已处理')
            result = apply(db, json.loads(row['data']))
            db.execute('DELETE FROM ui_sessions WHERE bot_id=? AND user_id=? AND nonce=?', (self.bot_id, actor, nonce))
            return result

    def _audit(self, actor, action, detail=None):
        self._write('INSERT INTO audit_logs(bot_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)',
                    (actor, action, json.dumps(detail or {}, ensure_ascii=False), time.time()))

    def _case(self, uid):
        return self._row('SELECT * FROM client_cases WHERE bot_id=? AND user_id=?', (uid,))

    def _pending(self):
        return self._rows("SELECT c.*,u.first_name,u.username FROM client_cases c JOIN users u ON u.bot_id=c.bot_id AND u.user_id=c.user_id WHERE c.bot_id=? AND c.state='OPEN' AND c.last_inbound_at>COALESCE(c.last_outbound_at,0) ORDER BY c.last_inbound_at")

    def _route(self, chat_id, message_id):
        row = self._row('SELECT user_id FROM relay_routes WHERE bot_id=? AND admin_chat_id=? AND admin_message_id=?', (chat_id, message_id))
        return row['user_id'] if row else None

    def _save_route(self, chat_id, message_id, uid, original):
        self._write('INSERT OR REPLACE INTO relay_routes(bot_id,admin_chat_id,admin_message_id,user_id,original_message_id,created_at) VALUES(?,?,?,?,?,?)',
                    (chat_id, message_id, uid, original, time.time()))

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
