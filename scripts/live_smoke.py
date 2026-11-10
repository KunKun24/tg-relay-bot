# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Explicit admin-only live acceptance; uses isolated SQL and never broadcasts to customers."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from telegram import Bot, Chat, Message, Update, User
from relayapp import database
from relayapp.broadcast import BroadcastService
from relayapp.config import DB_PATH, MAIN_ADMIN_ID, MAIN_BOT_TOKEN, ROOT
from relayapp.formatting import send_payload
from relayapp.main_ui import MainBotHandlers
from relayapp.network import configure_telegram_dns
from relayapp.relay import RelayBotHandlers


class ProbeBot(Bot):
    async def send_message(self, *args, **kwargs):
        msg = await super().send_message(*args, **kwargs)
        record = summarize(msg)
        print(json.dumps({'api_result': record}, ensure_ascii=False))
        return msg


def summarize(msg):
    rows = getattr(getattr(msg, 'reply_markup', None), 'inline_keyboard', ())
    return {'message_id': msg.message_id, 'chat_id': msg.chat_id,
            'inline_buttons': sum(len(r) for r in rows),
            'button_icons': sum(bool(getattr(b, 'icon_custom_emoji_id', None)) for r in rows for b in r),
            'styles': [b.style for r in rows for b in r if getattr(b, 'style', None)],
            'custom_emoji_entities': sum(e.type == 'custom_emoji' for e in (msg.entities or msg.caption_entities or ()))}


def update_for(bot, command):
    message = Message(message_id=900000, date=datetime.now(timezone.utc),
                      chat=Chat(MAIN_ADMIN_ID, 'private'), from_user=User(MAIN_ADMIN_ID, '管理员', False), text=command)
    message.set_bot(bot)
    return Update(update_id=900000, message=message)


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

async def run(clone_id):
    configure_telegram_dns()
    source = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    row = source.execute('SELECT * FROM bots WHERE id=? AND owner_id=? AND deleted_at IS NULL', (clone_id, MAIN_ADMIN_ID)).fetchone()
    if row is None:
        raise ValueError('仅允许平台管理员本人拥有的克隆私聊验收')
    row = dict(row)
    settings = [tuple(r) for r in source.execute('SELECT * FROM settings WHERE bot_id IN (0,?)', (clone_id,)) if r['key'] not in ('runtime_heartbeat',)]
    welcomes = [dict(r) for r in source.execute('SELECT * FROM welcome_messages WHERE bot_id=?', (clone_id,))]
    source.close()
    previous = database._db_path
    report = {'admin_id': MAIN_ADMIN_ID, 'clone_id': clone_id, 'production_database_modified': False,
              'customer_broadcast': False, 'channel_and_group_permissions_tested': False}
    try:
        with tempfile.TemporaryDirectory(prefix='relay-live-admin-') as folder:
            database.init_db(Path(folder) / 'acceptance.sqlite3')
            con = database.get_db()
            columns = {r[1] for r in con.execute('PRAGMA table_info(bots)')}
            isolated_row = {key: value for key, value in row.items() if key in columns}
            con.execute(f"INSERT INTO bots({','.join(isolated_row)}) VALUES({','.join('?' for _ in isolated_row)})", tuple(isolated_row.values()))
            con.executemany('INSERT OR REPLACE INTO settings(bot_id,key,value) VALUES(?,?,?)', settings)
            for welcome in welcomes:
                con.execute(f"INSERT INTO welcome_messages({','.join(welcome)}) VALUES({','.join('?' for _ in welcome)})", tuple(welcome.values()))
            con.commit()
            async with ProbeBot(MAIN_BOT_TOKEN) as main_bot:
                report['main_bot'] = main_bot.username
                context = SimpleNamespace(bot=main_bot, user_data={})
                handler = MainBotHandlers()
                handler.bot = main_bot
                await handler.start(update_for(main_bot, '/start'), context)
                await handler.cmd_admin(update_for(main_bot, '/admin'), context)
                payload = {'type': 'text', 'text': '✅ 模块化升级实发验收：会员表情 👍 与三种按钮颜色。',
                           'entities': [{'type': 'custom_emoji', 'offset': 22, 'length': 2, 'custom_emoji_id': '5368324170671202286'}],
                           'buttons': [[{'text': '蓝色', 'style': 'primary', 'url': 'https://t.me/YOUR_BOT_USERNAME', 'icon_custom_emoji_id': '5368324170671202286'},
                                        {'text': '绿色', 'style': 'success', 'url': 'https://t.me/YOUR_BOT_USERNAME'},
                                        {'text': '红色', 'style': 'danger', 'url': 'https://t.me/YOUR_BOT_USERNAME'}]]}
                # Entity offsets are Telegram UTF-16 units, calculated from the actual prefix.
                prefix = payload['text'].split('👍')[0]
                payload['entities'][0]['offset'] = len(prefix.encode('utf-16-le')) // 2
                report['emoji_and_buttons'] = await send_payload(main_bot, MAIN_ADMIN_ID, payload)
                queue = BroadcastService()
                job_id = queue.create(0, MAIN_ADMIN_ID, {'type': 'text', 'text': '📣 私聊单接收者广播验收；没有向客户群发。'}, MAIN_ADMIN_ID)
                await queue.tick(lambda bid: main_bot if bid == 0 else None)
                report['broadcast'] = queue.stats(job_id, MAIN_ADMIN_ID)
                assert report['broadcast']['status'] == 'COMPLETED' and report['broadcast']['counts']['SENT'] == 1
            async with ProbeBot(row['bot_token']) as clone:
                report['clone_bot'] = clone.username
                handler = RelayBotHandlers(clone_id)
                context = SimpleNamespace(bot=clone, user_data={})
                await handler.cmd_admin(update_for(clone, '/admin'), context)
                # Direct owner diagnostic, never a simulated customer request or production route.
                await handler.send_welcome_to_user(context, MAIN_ADMIN_ID, force=True)
                report['clone_admin_and_welcome'] = True
            report['isolated_integrity'] = con.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        database.configure_database(previous)
    target = ROOT / 'data' / 'live-smoke.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    target.chmod(0o600)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clone-id', type=int, required=True)
    parser.add_argument('--confirm-admin-private-send', action='store_true', required=True)
    args = parser.parse_args()
    asyncio.run(run(args.clone_id))


if __name__ == '__main__':
    main()

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
