# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Dynamic, chat-scoped clone customer service handlers."""
from __future__ import annotations

import json
import logging
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError
from .common import *
from .clone_state import CloneStateMixin, paced_entry
from .clone_config import CloneConfigMixin
from .clone_groups import CloneGroupsMixin
from .clone_ui import CloneUIMixin

logger = logging.getLogger(__name__)


class _CallbackAlias:
    def __init__(self, query, data):
        self.query, self.data = query, data

    def __getattr__(self, name):
        return getattr(self.query, name)


class RelayBotHandlers(CloneConfigMixin, CloneGroupsMixin, CloneUIMixin, CloneStateMixin):
    def __init__(self, bot_id: int):
        self.bot_id = bot_id
        self._verified_cache = {}

    def get_bot_info(self):
        return get_bot(self.bot_id) or {}

    def get_admin_id(self):
        return int(self.get_bot_info().get('owner_id', 0))

    def _admin(self, uid):
        return is_bot_admin(self.bot_id, uid)

    def _staff_destination(self, chat_id):
        if chat_id > 0:
            return self._admin(chat_id)
        return bool(self._row('SELECT 1 FROM group_bindings WHERE bot_id=? AND chat_id=? AND enabled=1 AND staff_group=1', (chat_id,)))

    async def _staff_send(self, bot, chat_id, method, **kwargs):
        async def guarded(chat_id, **values):
            if not self._staff_destination(chat_id):
                raise Forbidden('客服权限或群绑定已失效')
            return await getattr(bot, method)(chat_id=chat_id, **values)
        return await api_call(bot, chat_id, guarded, **kwargs)

    async def _say(self, target, text, rows=None):
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows]) if rows else None
        if hasattr(target, 'edit_message_text'):
            try:
                return await target.edit_message_text(text, reply_markup=markup)
            except TelegramError as exc:
                if 'not modified' not in str(exc).lower():
                    raise
        else:
            return await target.reply_text(text, reply_markup=markup)

    async def _gate(self, update, context):
        user = update.effective_user
        if is_blocked(self.bot_id, user.id):
            return False
        info = self.get_bot_info()
        channel = str(info.get('channel_id') or get_setting(self.bot_id, 'channel_id', '')).strip()
        revision = (channel, get_setting(self.bot_id, 'channel_link', ''), get_setting(self.bot_id, 'verify_text', ''), get_setting(self.bot_id, 'verification_revision', ''))
        cached = self._verified_cache.get(user.id)
        if channel and not (cached and cached[0] == revision and cached[1] > time.time()):
            try:
                member = await context.bot.get_chat_member(channel, user.id)
                status = str(member.status)
                allowed = status in ('member', 'administrator', 'creator', 'owner') or (status == 'restricted' and bool(getattr(member, 'is_member', False)))
            except TelegramError:
                allowed = False
            if not allowed:
                self._verified_cache.pop(user.id, None)
                self._write('UPDATE users SET verified=0 WHERE bot_id=? AND user_id=?', (user.id,))
                markup = InlineKeyboardMarkup([[InlineKeyboardButton('加入频道', url=revision[1])]]) if revision[1] else None
                await update.effective_message.reply_text(revision[2] or '请加入频道后重新发送 /start；暂时无法验证时请稍后重试。', reply_markup=markup)
                return False
            self._verified_cache[user.id] = (revision, time.time() + 45)
        add_user(self.bot_id, user.id, user.username, user.first_name, verified=1)
        self._write('UPDATE users SET verified=1 WHERE bot_id=? AND user_id=?', (user.id,))
        return True

    @paced_entry
    async def cmd_start(self, update, context):
        if self._admin(update.effective_user.id):
            await self._show_admin_panel(update.effective_message, context)
        elif await self._gate(update, context):
            await self.send_welcome_to_user(context, update.effective_user.id, force=True)

    @paced_entry
    async def cmd_admin(self, update, context):
        if self._admin(update.effective_user.id):
            await self._show_admin_panel(update.effective_message, context)
        else:
            await self._gate(update, context)

    @paced_entry
    async def cmd_users(self, update, context):
        if self._admin(update.effective_user.id):
            await self._clients(update.effective_message)
        else:
            await self._gate(update, context)

    @paced_entry
    async def cmd_clear(self, update, context):
        actor = update.effective_user.id
        if not self._admin(actor):
            await self._gate(update, context)
            return
        self._cancel(actor)
        self._write('DELETE FROM conversations WHERE bot_id=? AND admin_id=?', (actor,))
        await update.effective_message.reply_text('已清除你的当前会话和编辑草稿。')

    @paced_entry
    async def handle_private_message(self, update, context):
        if self._admin(update.effective_user.id):
            await self.handle_admin_message(update, context)
        elif await self._gate(update, context):
            await self._customer_message(update, context)

    @paced_entry
    async def handle_user_message(self, update, context):
        await self.handle_private_message(update, context)
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def _customer_message(self, update, context):
        user, msg = update.effective_user, update.effective_message
        text = msg.text or msg.caption or ''
        if await self._filter_message(update, context, text):
            return
        is_new = self._case(user.id) is None
        self._write("INSERT INTO client_cases(bot_id,user_id,last_inbound_at,state) VALUES(?,?,?,'OPEN') ON CONFLICT(bot_id,user_id) DO UPDATE SET last_inbound_at=excluded.last_inbound_at,state='OPEN',reminder_count=0", (user.id, time.time()))
        try:
            if should_send_welcome(self.bot_id, user.id):
                await self.send_welcome_to_user(context, user.id)
            if text.startswith('/'):
                command = text.split()[0].split('@')[0][1:]
                row = self._row('SELECT * FROM commands WHERE bot_id=? AND command=? AND enabled=1', (command,))
                if row:
                    await self._send_customer_payload(context, user.id, json.loads(row['payload']), build_reply_keyboard(self.bot_id))
            ar = match_auto_reply(self.bot_id, text)
            if ar:
                await self.send_auto_reply(context, user.id, ar)
        except (TelegramError, ValueError, TypeError, KeyError):
            self._audit(0, 'customer_automation_failed', {'user_id': user.id})
        admins = [int(a) for a in get_bot_admins(self.bot_id) if a and self._admin(int(a))]
        case = self._case(user.id)
        assigned = case.get('assigned_admin_id')
        mode = get_setting(self.bot_id, 'routing_mode', 'shared')
        if assigned in admins:
            recipients = [assigned]
        elif mode == 'balanced' and admins:
            loads = {a: 0 for a in admins}
            for row in self._rows("SELECT assigned_admin_id,COUNT(*) AS n FROM client_cases WHERE bot_id=? AND state='OPEN' GROUP BY assigned_admin_id"):
                if row['assigned_admin_id'] in loads:
                    loads[row['assigned_admin_id']] = row['n']
            selected = min(admins, key=lambda a: (loads[a], a))
            with transaction() as db:
                db.execute('UPDATE client_cases SET assigned_admin_id=? WHERE bot_id=? AND user_id=?', (selected, self.bot_id, user.id))
            recipients = [selected]
        else:
            recipients = admins
        recipients += [r['chat_id'] for r in self._rows('SELECT chat_id FROM group_bindings WHERE bot_id=? AND enabled=1 AND staff_group=1')]
        delivered = 0
        for chat_id in dict.fromkeys(recipients):
            try:
                sent = await self._staff_send(context.bot, chat_id, 'copy_message', from_chat_id=msg.chat.id, message_id=msg.message_id)
            except (BadRequest, Forbidden):
                self._audit(0, 'inbound_delivery_failed', {'user_id': user.id, 'chat_id': chat_id})
                continue
            except NetworkError:
                self._audit(0, 'inbound_delivery_unknown', {'user_id': user.id, 'chat_id': chat_id, 'message_id': msg.message_id})
                continue
            except TelegramError:
                self._audit(0, 'inbound_delivery_failed', {'user_id': user.id, 'chat_id': chat_id})
                continue
            self._save_route(chat_id, sent.message_id, user.id, msg.message_id)
            save_message(self.bot_id, user.id, 'user_to_admin', text or '[媒体]', admin_msg_id=sent.message_id, user_msg_id=msg.message_id, admin_chat_id=chat_id)
            delivered += 1
            try:
                name = user.first_name or user.username or str(user.id)
                header = await self._staff_send(context.bot, chat_id, 'send_message', text=f'客户 {name} · {user.id}', reply_to_message_id=sent.message_id, reply_markup=self._case_markup(user.id))
                self._save_route(chat_id, header.message_id, user.id, msg.message_id)
            except TelegramError:
                pass
        if not delivered:
            await msg.reply_text('消息已登记为待回复，客服投递暂未确认，请勿重复发送。')
        if is_new and get_setting(self.bot_id, 'visitor_notify', '1') == '1':
            for admin in admins:
                try:
                    await self._staff_send(context.bot, admin, 'send_message', text=f'新访客 {user.first_name or user.id}（{user.id}）已咨询。')
                except TelegramError:
                    pass

    @paced_entry
    async def handle_admin_message(self, update, context):
        actor, msg = update.effective_user.id, update.effective_message
        if not self._admin(actor):
            return
        if await self._config_input(update, context):
            return
        if msg.text and msg.text.startswith('/'):
            return
        replied = msg.reply_to_message
        if replied:
            target = self._route(msg.chat.id, replied.message_id)
            if not target:
                target = find_user_by_admin_message(self.bot_id, replied.message_id, admin_chat_id=msg.chat.id)
            if not target:
                await msg.reply_text('引用消息没有本聊天的有效客户路由；未发送。')
                return
        else:
            conv = get_conversation(self.bot_id, actor)
            target = conv.get('current_user_id') if conv else None
        if not target or not get_user(self.bot_id, target):
            await msg.reply_text('请先选择客户，或引用已映射的客户消息。')
            return
        await self._reply_customer(update, context, target)

    async def _reply_customer(self, update, context, target):
        actor, msg = update.effective_user.id, update.effective_message
        if not self._admin(actor):
            return
        async def copy_to_customer(chat_id, **kwargs):
            if not self._admin(actor):
                raise Forbidden('客服权限已失效')
            if msg.chat.id < 0 and not self._row('SELECT 1 FROM group_bindings WHERE bot_id=? AND chat_id=? AND enabled=1 AND staff_group=1', (msg.chat.id,)):
                raise Forbidden('客服群绑定已失效')
            return await context.bot.copy_message(chat_id=chat_id, **kwargs)
        try:
            sent = await api_call(context.bot, target, copy_to_customer, from_chat_id=msg.chat.id, message_id=msg.message_id)
        except (BadRequest, Forbidden):
            await msg.reply_text('发送失败，未记账。')
            return
        except NetworkError:
            self._audit(actor, 'outbound_delivery_unknown', {'user_id': target, 'message_id': msg.message_id, 'chat_id': msg.chat.id})
            await msg.reply_text('发送结果未知，未记为成功；请核实后决定是否重发，重复发送可能造成重复消息。')
            return
        except TelegramError:
            await msg.reply_text('发送失败，未记账。')
            return
        save_message(self.bot_id, target, 'admin_to_user', msg.text or msg.caption or '[媒体]', admin_msg_id=msg.message_id, user_msg_id=sent.message_id, admin_chat_id=msg.chat.id)
        self._save_route(msg.chat.id, msg.message_id, target, sent.message_id)
        with transaction() as db:
            db.execute("UPDATE client_cases SET last_outbound_at=?,state='OPEN',reminder_count=0 WHERE bot_id=? AND user_id=?", (time.time(), self.bot_id, target))
        self._audit(actor, 'customer_reply', {'user_id': target, 'message_id': sent.message_id})
        await msg.reply_text(f'已发送给客户 {target}。')

    async def _send_customer_payload(self, context, user_id, payload, keyboard=None):
        if payload.get('buttons') and keyboard:
            await send_payload(context.bot, user_id, payload)
            await send_payload(context.bot, user_id, {'type': 'text', 'text': '请选择'}, reply_markup=keyboard)
        else:
            await send_payload(context.bot, user_id, payload, reply_markup=keyboard)

    async def send_auto_reply(self, context, user_id, ar):
        payload = self._legacy_payload(ar, auto=True)
        inline = ar.get('inline_kb')
        if inline and not payload.get('buttons'):
            buttons = json.loads(inline)
            if buttons and isinstance(buttons[0], dict):
                buttons = [[button] for button in buttons]
            payload = {**payload, 'buttons': buttons}
        keyboard = build_reply_keyboard(self.bot_id)
        if ar.get('reply_kb'):
            config = json.loads(ar['reply_kb'])
            if isinstance(config, list):
                config = {'enabled': True, 'per_row': 2, 'buttons': config}
            if config.get('enabled', True) and config.get('buttons'):
                per_row = max(1, min(10, int(config.get('per_row', 2))))
                buttons = []
                for item in config['buttons']:
                    item = {'text': item} if isinstance(item, str) else item
                    options = {}
                    if item.get('color') in ('primary', 'success', 'danger'):
                        options['style'] = item['color']
                    if item.get('emoji_id'):
                        options['icon_custom_emoji_id'] = str(item['emoji_id'])
                    buttons.append(KeyboardButton(item['text'], **options))
                keyboard = ReplyKeyboardMarkup([buttons[i:i+per_row] for i in range(0, len(buttons), per_row)], resize_keyboard=True)
        await self._send_customer_payload(context, user_id, payload, keyboard)

    async def send_welcome_to_user(self, context, user_id, extra_reply_markup=None, force=False):
        if not force and not should_send_welcome(self.bot_id, user_id):
            return
        messages = [m for m in get_welcome_messages(self.bot_id) if m.get('enabled', 1)]
        keyboard = extra_reply_markup or build_reply_keyboard(self.bot_id)
        notice = get_main_text('clone_trial_notice') if self.get_bot_info().get('version', '普通版') == '普通版' else ''
        for index, row in enumerate(messages):
            await self._send_customer_payload(context, user_id, self._legacy_payload(row), keyboard if index == len(messages)-1 and not notice else None)
        if not messages:
            welcome = get_setting(self.bot_id, 'welcome_text', '') or self.get_bot_info().get('welcome_text') or '欢迎，请发送消息，客服会尽快回复。'
            await send_payload(context.bot, user_id, {'type': 'text', 'text': welcome, 'legacy_html': True}, reply_markup=keyboard if not notice else None)
        if notice:
            await send_payload(context.bot, user_id, {'type': 'text', 'text': notice, 'legacy_html': True}, reply_markup=keyboard)
        update_user_welcome_time(self.bot_id, user_id)

    def _legacy_payload(self, row, auto=False):
        raw = row.get('payload')
        if raw:
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if payload:
                return payload
        return {'type': row.get('reply_type' if auto else 'content_type', 'text'), 'text': row.get('reply_text' if auto else 'content_text', '') or '', 'file_id': row.get('file_id', ''), 'legacy_html': True}

    @paced_entry
    async def callback_handler(self, update, context):
        query = update.callback_query
        data = query.data or ''
        legacy = {'cad:welcome_back': 'list:welcome', 'cad:welcome_add': 'cfg:welcome:add', 'cad:ar_back': 'list:ar', 'cad:ar_add': 'cfg:ar:add'}
        for old, new in {'cad:welcome_view:': 'cfg:welcome:view:', 'cad:welcome_del:': 'cfg:welcome:delete:', 'cad:ar_view:': 'cfg:ar:view:', 'cad:ar_edit:': 'cfg:ar:edit:', 'cad:ar_del:': 'cfg:ar:delete:'}.items():
            if data.startswith(old):
                data = new + data[len(old):]
                break
        query = _CallbackAlias(query, legacy.get(data, data))
        if not self._admin(query.from_user.id):
            await query.answer('无权操作', show_alert=True)
            return
        try:
            await query.answer()
            if not self._admin(query.from_user.id):
                return
            if await self._config_callback(query, context):
                return
            if await self._group_callback(query, context):
                return
            await self._ui_callback(query, context)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            await self._say(query, str(exc)[:300] or '无效操作')

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
