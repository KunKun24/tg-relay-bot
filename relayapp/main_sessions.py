# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Persistent expiring main-platform interactions."""
from __future__ import annotations

import json
import secrets
import time
from telegram.error import BadRequest
from .database import get_db, transaction
from .bots import get_bot
from .config import MAIN_ADMIN_ID

SESSION_TTL = 15 * 60


def owner_bot(bot_id, actor_id, *, platform=False):
    bot = get_bot(int(bot_id))
    if not bot or bot.get("deleted_at") or bot.get("desired_state") == "DELETED":
        raise ValueError("机器人不存在或已删除")
    if int(bot["owner_id"]) != int(actor_id) and not (platform and int(actor_id) == MAIN_ADMIN_ID):
        raise PermissionError("无权操作")
    return bot


def put_session(user_id, state, data=None, ttl=SESSION_TTL):
    nonce = secrets.token_hex(8)
    get_db().execute(
        "INSERT OR REPLACE INTO ui_sessions(bot_id,user_id,state,data,nonce,expires_at) VALUES(0,?,?,?,?,?)",
        (int(user_id), state, json.dumps(data or {}, ensure_ascii=False), nonce, time.time() + ttl))
    get_db().commit()
    return nonce


def clear_session(user_id):
    get_db().execute("DELETE FROM ui_sessions WHERE bot_id=0 AND user_id=?", (int(user_id),))
    get_db().commit()


def get_session(user_id, nonce=None):
    row = get_db().execute("SELECT * FROM ui_sessions WHERE bot_id=0 AND user_id=?", (int(user_id),)).fetchone()
    if row is None:
        return None
    result = dict(row)
    if result["expires_at"] <= time.time():
        return None
    if nonce is not None and not secrets.compare_digest(str(result["nonce"]), str(nonce)):
        return None
    result["data"] = json.loads(result["data"] or "{}")
    return result


def validate_session_actor(session, actor_id):
    if not session or int(session["user_id"]) != int(actor_id):
        raise ValueError("操作已过期，请重新打开菜单")
    data = session["data"]
    if data.get("admin") and int(actor_id) != MAIN_ADMIN_ID:
        raise PermissionError("无权操作")
    if data.get("bot_id") is not None:
        owner_bot(data["bot_id"], actor_id, platform=bool(data.get("platform")))
    return data


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def consume_session(user_id, nonce):
    with transaction() as con:
        session = get_session(user_id, nonce)
        validate_session_actor(session, user_id)
        changed = con.execute(
            "DELETE FROM ui_sessions WHERE bot_id=0 AND user_id=? AND nonce=? AND expires_at>?",
            (int(user_id), nonce, time.time())).rowcount
        if changed != 1:
            raise ValueError("操作已过期或已提交")
        return session


class PacedObject:
    """Delegate Telegram objects while pacing bound UI send/edit methods."""
    def __init__(self, original, bot):
        self._original, self._bot = original, bot

    def __getattr__(self, name):
        return getattr(self._original, name)

    async def _call(self, method, *args, **kwargs):
        from .formatting import api_call
        original = self._original
        message = getattr(original, "message", original)
        chat_id = message.chat_id
        async def bound_call(chat_id, **unused):
            return await getattr(original, method)(*args, **kwargs)
        try:
            return await api_call(self._bot, chat_id, bound_call)
        except BadRequest as exc:
            from .formatting import _emoji_permission_error, _strip_icons
            if not _emoji_permission_error(exc):
                raise
            import re
            changed = False
            if args and isinstance(args[0], str):
                stripped = re.sub(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', r'\1', args[0], flags=re.S)
                changed = stripped != args[0]
                args = (stripped, *args[1:])
            if isinstance(kwargs.get("text"), str):
                stripped = re.sub(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', r'\1', kwargs["text"], flags=re.S)
                changed = changed or stripped != kwargs["text"]
                kwargs["text"] = stripped
            if kwargs.get("reply_markup") is not None:
                kwargs["reply_markup"], removed = _strip_icons(kwargs["reply_markup"])
                changed = changed or removed
            if not changed:
                raise
            return await api_call(self._bot, chat_id, bound_call)

    async def reply_text(self, *args, **kwargs):
        return await self._call("reply_text", *args, **kwargs)

    async def edit_message_text(self, *args, **kwargs):
        return await self._call("edit_message_text", *args, **kwargs)

    async def answer(self, *args, **kwargs):
        return await self._call("answer", *args, **kwargs)


class PacedUpdate:
    def __init__(self, original, bot):
        self._original = original
        self.effective_message = PacedObject(original.effective_message, bot) if original.effective_message else None
        self.callback_query = PacedObject(original.callback_query, bot) if original.callback_query else None

    def __getattr__(self, name):
        return getattr(self._original, name)


class MessageQuery:
    def __init__(self, message):
        self.message = message
        self.from_user = message.from_user

    async def edit_message_text(self, *args, **kwargs):
        return await self.message.reply_text(*args, **kwargs)

    async def answer(self, *args, **kwargs):
        return None

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
