# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Per-bot serialized lifecycle with desired state and deletion tombstones."""
from __future__ import annotations

import asyncio
import logging
import time
from telegram import Bot, BotCommand
from telegram.ext import (Application, CommandHandler, MessageHandler, CallbackQueryHandler,
                          ChatMemberHandler, filters)
from telegram.request import HTTPXRequest
from .bots import get_bot, get_all_active_bots, ensure_owner_admin, audit
from .config import MAIN_ADMIN_ID
from .database import get_db, transaction

log = logging.getLogger(__name__)


async def telegram_error(update, context):
    # Exception objects can contain user text and tokens. Persist only error classes here.
    log.warning('Telegram处理失败 error=%s update_id=%s', type(context.error).__name__, getattr(update, 'update_id', None))


class LifecycleMixin:
    def _lock_for(self, bot_id):
        return self._runner_locks.setdefault(int(bot_id), asyncio.Lock())

    def _authorize(self, bot_id, actor_id):
        row = get_bot(bot_id)
        if not row or row.get('deleted_at') is not None or row.get('desired_state') == 'DELETED':
            raise ValueError('机器人不存在或已删除')
        if actor_id is not None and int(actor_id) not in (int(row['owner_id']), MAIN_ADMIN_ID):
            raise PermissionError('机器人归属已变化，无权操作')
        return row

    def _state(self, bot_id, **fields):
        allowed = {'actual_state', 'desired_state', 'status', 'last_error'}
        if set(fields) - allowed:
            raise ValueError('Invalid lifecycle field')
        with transaction() as con:
            con.execute('UPDATE bots SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?', (*fields.values(), bot_id))

    def _build_clone(self, row):
        from .relay import RelayBotHandlers
        handler = RelayBotHandlers(row['id'])
        request = HTTPXRequest(connection_pool_size=16, connect_timeout=10, read_timeout=35, write_timeout=30)
        app = Application.builder().token(row['bot_token']).request(request).concurrent_updates(False).build()
        for name, callback in [('start',handler.cmd_start),('admin',handler.cmd_admin),('users',handler.cmd_users),('clear',handler.cmd_clear)]:
            app.add_handler(CommandHandler(name, callback, filters=filters.ChatType.PRIVATE))
        app.add_handler(CallbackQueryHandler(handler.callback_handler))
        app.add_handler(MessageHandler(filters.ChatType.PRIVATE, handler.handle_private_message))
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS, handler.handle_new_members))
        app.add_handler(MessageHandler(filters.ChatType.GROUPS, handler.handle_group_message))
        app.add_handler(ChatMemberHandler(handler.handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
        app.add_error_handler(telegram_error)
        return {'app': app, 'handler': handler, 'generation': row['generation']}

    async def _cleanup_app(self, app):
        if app.updater and app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        await app.shutdown()

    async def _start_locked(self, bot_id):
        row = self._authorize(bot_id, None)
        if row['desired_state'] != 'RUNNING':
            raise ValueError('机器人当前未要求运行')
        if bot_id in self.clone_runners:
            if row['actual_state']=='RUNNING':
                return self.clone_runners[bot_id]
            # A prior partial startup may still own a polling connection.
            await self._stop_locked(bot_id)
        self._state(bot_id, actual_state='STARTING', last_error='', status='starting')
        runner = self._build_clone(row)
        app = runner['app']
        # Keep every potentially live Application reachable until cleanup succeeds.
        self.clone_runners[bot_id] = runner
        try:
            await app.initialize()
            if app.bot.id != int(row['telegram_bot_id']):
                raise ValueError('Token对应机器人身份变化')
            current = self._authorize(bot_id, None)
            if current['desired_state'] != 'RUNNING' or current['generation'] != row['generation']:
                raise ValueError('机器人状态已变化')
            ensure_owner_admin(bot_id, current['owner_id'])
            await app.start()
            await app.updater.start_polling(poll_interval=0.1, timeout=25, bootstrap_retries=0,
                allowed_updates=['message','callback_query','my_chat_member','chat_member'], drop_pending_updates=False,
                error_callback=lambda exc: log.warning('克隆轮询读取失败 bot_id=%s error=%s', bot_id, type(exc).__name__))
            self.clone_runners[bot_id] = runner
            self._state(bot_id, actual_state='RUNNING', status='active', last_error='')
            log.info('克隆已启动 bot_id=%s telegram_id=%s', bot_id, app.bot.id)
            return runner
        except BaseException as exc:
            try:
                await self._cleanup_app(app)
            except Exception as cleanup_exc:
                log.warning('克隆清理失败 bot_id=%s error=%s', bot_id, type(cleanup_exc).__name__)
            else:
                self.clone_runners.pop(bot_id,None)
            self._state(bot_id, actual_state='ERROR', status='error', last_error=type(exc).__name__)
            raise
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def _stop_locked(self, bot_id):
        runner = self.clone_runners.get(bot_id)
        self._state(bot_id, actual_state='STOPPING')
        if runner:
            try:
                await self._cleanup_app(runner['app'])
            except BaseException as exc:
                self._state(bot_id, actual_state='ERROR', last_error=type(exc).__name__)
                raise
            else:
                self.clone_runners.pop(bot_id, None)
        self._state(bot_id, actual_state='STOPPED')

    async def _start_clone_bot(self, bot_id, actor_id=None):
        async with self._lock_for(bot_id):
            self._authorize(bot_id, actor_id)
            return await self._start_locked(bot_id)

    async def _stop_clone_bot(self, bot_id, actor_id=None):
        async with self._lock_for(bot_id):
            self._authorize(bot_id, actor_id)
            self._state(bot_id, desired_state='STOPPED', status='stopped')
            await self._stop_locked(bot_id)

    async def _restart_clone_bot(self, bot_id, actor_id=None):
        async with self._lock_for(bot_id):
            row = self._authorize(bot_id, actor_id)
            if row['desired_state'] != 'RUNNING':
                raise ValueError('请先恢复连接')
            await self._stop_locked(bot_id)
            return await self._start_locked(bot_id)

    async def _reconnect_clone_bot(self, bot_id, actor_id=None):
        async with self._lock_for(bot_id):
            self._authorize(bot_id, actor_id)
            self._state(bot_id, desired_state='RUNNING', status='starting')
            return await self._start_locked(bot_id)

    async def _disconnect_clone_bot(self, bot_id, actor_id=None):
        async with self._lock_for(bot_id):
            self._authorize(bot_id, actor_id)
            with transaction() as con:
                con.execute("UPDATE bots SET desired_state='DISCONNECTED',status='disconnected',generation=generation+1 WHERE id=?",(bot_id,))
                con.execute("UPDATE managed_setup_jobs SET state='cancelled' WHERE telegram_bot_id=(SELECT telegram_bot_id FROM bots WHERE id=?)",(bot_id,))
                con.execute("UPDATE broadcast_jobs SET status='PAUSED',updated_at=? WHERE bot_id=? AND status IN ('PENDING','RUNNING')",(time.time(),bot_id))
            await self._stop_locked(bot_id)
            audit(bot_id, actor_id or 0, 'DISCONNECT')

    async def _delete_clone_bot(self, bot_id, actor_id=None):
        async with self._lock_for(bot_id):
            self._authorize(bot_id, actor_id)
            with transaction() as con:
                con.execute("UPDATE bots SET desired_state='DELETED',status='deleted',deleted_at=?,generation=generation+1 WHERE id=?",(time.time(),bot_id))
                con.execute("UPDATE managed_setup_jobs SET state='cancelled' WHERE telegram_bot_id=(SELECT telegram_bot_id FROM bots WHERE id=?)",(bot_id,))
                con.execute('DELETE FROM ui_sessions WHERE bot_id=?',(bot_id,))
                con.execute('DELETE FROM conversations WHERE bot_id=?',(bot_id,))
                con.execute("UPDATE owner_transfers SET state='CANCELLED' WHERE bot_id=? AND state='PENDING'",(bot_id,))
                con.execute("UPDATE broadcast_jobs SET status='CANCELLED',updated_at=? WHERE bot_id=? AND status IN ('PENDING','RUNNING','PAUSED')",(time.time(),bot_id))
            await self._stop_locked(bot_id)
            audit(bot_id, actor_id or 0, 'DELETE_TOMBSTONE')

    async def _rotate_clone_token(self, bot_id, token, actor_id=None):
        async with self._lock_for(bot_id):
            row = self._authorize(bot_id, actor_id)
            async with Bot(token=token) as probe:
                identity = await probe.get_me()
            row = self._authorize(bot_id, actor_id)
            if identity.id != int(row['telegram_bot_id']):
                raise ValueError('新Token不属于原来的Telegram机器人')
            # Validate before stopping; wrong tokens never interrupt the live clone.
            await self._stop_locked(bot_id)
            with transaction() as con:
                con.execute('UPDATE bots SET bot_token=?,bot_username=?,bot_name=?,generation=generation+1 WHERE id=?', (token,identity.username or '',identity.first_name or '',bot_id))
                con.execute("UPDATE managed_setup_jobs SET state='cancelled' WHERE telegram_bot_id=?",(identity.id,))
            audit(bot_id, actor_id or 0, 'ROTATE_TOKEN', {'telegram_bot_id': identity.id})
            if row['desired_state'] == 'RUNNING':
                return await self._start_locked(bot_id)

    async def retry_failed_clones(self):
        """Retry transient connection failures; never revive revoked/deleted/disconnected bots."""
        backoff = self.__dict__.setdefault('_clone_retry_after', {})
        attempts = self.__dict__.setdefault('_clone_retry_attempts', {})
        now = time.monotonic()
        rows = get_db().execute("SELECT id FROM bots WHERE desired_state='RUNNING' AND actual_state='ERROR' AND deleted_at IS NULL AND last_error IN ('TimedOut','NetworkError','RetryAfter') ORDER BY id").fetchall()
        semaphore = asyncio.Semaphore(2)
        async def one(row):
            bot_id = row['id']
            if backoff.get(bot_id, 0) > now:
                return
            async with semaphore, self._lock_for(bot_id):
                current = get_bot(bot_id)
                if not current or current.get('deleted_at') is not None or current['desired_state'] != 'RUNNING' or current['actual_state'] != 'ERROR' or current['last_error'] not in ('TimedOut','NetworkError','RetryAfter'):
                    return
                try:
                    await self._start_locked(bot_id)
                except Exception as exc:
                    count = attempts.get(bot_id, 0) + 1
                    attempts[bot_id] = count
                    backoff[bot_id] = time.monotonic() + min(900, 30 * 2 ** min(count - 1, 5))
                    log.warning('克隆自动恢复暂未成功 bot_id=%s error=%s', bot_id, type(exc).__name__)
                else:
                    attempts.pop(bot_id, None)
                    backoff.pop(bot_id, None)
        await asyncio.gather(*(one(row) for row in rows))

    async def start_all_clones(self):
        semaphore = asyncio.Semaphore(4)
        async def start(row):
            async with semaphore:
                try:
                    await self._start_clone_bot(row['id'])
                except Exception as exc:
                    log.warning('克隆启动未完成 bot_id=%s error=%s',row['id'],type(exc).__name__)
        await asyncio.gather(*(start(row) for row in get_all_active_bots()))

    async def shutdown_clones(self):
        async def stop(bot_id):
            async with self._lock_for(bot_id):
                await self._stop_locked(bot_id)
        results = await asyncio.gather(*(stop(bot_id) for bot_id in list(self.clone_runners)), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                log.warning('克隆退出异常 error=%s',type(result).__name__)

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
