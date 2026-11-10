# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Persistent preview/confirm configuration, never active partial drafts."""
from __future__ import annotations

import json
import re
import time
import regex
from .common import *

TABLES = {'welcome': 'welcome_messages', 'ar': 'auto_replies', 'filter': 'filter_rules', 'command': 'commands'}
FEATURES = {'welcome': 'custom_welcome', 'ar': 'auto_reply', 'broadcast': 'broadcast'}


class CloneConfigMixin:
    async def _preview(self, target, context, actor, data):
        payload = data.get('payload')
        if payload:
            await send_payload(context.bot, actor, payload)
        nonce = self._draft(actor, 'confirm', data)
        summary = {k: v for k, v in data.items() if k != 'payload'}
        await self._say(target, '确认以下配置（15分钟内有效）：\n' + json.dumps(summary, ensure_ascii=False, indent=2)[:3500],
                        [[('确认', f'cfg:confirm:{nonce}'), ('取消', 'cfg:cancel')]])

    async def _config_callback(self, query, context):
        data, actor = query.data, query.from_user.id
        if data == 'cfg:cancel':
            self._cancel(actor)
            await self._show_admin_panel(query, context)
            return True
        if data.startswith('cfg:confirm:'):
            session = self._session(actor)
            if not session or session['nonce'] != data.split(':')[2]:
                raise ValueError('确认已过期或已处理')
            draft = session['data']
            if not self._admin(actor):
                raise ValueError('无权操作')
            if draft.get('kind') in ('admins',) and actor != self.get_admin_id():
                raise ValueError('仅所有者可修改管理员')
            if draft.get('kind') in FEATURES and draft.get('op') != 'delete':
                require_capability(self.bot_id, FEATURES[draft['kind']])
            if draft.get('kind') == 'group' and draft.get('op') != 'delete':
                await self._check_group(context, draft['chat_id'], actor)
            if draft.get('kind') == 'verification' and draft.get('channel_id'):
                await self._check_group(context, draft['channel_id'], actor)
            def apply(db, draft_data):
                self._apply_config(db, actor, draft_data)
                if draft_data['kind'] == 'broadcast':
                    from .broadcast import broadcasts
                    return broadcasts.create_in_transaction(db, self.bot_id, actor, draft_data['payload'], query.message.chat.id, query.message.message_id)
            result = self._consume(actor, data.split(':')[2], apply)
            if draft['kind'] == 'broadcast':
                await self._broadcast_detail(query, actor, result)
            else:
                self._verified_cache.clear()
                await self._say(query, '配置已保存。', [[('管理面板', 'cad:back_panel')]])
            return True
        if data == 'cfg:replykb':
            session = self._session(actor)
            if not session or session['data'].get('kind') != 'ar' or 'payload' not in session['data']:
                raise ValueError('自动回复草稿已过期')
            self._draft(actor, 'ar_replykb', session['data'])
            await self._say(query, '发送底部键盘JSON：{"enabled":true,"per_row":2,"buttons":[{"text":"咨询","color":"primary","emoji_id":""}]}。')
            return True
        if data.startswith('cfg:buttons'):
            session = self._session(actor)
            if not session or 'payload' not in session['data']:
                raise ValueError('草稿已过期')
            self._draft(actor, 'buttons', session['data'])
            await self._say(query, '发送按钮：文字|URL，每行一组，同行用 && 分隔；可附 #p/#g/#r 和会员表情。发送 无 清空。')
            return True
        if data.startswith('cfg:'):
            parts = data.split(':')
            kind, op = parts[1:3]
            if kind not in TABLES and kind not in ('keyboard', 'visitor', 'admins', 'verification', 'routing', 'broadcast'):
                return False
            if kind == 'admins' and actor != self.get_admin_id():
                raise ValueError('仅所有者可修改管理员')
            if kind in FEATURES and op not in ('delete', 'view'):
                require_capability(self.bot_id, FEATURES[kind])
            rid = parts[3] if len(parts) > 3 else None
            if kind in TABLES and op in ('view', 'edit', 'delete', 'toggle', 'up', 'down'):
                column = 'command' if kind == 'command' else 'id'
                row = self._row(f'SELECT * FROM {TABLES[kind]} WHERE bot_id=? AND {column}=?', (rid,))
                if not row:
                    raise ValueError('资源不存在')
                if op == 'view':
                    if kind in ('welcome', 'ar'):
                        await send_payload(context.bot, actor, self._legacy_payload(row, auto=kind == 'ar'))
                    await self._say(query, json.dumps({k: v for k, v in row.items() if k != 'payload'}, ensure_ascii=False)[:3500],
                                    [[('编辑', f'cfg:{kind}:edit:{rid}'), ('开关', f'cfg:{kind}:toggle:{rid}')],
                                     [('上移', f'cfg:{kind}:up:{rid}'), ('下移', f'cfg:{kind}:down:{rid}')],
                                     [('删除', f'cfg:{kind}:delete:{rid}'), ('返回', f'list:{kind}')]])
                    return True
                if op != 'edit':
                    if op in ('up', 'down') and kind not in ('welcome', 'ar'):
                        raise ValueError('此类资源无排序字段')
                    await self._preview(query, context, actor, {'kind': kind, 'op': op, 'id': rid})
                    return True
            draft = {'kind': kind, 'op': 'save', 'id': rid}
            if kind in ('welcome', 'broadcast'):
                state, prompt = 'payload', '发送完整内容（支持文字、媒体及会员表情），先预览再确认。'
            elif kind == 'ar':
                state, prompt = 'ar_keyword', '发送 匹配模式|关键词，模式为 contains、exact 或 regex。'
            elif kind == 'command':
                state, prompt = 'command_header', '发送 指令名|描述（不含 /），随后发送回复内容。'
            else:
                state = 'json'
                prompts = {
                    'filter': '发送 JSON：{"pattern":"关键词","mode":"contains","action":"warn","duration_seconds":3600}；mode支持contains/exact/regex，action支持warn/block/mute。',
                    'keyboard': '发送 JSON：{"enabled":true,"per_row":2,"buttons":[{"text":"咨询","color":"primary","emoji_id":""}]}。文字中的会员表情实体会自动提取图标；颜色支持default/primary/success/danger。',
                    'visitor': '发送 JSON：{"notify":true,"reminder_enabled":true,"reminder_seconds":1800,"reminder_limit":3}。',
                    'admins': '发送 JSON：{"add":[123456],"remove":[]}。所有者不可删除。',
                    'verification': '发送 JSON：{"channel_id":"@频道","channel_link":"https://t.me/频道","verify_text":"请先加入频道"}；channel_id留空关闭验证。',
                    'routing': '发送 JSON：{"mode":"shared"} 或 {"mode":"balanced"}。共享模式分发所有客服，均衡模式按当前开放客户数分配。',
                }
                prompt = prompts[kind]
            self._draft(actor, state, draft)
            await self._say(query, prompt, [[('取消', 'cfg:cancel')]])
            return True
        return False
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def _config_input(self, update, context):
        actor, msg = update.effective_user.id, update.effective_message
        session = self._session(actor)
        if not session:
            return False
        if not self._admin(actor):
            self._cancel(actor)
            return True
        state, data = session['state'], session['data']
        if state == 'confirm':
            await msg.reply_text('有配置等待确认；请确认、取消或使用 /clear。当前消息未转发。')
            return True
        text = msg.text or ''
        try:
            if data['kind'] == 'admins' and actor != self.get_admin_id():
                raise ValueError('仅所有者可修改管理员')
            if state == 'ar_keyword':
                mode, keyword = text.split('|', 1)
                self._validate_pattern(mode.strip(), keyword)
                data.update(match_mode=mode.strip(), keyword=keyword)
                self._draft(actor, 'payload', data)
                await msg.reply_text('发送完整自动回复内容。')
            elif state == 'command_header':
                command, description = text.split('|', 1)
                if not re.fullmatch('[a-z0-9_]{1,32}', command):
                    raise ValueError('指令名仅支持1-32位小写字母、数字、下划线')
                if command in ('start', 'admin', 'users', 'clear', 'bind'):
                    raise ValueError('不能覆盖内置指令')
                data.update(command=command, description=description[:256])
                self._draft(actor, 'payload', data)
                await msg.reply_text('发送指令回复内容。')
            elif state == 'payload':
                data['payload'] = capture_payload(msg.reply_to_message or msg)
                await self._preview(msg, context, actor, data)
                rows = [[('配置内联按钮', 'cfg:buttons')]]
                if data['kind'] == 'ar':
                    rows[0].append(('配置底部键盘', 'cfg:replykb'))
                await self._say(msg, '可继续配置按钮。', rows)
            elif state == 'buttons':
                data['payload']['buttons'] = [] if text.strip() == '无' else parse_inline_buttons(text, msg.entities or ())
                await self._preview(msg, context, actor, data)
            elif state == 'ar_replykb':
                values = json.loads(text)
                if not isinstance(values, dict):
                    raise ValueError('需发送JSON对象')
                self._validate_config('keyboard', values, msg)
                data['reply_kb'] = values
                await self._preview(msg, context, actor, data)
            elif state == 'json':
                values = json.loads(text)
                if not isinstance(values, dict):
                    raise ValueError('需发送JSON对象')
                if {'kind', 'op', 'id', 'payload'} & values.keys():
                    raise ValueError('JSON不能覆盖内部操作字段')
                self._validate_config(data['kind'], values, msg)
                data.update(values)
                await self._preview(msg, context, actor, data)
            elif state == 'note':
                data['notes'] = text[:4000]
                await self._preview(msg, context, actor, data)
            elif state == 'blacklist_search':
                self._cancel(actor)
                await self._blacklist(msg, text)
            elif state in ('group_bind', 'group_welcome'):
                await self._group_input(update, context, session)
            else:
                return False
        except (ValueError, TypeError, KeyError, regex.error) as exc:
            await msg.reply_text('输入无效：' + str(exc)[:250])
        return True

    def _validate_pattern(self, mode, pattern):
        if mode not in ('contains', 'exact', 'regex') or not pattern or len(pattern) > 1000:
            raise ValueError('匹配模式或关键词无效')
        if mode == 'regex':
            regex.compile(pattern)

    def _validate_config(self, kind, values, message=None):
        if kind == 'filter':
            self._validate_pattern(values.get('mode', 'contains'), values.get('pattern', ''))
            if values.get('action') not in ('warn', 'block', 'mute'):
                raise ValueError('过滤动作无效')
            values['duration_seconds'] = max(1, min(31536000, int(values.get('duration_seconds', 3600))))
        elif kind == 'keyboard':
            values['per_row'] = max(1, min(4, int(values.get('per_row', 2))))
            if not isinstance(values.get('buttons'), list) or len(values['buttons']) > 100:
                raise ValueError('按钮列表无效')
            for button in values['buttons']:
                if not isinstance(button, dict) or not str(button.get('text', '')).strip():
                    raise ValueError('按钮文字不能为空')
                if button.get('color', 'default') not in ('default', 'primary', 'success', 'danger'):
                    raise ValueError('按钮颜色无效')
                eid = str(button.get('emoji_id') or '')
                if eid and not eid.isdigit():
                    raise ValueError('会员图标ID必须为数字字符串')
                button['emoji_id'] = eid
            emoji = next((str(e.custom_emoji_id) for e in (message.entities or ()) if e.type == 'custom_emoji'), '') if message else ''
            if emoji and values['buttons']:
                values['buttons'][0]['emoji_id'] = emoji
        elif kind == 'routing' and values.get('mode') not in ('shared', 'balanced'):
            raise ValueError('分流模式无效')
        elif kind == 'visitor':
            values['reminder_seconds'] = max(60, int(values.get('reminder_seconds', 1800)))
            values['reminder_limit'] = max(1, min(100, int(values.get('reminder_limit', 3))))
        elif kind == 'admins':
            for key in ('add', 'remove'):
                if not isinstance(values.get(key, []), list):
                    raise ValueError('管理员列表无效')
                values[key] = [int(v) for v in values.get(key, [])]
                if any(v <= 0 for v in values[key]):
                    raise ValueError('管理员ID必须为正整数')

    def _apply_config(self, db, actor, data):
        if not self._admin(actor):
            raise ValueError('无权操作')
        kind, op = data['kind'], data.get('op', 'save')
        if kind in FEATURES and op != 'delete':
            require_capability(self.bot_id, FEATURES[kind])
        def setting(key, value):
            db.execute('INSERT OR REPLACE INTO settings(bot_id,key,value) VALUES(?,?,?)', (self.bot_id, key, str(value)))
        if kind in TABLES:
            table = TABLES[kind]
            rid = data.get('id')
            column = 'command' if kind == 'command' else 'id'
            if rid is not None and not db.execute(f'SELECT 1 FROM {table} WHERE bot_id=? AND {column}=?', (self.bot_id, rid)).fetchone():
                raise ValueError('资源不存在')
            if op == 'delete':
                db.execute(f'DELETE FROM {table} WHERE bot_id=? AND {column}=?', (self.bot_id, rid))
            elif op == 'toggle':
                db.execute(f'UPDATE {table} SET enabled=1-enabled WHERE bot_id=? AND {column}=?', (self.bot_id, rid))
            elif op in ('up', 'down'):
                row = db.execute(f'SELECT id,sort_order FROM {table} WHERE bot_id=? AND id=?', (self.bot_id, rid)).fetchone()
                ordered = list(db.execute(f'SELECT id FROM {table} WHERE bot_id=? ORDER BY sort_order,id', (self.bot_id,)))
                ids = [r[0] for r in ordered]
                index = ids.index(row['id'])
                other = index + (-1 if op == 'up' else 1)
                if 0 <= other < len(ids):
                    ids[index], ids[other] = ids[other], ids[index]
                for position, item in enumerate(ids):
                    db.execute(f'UPDATE {table} SET sort_order=? WHERE bot_id=? AND id=?', (position, self.bot_id, item))
            elif kind in ('welcome', 'ar'):
                feature = FEATURES[kind]
                require_capability(self.bot_id, feature)
                if rid is None:
                    limit_key = 'free_welcome_limit' if kind == 'welcome' else 'free_auto_reply_limit'
                    limit = int(get_setting(0, limit_key, '3' if kind == 'welcome' else '10'))
                    if self.get_bot_info().get('version') != '高级版' and db.execute(f'SELECT count(*) FROM {table} WHERE bot_id=?', (self.bot_id,)).fetchone()[0] >= limit:
                        raise ValueError(f'普通版数量上限为{limit}，已有资源保留')
                payload = data['payload']
                fields = {'payload': json.dumps(payload, ensure_ascii=False), 'enabled': 1}
                if kind == 'welcome':
                    fields.update(content_type=payload['type'], content_text=payload.get('text', ''), file_id=payload.get('file_id', ''))
                else:
                    fields.update(reply_type=payload['type'], reply_text=payload.get('text', ''), file_id=payload.get('file_id', ''), keyword=data['keyword'], match_mode=data['match_mode'], inline_kb=None)
                    if 'reply_kb' in data:
                        fields['reply_kb'] = json.dumps(data['reply_kb'], ensure_ascii=False)
                if rid is None:
                    fields.update(bot_id=self.bot_id, sort_order=db.execute(f'SELECT COALESCE(MAX(sort_order),0)+1 FROM {table} WHERE bot_id=?', (self.bot_id,)).fetchone()[0])
                    db.execute(f"INSERT INTO {table}({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", tuple(fields.values()))
                else:
                    db.execute(f"UPDATE {table} SET {','.join(k+'=?' for k in fields)} WHERE bot_id=? AND id=?", (*fields.values(), self.bot_id, rid))
            elif kind == 'filter':
                fields = ('pattern', 'mode', 'action', 'duration_seconds')
                vals = (data['pattern'], data.get('mode', 'contains'), data['action'], data['duration_seconds'])
                if rid:
                    db.execute('UPDATE filter_rules SET pattern=?,mode=?,action=?,duration_seconds=? WHERE bot_id=? AND id=?', (*vals, self.bot_id, rid))
                else:
                    db.execute('INSERT INTO filter_rules(bot_id,pattern,mode,action,duration_seconds) VALUES(?,?,?,?,?)', (self.bot_id, *vals))
            elif kind == 'command':
                if rid and rid != data['command']:
                    db.execute('DELETE FROM commands WHERE bot_id=? AND command=?', (self.bot_id, rid))
                db.execute('INSERT OR REPLACE INTO commands(bot_id,command,description,payload,enabled) VALUES(?,?,?,?,1)', (self.bot_id, data['command'], data['description'], json.dumps(data['payload'], ensure_ascii=False)))
        elif kind == 'keyboard':
            setting('reply_kb_enabled', int(bool(data.get('enabled'))))
            setting('reply_kb_per_row', data['per_row'])
            setting('reply_kb_buttons', json.dumps(data['buttons'], ensure_ascii=False))
        elif kind == 'visitor':
            for key, value in {'visitor_notify': int(bool(data.get('notify'))), 'visitor_reminder_enabled': int(bool(data.get('reminder_enabled'))), 'visitor_reminder_seconds': data['reminder_seconds'], 'visitor_reminder_limit': data['reminder_limit']}.items():
                setting(key, value)
        elif kind == 'verification':
            channel = str(data.get('channel_id', '')).strip()
            db.execute('UPDATE bots SET channel_id=? WHERE id=?', (channel, self.bot_id))
            for key in ('channel_id', 'channel_link', 'verify_text'):
                setting(key, data.get(key, ''))
            setting('verification_revision', time.time())
            db.execute('UPDATE users SET verified=0 WHERE bot_id=?', (self.bot_id,))
        elif kind == 'routing':
            setting('routing_mode', data['mode'])
        elif kind == 'admins':
            if actor != self.get_admin_id():
                raise ValueError('仅所有者可修改管理员')
            if self.get_admin_id() in data.get('remove', []):
                raise ValueError('不能删除所有者')
            for uid in data.get('add', []):
                db.execute('INSERT OR IGNORE INTO bot_admins(bot_id,admin_id,added_by,created_at) VALUES(?,?,?,?)', (self.bot_id, uid, actor, str(time.time())))
            for uid in data.get('remove', []):
                db.execute('DELETE FROM bot_admins WHERE bot_id=? AND admin_id=?', (self.bot_id, uid))
                db.execute('DELETE FROM conversations WHERE bot_id=? AND admin_id=?', (self.bot_id, uid))
                db.execute('DELETE FROM ui_sessions WHERE bot_id=? AND user_id=?', (self.bot_id, uid))
                db.execute('UPDATE client_cases SET assigned_admin_id=NULL WHERE bot_id=? AND assigned_admin_id=?', (self.bot_id, uid))
        elif kind == 'case':
            self._apply_case(db, actor, data)
        elif kind == 'group':
            self._apply_group(db, data)
        elif kind == 'broadcast':
            require_capability(self.bot_id, 'broadcast')
        else:
            raise ValueError('配置类型无效')
        db.execute('INSERT INTO audit_logs(bot_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)', (self.bot_id, actor, 'config_'+kind+'_'+op, json.dumps({'id': data.get('id')}, ensure_ascii=False), time.time()))

    async def _filter_message(self, update, context, text):
        for rule in self._rows('SELECT * FROM filter_rules WHERE bot_id=? AND enabled=1 ORDER BY id'):
            mode, pattern = rule['mode'], rule['pattern']
            try:
                matched = text.strip() == pattern.strip() if mode == 'exact' else bool(regex.search(pattern, text, regex.IGNORECASE, timeout=0.025)) if mode == 'regex' else pattern.casefold() in text.casefold()
            except (regex.error, TimeoutError):
                self._audit(0, 'filter_regex_invalid_or_timeout', {'rule_id': rule['id']})
                continue
            if matched:
                action = rule['action']
                if action == 'block':
                    block_user(self.bot_id, update.effective_user.id, '过滤规则')
                elif action == 'mute':
                    block_user(self.bot_id, update.effective_user.id, '过滤规则限时禁言', duration_seconds=rule['duration_seconds'] or 3600)
                await update.effective_message.reply_text('消息触发过滤规则，未转交客服。' if action != 'warn' else '请注意咨询内容，当前消息已拦截。')
                return True
        return False

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
