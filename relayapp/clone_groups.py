# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Bound group/channel reception and current-admin mapped replies only."""
from __future__ import annotations

import json
from telegram.error import TelegramError
from .common import capture_payload, send_payload
from .clone_state import paced_entry


class CloneGroupsMixin:
    async def _check_group(self, context, chat_id, actor):
        bot_id = context.bot.id
        try:
            bot_member = await context.bot.get_chat_member(chat_id, bot_id)
            actor_member = await context.bot.get_chat_member(chat_id, actor)
            chat = await context.bot.get_chat(chat_id)
        except TelegramError as exc:
            raise ValueError('无法确认目标群组/频道权限，请稍后重试') from exc
        if not self._admin(actor):
            raise ValueError('客服权限已失效')
        if str(bot_member.status) not in ('administrator', 'creator', 'owner') or str(actor_member.status) not in ('administrator', 'creator', 'owner'):
            raise ValueError('机器人和操作者都必须是该群组/频道的管理员')
        return chat

    async def _groups(self, target):
        groups = self._rows('SELECT * FROM group_bindings WHERE bot_id=? ORDER BY chat_id')
        rows = [[(f"{g['title']} · {'启用' if g['enabled'] else '停用'}", f"group:view:{g['chat_id']}")] for g in groups]
        rows += [[('绑定群组/频道', 'group:bind'), ('管理面板', 'cad:back_panel')]]
        await self._say(target, f'绑定群组/频道：{len(groups)}', rows)

    async def _group_callback(self, query, context):
        if not query.data.startswith('group:'):
            return False
        actor = query.from_user.id
        parts = query.data.split(':')
        op = parts[1]
        if op == 'bind':
            self._draft(actor, 'group_bind', {'kind': 'group'})
            await self._say(query, '发送群组/频道的数字ID或 @用户名；机器人与你都必须在目标中具有管理权限。')
            return True
        chat_id = int(parts[2])
        row = self._row('SELECT * FROM group_bindings WHERE bot_id=? AND chat_id=?', (chat_id,))
        if not row:
            raise ValueError('此绑定不属于当前机器人')
        if op == 'view':
            await self._say(query, f"{row['title']} ({chat_id})\n类型：{row['kind']}\n启用：{bool(row['enabled'])}\n客服群：{bool(row['staff_group'])}\n入群欢迎：{bool(row['welcome_enabled'])}",
                            [[('启用/停用', f'group:toggle:{chat_id}'), ('客服群开关', f'group:staff:{chat_id}')],
                             [('编辑欢迎语', f'group:welcome:{chat_id}'), ('欢迎语开关', f'group:welcome_toggle:{chat_id}')],
                             [('解除绑定', f'group:delete:{chat_id}'), ('返回', 'menu:groups')]])
        elif op == 'welcome':
            await self._check_group(context, chat_id, actor)
            self._draft(actor, 'group_welcome', {'kind': 'group', 'op': 'welcome', 'chat_id': chat_id})
            await self._say(query, '发送完整入群欢迎内容，预览确认后生效。')
        elif op in ('toggle', 'staff', 'welcome_toggle', 'delete'):
            if op != 'delete':
                await self._check_group(context, chat_id, actor)
            if op == 'staff' and row['kind'] not in ('group', 'supergroup'):
                raise ValueError('仅群组可作为客服群')
            await self._preview(query, context, actor, {'kind': 'group', 'op': op, 'chat_id': chat_id})
        else:
            raise ValueError('群组操作无效')
        return True
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def _group_input(self, update, context, session):
        actor, msg = update.effective_user.id, update.effective_message
        data = session['data']
        if session['state'] == 'group_bind':
            text = (msg.text or '').strip()
            chat_id = int(text) if text.lstrip('-').isdigit() else text
            chat = await self._check_group(context, chat_id, actor)
            if str(chat.type) not in ('group', 'supergroup', 'channel'):
                raise ValueError('只能绑定群组或频道')
            data.update(op='bind', chat_id=chat.id, title=chat.title or str(chat.id), chat_kind=str(chat.type))
        else:
            await self._check_group(context, data['chat_id'], actor)
            data['payload'] = capture_payload(msg.reply_to_message or msg)
        await self._preview(msg, context, actor, data)

    def _apply_group(self, db, data):
        op, chat_id = data['op'], data['chat_id']
        if op == 'bind':
            db.execute('INSERT INTO group_bindings(bot_id,chat_id,title,kind,enabled) VALUES(?,?,?,?,1) ON CONFLICT(bot_id,chat_id) DO UPDATE SET title=excluded.title,kind=excluded.kind,enabled=1', (self.bot_id, chat_id, data['title'], data['chat_kind']))
            return
        if not db.execute('SELECT 1 FROM group_bindings WHERE bot_id=? AND chat_id=?', (self.bot_id, chat_id)).fetchone():
            raise ValueError('绑定不存在')
        if op == 'delete':
            db.execute('DELETE FROM group_bindings WHERE bot_id=? AND chat_id=?', (self.bot_id, chat_id))
        elif op == 'welcome':
            db.execute('UPDATE group_bindings SET welcome_payload=?,welcome_enabled=1 WHERE bot_id=? AND chat_id=?', (json.dumps(data['payload'], ensure_ascii=False), self.bot_id, chat_id))
        else:
            column = {'toggle': 'enabled', 'staff': 'staff_group', 'welcome_toggle': 'welcome_enabled'}[op]
            db.execute(f'UPDATE group_bindings SET {column}=1-{column} WHERE bot_id=? AND chat_id=?', (self.bot_id, chat_id))

    @paced_entry
    async def handle_group_message(self, update, context):
        actor = update.effective_user
        msg = update.effective_message
        if not actor or not msg:
            return
        if msg.text and msg.text.split()[0].split('@')[0] == '/bind':
            if not self._admin(actor.id):
                return
            chat = await self._check_group(context, msg.chat.id, actor.id)
            await self._preview(msg, context, actor.id, {'kind': 'group', 'op': 'bind', 'chat_id': chat.id, 'title': chat.title or str(chat.id), 'chat_kind': str(chat.type)})
            return
        row = self._row('SELECT * FROM group_bindings WHERE bot_id=? AND chat_id=? AND enabled=1 AND staff_group=1', (msg.chat.id,))
        if not row or not self._admin(actor.id) or not msg.reply_to_message:
            return
        target = self._route(msg.chat.id, msg.reply_to_message.message_id)
        if target:
            await self._reply_customer(update, context, target)

    @paced_entry
    async def handle_new_members(self, update, context):
        msg = update.effective_message
        if not msg or not getattr(msg, 'new_chat_members', None):
            return
        row = self._row('SELECT * FROM group_bindings WHERE bot_id=? AND chat_id=? AND enabled=1 AND welcome_enabled=1', (msg.chat.id,))
        if row:
            payload = json.loads(row['welcome_payload'])
            if payload:
                await send_payload(context.bot, msg.chat.id, payload)

    @paced_entry
    async def handle_chat_member(self, update, context):
        event = getattr(update, 'my_chat_member', None)
        if event and str(event.new_chat_member.status) not in ('administrator', 'creator', 'owner'):
            self._write('UPDATE group_bindings SET enabled=0 WHERE bot_id=? AND chat_id=?', (event.chat.id,))

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
