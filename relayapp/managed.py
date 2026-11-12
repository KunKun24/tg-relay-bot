# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Official managed events and identity-safe idempotent creation."""
from __future__ import annotations

import logging
import re
import time
from types import SimpleNamespace
from telegram import Bot
from telegram.error import Forbidden, InvalidToken, RetryAfter
from telegram.ext import ApplicationHandlerStop
from .bots import get_bot, get_bots_by_owner, touch_main_user
from .configuration import get_main_text, get_setting
from .database import get_db, transaction
from .formatting import render_emoji_html, send_payload

logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{30,}$")


class ManagedMixin:
    async def _notify_setup(self, send_message, text, **kwargs):
        try:
            return await send_message(text, **kwargs)
        except Exception as exc:
            logger.warning("配置通知未送达 error=%s", type(exc).__name__)
            return None

    async def _send_main_user_message(self, context, user_id, text, **kwargs):
        legacy = kwargs.pop("parse_mode", None) == "HTML"
        return await send_payload(context.bot, user_id, {"type": "text", "text": text, "legacy_html": legacy}, **kwargs)

    def _managed_job_valid(self, job):
        current = get_db().execute("SELECT * FROM managed_setup_jobs WHERE telegram_bot_id=?", (job["telegram_bot_id"],)).fetchone()
        if not current or current["state"] != "pending" or current["update_id"] != job["update_id"]:
            return False
        row = get_db().execute("SELECT * FROM bots WHERE telegram_bot_id=?", (job["telegram_bot_id"],)).fetchone()
        if row:
            bot = dict(row)
            return (not bot.get("deleted_at") and bot.get("desired_state") == "RUNNING"
                    and int(bot["owner_id"]) == int(job["owner_id"])
                    and int(bot.get("generation", 0)) == int(job.get("generation", 0)))
        return True

    async def _configure_managed_bot(self, owner_id, managed_bot, context, job=None):
        identity = int(managed_bot.id)
        if identity == context.bot.id:
            raise ValueError("不能托管主机器人自身")
        token = await context.bot.get_managed_bot_token(user_id=identity)
        if not isinstance(token, str) or not TOKEN_RE.fullmatch(token) or int(token.partition(":")[0]) != identity:
            raise ValueError("托管 Token 与官方机器人身份不一致")
        if job is not None and not self._managed_job_valid(job):
            return False

        async def send(text, **kwargs):
            return await self._send_main_user_message(context, owner_id, text, **kwargs)
        return await self._setup_new_bot(owner_id, token, send, managed_id=identity, job=job)

    async def handle_managed_bot_update(self, update, context):
        data = update.to_dict()
        event = data.get("managed_bot")
        if not event:
            msg = data.get("message") or {}
            created = msg.get("managed_bot_created")
            if not created:
                return
            if (msg.get("chat") or {}).get("type") != "private":
                raise ApplicationHandlerStop
            event = {"user": msg.get("from"), "bot": created.get("bot")}
        owner, bot = event.get("user") or {}, event.get("bot") or {}
        if (not owner.get("id") or owner.get("is_bot") or not bot.get("is_bot")
                or not bot.get("id") or int(owner["id"]) <= 0 or int(bot["id"]) <= 0
                or int(bot["id"]) == context.bot.id):
            logger.warning("忽略身份不完整的官方托管事件")
            raise ApplicationHandlerStop
        owner_id, identity = int(owner["id"]), int(bot["id"])
        touch_main_user(owner_id, owner.get("username", ""), owner.get("first_name", ""))
        with transaction() as con:
            row = con.execute("SELECT * FROM bots WHERE telegram_bot_id=?", (identity,)).fetchone()
            if row and (int(row["owner_id"]) != owner_id or row["deleted_at"] or row["desired_state"] != "RUNNING"):
                logger.warning("托管事件拒绝覆盖现有身份 bot_id=%s", identity)
                raise ApplicationHandlerStop
            prior = con.execute("SELECT owner_id FROM managed_setup_jobs WHERE telegram_bot_id=?", (identity,)).fetchone()
            if prior and int(prior["owner_id"]) != owner_id:
                logger.warning("托管事件拒绝覆盖已登记创建者 bot_id=%s", identity)
                raise ApplicationHandlerStop
            generation = row["generation"] if row else 0
            con.execute("""INSERT INTO managed_setup_jobs
                (telegram_bot_id,owner_id,bot_username,update_id,attempts,next_retry,state,generation)
                VALUES(?,?,?,?,0,0,'pending',?) ON CONFLICT(telegram_bot_id) DO UPDATE SET
                update_id=excluded.update_id,bot_username=excluded.bot_username,
                attempts=0,next_retry=0,state='pending',generation=excluded.generation
                WHERE excluded.update_id>managed_setup_jobs.update_id AND managed_setup_jobs.owner_id=excluded.owner_id""",
                (identity, owner_id, bot.get("username", ""), update.update_id, generation))
        await self.retry_managed_jobs(context)
        raise ApplicationHandlerStop

    async def retry_managed_jobs(self, context):
        async with self._jobs_lock:
            await self._retry_managed_jobs_locked(context)
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


    async def _retry_managed_jobs_locked(self, context):
        rows = get_db().execute("SELECT * FROM managed_setup_jobs WHERE state='pending' AND next_retry<=? ORDER BY update_id LIMIT 20", (time.time(),)).fetchall()
        for row in rows:
            job = dict(row)
            if not self._managed_job_valid(job):
                self._finish_managed(job, "cancelled", "机器人状态或所有者已变化")
                continue
            try:
                ok = await self._configure_managed_bot(job["owner_id"], SimpleNamespace(id=job["telegram_bot_id"]), context, job)
                if not ok:
                    if not self._managed_job_valid(job):
                        self._finish_managed(job, "cancelled", "机器人状态已变化")
                        continue
                    raise RuntimeError("初始化或启动未完成")
            except (InvalidToken, Forbidden, ValueError, PermissionError) as exc:
                self._finish_managed(job, "failed", type(exc).__name__)
                await self._notify_setup(lambda text: self._send_main_user_message(context, job["owner_id"], text),
                                         "❌ 托管配置未完成，请检查机器人授权后重新操作。")
            except Exception as exc:
                attempts = int(job["attempts"]) + 1
                delay = min(3600, 5 * 2 ** min(attempts, 9))
                if isinstance(exc, RetryAfter):
                    value = exc.retry_after
                    delay = min(3600, max(delay, value.total_seconds() if hasattr(value, "total_seconds") else float(value)))
                get_db().execute("""UPDATE managed_setup_jobs SET attempts=?,next_retry=?,last_error=?
                    WHERE telegram_bot_id=? AND update_id=? AND state='pending'""",
                    (attempts, time.time() + delay, type(exc).__name__, job["telegram_bot_id"], job["update_id"]))
                get_db().commit()
                logger.warning("托管重试 bot_id=%s attempt=%s error=%s", job["telegram_bot_id"], attempts, type(exc).__name__)
                if attempts == 1:
                    await self._notify_setup(lambda text: self._send_main_user_message(context, job["owner_id"], text),
                                             "⚠️ 机器人已创建，但配置未完成，系统将自动重试，无需发送 /start。")
            else:
                self._finish_managed(job, "done", "")

    def _finish_managed(self, job, state, error):
        get_db().execute("UPDATE managed_setup_jobs SET state=?,last_error=? WHERE telegram_bot_id=? AND update_id=? AND state='pending'",
                         (state, error, job["telegram_bot_id"], job["update_id"]))
        get_db().commit()

    async def _setup_new_bot(self, user_id, token, send_message, managed_id=None, job=None):
        async with self._managed_sync_lock:
            if not TOKEN_RE.fullmatch(token or ""):
                raise ValueError("Token 格式不正确")
            if self.bot is not None and int(token.partition(":")[0]) == self.bot.id:
                raise ValueError("不能添加主机器人自身")
            try:
                async with Bot(token=token) as probe:
                    info = await probe.get_me()
            except Exception as exc:
                logger.warning("机器人验证失败 error=%s", type(exc).__name__)
                if managed_id is not None:
                    raise
                await self._notify_setup(send_message, "❌ Token 验证失败，请检查 Token 或网络后重试。")
                return False
            if info.id != int(token.partition(":")[0]) or (managed_id is not None and info.id != managed_id):
                raise ValueError("机器人身份不一致")
            if job is not None and not self._managed_job_valid(job):
                return False
            row = get_db().execute("SELECT * FROM bots WHERE telegram_bot_id=? OR bot_token LIKE ? ORDER BY id LIMIT 1",
                                   (info.id, f"{info.id}:%")).fetchone()
            existing = dict(row) if row else None
            if existing:
                if int(existing["owner_id"]) != int(user_id):
                    raise PermissionError("此机器人已属于其他用户，请先办理所有权转移")
                if existing.get("deleted_at") or existing.get("desired_state") == "DELETED":
                    raise ValueError("此机器人已删除，不能由旧事件恢复")
                bot_id = existing["id"]
                if managed_id is not None and existing.get("desired_state") != "RUNNING":
                    return False
                if existing["bot_token"] != token:
                    try:
                        await self._rotate_clone_token(bot_id, token, actor_id=user_id)
                    finally:
                        # Rotation cancels older setup attempts. Rebind only this attempt
                        # when exactly its own token change advanced the generation.
                        if job is not None:
                            current = get_bot(bot_id)
                            if (current and current["owner_id"] == user_id and not current.get("deleted_at")
                                    and current.get("desired_state") == "RUNNING" and current["bot_token"] == token
                                    and current["generation"] == existing["generation"] + 1):
                                get_db().execute("""UPDATE managed_setup_jobs SET state='pending',generation=?
                                    WHERE telegram_bot_id=? AND update_id=? AND owner_id=? AND state='cancelled'""",
                                    (current["generation"], info.id, job["update_id"], user_id))
                                get_db().commit()
                                job["generation"] = current["generation"]
                elif existing.get("desired_state") == "RUNNING":
                    await self._start_clone_bot(bot_id, actor_id=user_id)
                else:
                    await self._notify_setup(send_message, "ℹ️ 机器人已登记但处于断开/停止状态，请在设置中恢复。")
                    return True
            else:
                from .store import has_capability
                with transaction() as con:
                    bots = get_bots_by_owner(user_id)
                    limit = int(get_setting(0, "free_bot_limit", "5"))
                    unlimited = any(has_capability(b["id"], "unlimited_bots") for b in bots)
                    feature = con.execute("SELECT enabled FROM vip_features WHERE key='unlimited_bots'").fetchone()
                    unlimited = unlimited or not feature or not feature["enabled"]
                    if not unlimited and len(bots) >= limit:
                        raise ValueError(f"普通版最多新建 {limit} 个机器人；已有机器人不受影响")
                    cursor = con.execute("""INSERT INTO bots(bot_token,bot_username,bot_name,owner_id,telegram_bot_id,
                        desired_state,actual_state,status,created_at) VALUES(?,?,?,?,?,'RUNNING','STOPPED','setup_pending',?)""",
                        (token, info.username or "", info.first_name or "", user_id, info.id, time.strftime("%Y-%m-%d %H:%M:%S")))
                    bot_id = cursor.lastrowid
                await self._notify_setup(send_message, render_emoji_html(get_main_text("creating_bot")), parse_mode="HTML")
                await self._start_clone_bot(bot_id, actor_id=user_id)
            current = get_bot(bot_id)
            if current.get("actual_state") != "RUNNING":
                if managed_id is not None:
                    raise RuntimeError("启动尚未完成")
                await self._notify_setup(send_message, "⚠️ Token 已验证，但机器人尚未运行，请在设置查看状态后重试。")
                return False
            await self._notify_setup(send_message, render_emoji_html(get_main_text("created_bot", username=info.username or "")), parse_mode="HTML")
            return True

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
