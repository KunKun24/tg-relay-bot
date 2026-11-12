# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Single-process platform and clone supervisor; imports never start polling."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import time

from telegram import BotCommandScopeChat, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, TypeHandler, filters
from telegram.request import HTTPXRequest

from .broadcast import broadcasts
from .config import MAIN_ADMIN_ID, MAIN_BOT_TOKEN, ROOT, configure_logging
from .configuration import init_vip_features, set_setting
from .database import get_db, init_db, transaction
from .formatting import api_call
from .lifecycle import telegram_error
from .main_ui import MainBotHandlers
from .payments import check_expired_vips

log = logging.getLogger(__name__)


async def _periodic(stop, interval, callback, label):
    while not stop.is_set():
        try:
            await callback()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error('后台循环失败 name=%s error=%s', label, type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


def build_application():
    request = HTTPXRequest(connection_pool_size=32, connect_timeout=10, read_timeout=35, write_timeout=30, pool_timeout=30)
    polling_request = HTTPXRequest(connection_pool_size=1, connect_timeout=10, read_timeout=35, write_timeout=30, pool_timeout=30)
    return (Application.builder().token(MAIN_BOT_TOKEN).request(request)
            .get_updates_request(polling_request).concurrent_updates(False).build())


async def run():
    configure_logging()
    from .network import configure_telegram_dns
    addresses = configure_telegram_dns()
    if addresses:
        log.info('已启用服务内Telegram DNS修正，TLS主机名校验保留')
    if not MAIN_BOT_TOKEN:
        raise RuntimeError('请在私有.env配置MAIN_BOT_TOKEN')
    data = ROOT / 'data'
    data.mkdir(mode=0o700, exist_ok=True)
    # The lock is held through all clone shutdowns to prevent duplicate polling.
    with (data / 'runtime.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('双向机器人服务已经运行，不允许重复启动') from None
        init_db()
        init_vip_features()
        broadcasts.recover()
        # The previous process no longer exists after we acquired the OS lock.
        with transaction() as con:
            con.execute("UPDATE bots SET actual_state='STOPPED' WHERE deleted_at IS NULL")
        handlers = MainBotHandlers()
        app = build_application()
        app.add_error_handler(telegram_error)
        app.add_handler(TypeHandler(Update, handlers.handle_managed_bot_update), group=-1)
        app.add_handler(CommandHandler('start', handlers.start, filters=filters.ChatType.PRIVATE))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


        app.add_handler(CommandHandler('admin', handlers.cmd_admin, filters=filters.ChatType.PRIVATE))
        app.add_handler(CallbackQueryHandler(handlers.callback))
        app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handlers.handle_text))
        stop = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        jobs = []
        try:
            await app.initialize()
            handlers.bot = app.bot
            # One-click creation must use the identity returned by Telegram.
            from . import main_ui
            main_ui.MAIN_BOT_USERNAME = app.bot.username
            await app.start()
            await app.updater.start_polling(timeout=25, poll_interval=0.1, bootstrap_retries=0,
                allowed_updates=['message','callback_query','managed_bot'], drop_pending_updates=False,
                error_callback=lambda exc: log.warning('主机器人轮询读取失败 error=%s', type(exc).__name__))
            try:
                await app.bot.set_my_commands([('start','启动机器人')])
                await app.bot.set_my_commands([('start','启动机器人'),('admin','管理员后台')], scope=BotCommandScopeChat(chat_id=MAIN_ADMIN_ID))
            except Exception as exc:
                log.warning('快捷指令设置未完成 error=%s', type(exc).__name__)

            def lookup(bot_id):
                if bot_id == 0:
                    return app.bot
                runner = handlers.clone_runners.get(bot_id)
                return runner['app'].bot if runner else None

            async def heartbeat():
                con = get_db()
                counts = dict(con.execute('SELECT actual_state,count(*) FROM bots GROUP BY actual_state').fetchall())
                set_setting(0, 'runtime_heartbeat', json.dumps({'at':time.time(),'pid':os.getpid(),'running_clones':len(handlers.clone_runners),'states':counts}))

            async def reminders():
                semaphore = asyncio.Semaphore(4)
                async def one(runner):
                    async with semaphore:
                        try:
                            await runner['handler'].reminder_tick(runner['app'].bot)
                        except Exception as exc:
                            log.warning('访客提醒失败 error=%s', type(exc).__name__)
                await asyncio.gather(*(one(r) for r in list(handlers.clone_runners.values())))

            async def expiry():
                for row in check_expired_vips():
                    try:
                        await api_call(app.bot,row['owner_id'],'send_message',text=f"⚠️ @{row['bot_username']} 的高级版已到期；原有配置和数据保留，新增或编辑受当前权益限制。")
                    except Exception as exc:
                        log.warning('到期通知未送达 error=%s', type(exc).__name__)

            await heartbeat()
            jobs = [asyncio.create_task(_periodic(stop,1,lambda:broadcasts.tick(lookup),'broadcast')),
                    asyncio.create_task(_periodic(stop,30,lambda:handlers.retry_managed_jobs(app),'managed')),
                    asyncio.create_task(_periodic(stop,60,reminders,'reminders')),
                    asyncio.create_task(_periodic(stop,60,expiry,'expiry')),
                    asyncio.create_task(_periodic(stop,15,heartbeat,'heartbeat'))]
            await handlers.start_all_clones()
            jobs.append(asyncio.create_task(_periodic(stop,30,handlers.retry_failed_clones,'clone_reconnect')))
            log.info('模块化服务已启动 main=@%s running_clones=%s',app.bot.username,len(handlers.clone_runners))
            if not stop.is_set():
                try:
                    await api_call(app.bot,MAIN_ADMIN_ID,'send_message',text=f'✅ 双向机器人模块化服务已启动。\n主机器人：@{app.bot.username}\n已运行克隆：{len(handlers.clone_runners)}\n发送 /admin 打开主后台；在自己的克隆中发送 /admin 管理客服功能。')
                except Exception as exc:
                    log.warning('启动通知未送达 error=%s',type(exc).__name__)
            await stop.wait()
        finally:
            stop.set()
            if app.updater and app.updater.running:
                await app.updater.stop()
            # Do not cancel a broadcast API request: persist its returned result first.
            if jobs:
                await asyncio.gather(*jobs,return_exceptions=True)
            await handlers.shutdown_clones()
            if app.running:
                await app.stop()
            with suppress(Exception):
                await app.shutdown()
            set_setting(0,'runtime_stopped_at',str(time.time()))
            log.info('主服务与克隆轮询已安全停止')


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
