# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Customer workbench and persistent broadcast controls."""
from __future__ import annotations

import json
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .common import *

LABELS = {'welcome': '欢迎语', 'ar': '自动回复', 'filter': '过滤规则', 'command': '指令'}


class CloneUIMixin:
    def _case_markup(self, uid):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton('选择客户', callback_data=f'switch:{uid}'), InlineKeyboardButton('认领', callback_data=f'case:claim:{uid}')],
            [InlineKeyboardButton('转交', callback_data=f'case:transfer:{uid}'), InlineKeyboardButton('关闭', callback_data=f'case:close:{uid}'), InlineKeyboardButton('备注', callback_data=f'case:note:{uid}')],
            [InlineKeyboardButton('禁言1天', callback_data=f'mute:{uid}:1d'), InlineKeyboardButton('禁言1周', callback_data=f'mute:{uid}:1w'), InlineKeyboardButton('禁言1月', callback_data=f'mute:{uid}:1m')],
            [InlineKeyboardButton('永久禁言', callback_data=f'mute:{uid}:forever'), InlineKeyboardButton('解除禁言', callback_data=f'unblock:{uid}')]])

    async def _show_admin_panel(self, target, context, bot_info=None):
        if hasattr(target, 'effective_message'):
            target = target.effective_message
        actor = target.from_user.id if hasattr(target, 'edit_message_text') else target.chat.id
        conv = get_conversation(self.bot_id, actor)
        current = conv.get('current_user_id') if conv else None
        text = f"客服工作台\n版本：{self.get_bot_info().get('version', '普通版')}\n待回复：{len(self._pending())}\n你的当前客户：{current or '未选择'}"
        keys = [('客户', 'cad:cad_clients'), ('统计', 'cad:cad_stats'), ('欢迎语', 'list:welcome'), ('自动回复', 'list:ar'), ('底部键盘', 'menu:keyboard'), ('黑名单', 'menu:blacklist'), ('过滤规则', 'list:filter'), ('群组频道', 'menu:groups'), ('入群欢迎', 'menu:groups'), ('广播', 'menu:broadcast'), ('访客提醒', 'menu:visitor'), ('管理员', 'menu:admins'), ('指令', 'list:command'), ('频道验证', 'menu:verification'), ('客服分流', 'menu:routing')]
        await self._say(target, text, [keys[i:i+2] for i in range(0, len(keys), 2)])

    async def _clients(self, target, page=1, pending=False):
        users = self._pending() if pending else self._rows('SELECT u.*,c.assigned_admin_id,c.state,c.notes FROM users u LEFT JOIN client_cases c ON c.bot_id=u.bot_id AND c.user_id=u.user_id WHERE u.bot_id=? ORDER BY COALESCE(c.last_inbound_at,0) DESC,u.id DESC')
        pages = max(1, (len(users)+9)//10)
        page = min(max(1, page), pages)
        lines, rows = [f"{'待回复' if pending else '共享客户'}：{len(users)} · {page}/{pages}"], []
        for user in users[(page-1)*10:page*10]:
            uid = user['user_id']
            name = user.get('first_name') or user.get('username') or str(uid)
            lines.append(f"{name} ({uid}) · 客服{user.get('assigned_admin_id') or '未认领'} · {user.get('state') or 'OPEN'}")
            rows.append([(name[:35], f'case:view:{uid}')])
        rows += [[('上一页', f'clients:{max(1,page-1)}:{int(pending)}'), ('下一页', f'clients:{min(pages,page+1)}:{int(pending)}')], [('仅待回复', 'clients:1:1'), ('全部客户', 'clients:1:0')], [('管理面板', 'cad:back_panel')]]
        await self._say(target, '\n'.join(lines), rows)

    async def _resource_list(self, target, kind, page=1):
        from .clone_config import TABLES
        order = 'command' if kind == 'command' else 'sort_order,id' if kind in ('welcome', 'ar') else 'id'
        resources = self._rows(f'SELECT * FROM {TABLES[kind]} WHERE bot_id=? ORDER BY {order}')
        pages = max(1, (len(resources)+19)//20)
        page = min(max(1, page), pages)
        rows = []
        for item in resources[(page-1)*20:page*20]:
            rid = item.get('id', item.get('command'))
            label = item.get('keyword') or item.get('command') or item.get('pattern') or f'欢迎语 {rid}'
            rows.append([(f"{'开' if item.get('enabled') else '关'} · {str(label)[:35]}", f'cfg:{kind}:view:{rid}')])
        rows += [[('上一页', f'list:{kind}:{max(1,page-1)}'), ('下一页', f'list:{kind}:{min(pages,page+1)}')], [('添加', f'cfg:{kind}:add'), ('管理面板', 'cad:back_panel')]]
        await self._say(target, f'{LABELS[kind]}：{len(resources)}条 · {page}/{pages}', rows)

    async def _blacklist(self, target, search=''):
        users = self._rows('SELECT b.*,u.first_name,u.username FROM blacklist b LEFT JOIN users u ON u.bot_id=b.bot_id AND u.user_id=b.user_id WHERE b.bot_id=? ORDER BY b.user_id')
        # Expiry is checked through the same helper used by customer entry points.
        users = [u for u in users if is_blocked(self.bot_id, u['user_id']) and (not search or search.casefold() in f"{u['user_id']} {u.get('first_name')} {u.get('username')}".casefold())]
        rows = [[(f"解禁 {u.get('first_name') or u['user_id']}", f"unblock:{u['user_id']}")] for u in users[:80]]
        rows += [[('搜索', 'blacklist:search'), ('管理面板', 'cad:back_panel')]]
        await self._say(target, f'有效黑名单：{len(users)}条', rows)

    def _apply_case(self, db, actor, data):
        uid, op = int(data['user_id']), data['op']
        if not db.execute('SELECT 1 FROM users WHERE bot_id=? AND user_id=?', (self.bot_id, uid)).fetchone():
            raise ValueError('客户不存在')
        db.execute("INSERT OR IGNORE INTO client_cases(bot_id,user_id,state) VALUES(?,?,'OPEN')", (self.bot_id, uid))
        if op == 'claim':
            changed = db.execute("UPDATE client_cases SET assigned_admin_id=?,state='OPEN' WHERE bot_id=? AND user_id=? AND (assigned_admin_id IS NULL OR assigned_admin_id=?)", (actor, self.bot_id, uid, actor)).rowcount
            if not changed:
                raise ValueError('客户已被其他客服认领')
        elif op == 'transfer':
            target = int(data['target'])
            if not self._admin(target):
                raise ValueError('接收人已不是客服')
            db.execute('UPDATE client_cases SET assigned_admin_id=? WHERE bot_id=? AND user_id=?', (target, self.bot_id, uid))
        elif op == 'close':
            db.execute("UPDATE client_cases SET state='CLOSED' WHERE bot_id=? AND user_id=?", (self.bot_id, uid))
        elif op == 'note':
            db.execute('UPDATE client_cases SET notes=? WHERE bot_id=? AND user_id=?', (data['notes'], self.bot_id, uid))
        elif op == 'mute':
            seconds = data['seconds']
            db.execute('INSERT OR REPLACE INTO blacklist(bot_id,user_id,reason,created_at,expires_at) VALUES(?,?,?,?,?)', (self.bot_id, uid, '客服禁言', str(time.time()), time.time()+seconds if seconds else None))
            db.execute('UPDATE users SET blocked=1 WHERE bot_id=? AND user_id=?', (self.bot_id, uid))
        elif op == 'unblock':
            db.execute('DELETE FROM blacklist WHERE bot_id=? AND user_id=?', (self.bot_id, uid))
            db.execute('UPDATE users SET blocked=0 WHERE bot_id=? AND user_id=?', (self.bot_id, uid))
        else:
            raise ValueError('客户操作无效')
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def _ui_callback(self, query, context):
        data, actor = query.data, query.from_user.id
        aliases = {'cad:cad_welcome': 'list:welcome', 'cad:cad_autoreply': 'list:ar', 'cad:cad_filter': 'list:filter', 'cad:cad_commands': 'list:command', 'cad:cad_replykb': 'menu:keyboard', 'cad:cad_blacklist': 'menu:blacklist', 'cad:cad_groups': 'menu:groups', 'cad:cad_join_welcome': 'menu:groups', 'cad:cad_broadcast': 'menu:broadcast', 'cad:cad_visitor': 'menu:visitor', 'cad:cad_admins': 'menu:admins'}
        data = aliases.get(data, data)
        if data in ('cad:back_panel', 'cad:cad_stats_home', 'cfg:cancel'):
            self._cancel(actor)
            await self._show_admin_panel(query, context)
        elif data in ('cad:cad_clients', 'cad:cad_stats_clients') or data.startswith(('user_list:', 'user_page:', 'clients:')):
            parts = data.split(':')
            await self._clients(query, int(parts[1]) if parts[0] in ('user_list', 'user_page', 'clients') else 1, pending=parts[0] == 'clients' and parts[2] == '1')
        elif data in ('cad:cad_stats', 'cad:cad_stats_refresh'):
            stats = get_bot_stats(self.bot_id)
            stats['pending'] = len(self._pending())
            await self._say(query, '\n'.join(f'{k}: {v}' for k, v in stats.items()), [[('刷新', 'cad:cad_stats_refresh'), ('待回复', 'clients:1:1')], [('管理面板', 'cad:back_panel')]])
        elif data.startswith('list:'):
            self._cancel(actor)
            parts = data.split(':')
            await self._resource_list(query, parts[1], int(parts[2]) if len(parts) > 2 else 1)
        elif data.startswith('switch:') or data.startswith('cad:switch:'):
            uid = int(data.split(':')[-1])
            if not get_user(self.bot_id, uid):
                raise ValueError('客户不存在')
            set_conversation(self.bot_id, actor, uid)
            await self._say(query, f'你的当前客户已切换为 {uid}。', [[('客户详情', f'case:view:{uid}'), ('管理面板', 'cad:back_panel')]])
        elif data.startswith('case:'):
            parts = data.split(':')
            op, uid = parts[1], int(parts[2])
            if not get_user(self.bot_id, uid):
                raise ValueError('客户不存在')
            if op == 'view':
                case = self._case(uid) or {}
                await query.edit_message_text(f"客户 {uid}\n客服：{case.get('assigned_admin_id') or '未认领'}\n状态：{case.get('state', 'OPEN')}\n备注：{case.get('notes', '')}", reply_markup=self._case_markup(uid))
            elif op == 'transfer' and len(parts) == 3:
                await self._say(query, '选择接收客服', [[(str(admin), f'case:transfer:{uid}:{admin}')] for admin in get_bot_admins(self.bot_id) if self._admin(admin)])
            elif op == 'note':
                self._draft(actor, 'note', {'kind': 'case', 'op': op, 'user_id': uid})
                await self._say(query, '发送客户备注。')
            else:
                await self._preview(query, context, actor, {'kind': 'case', 'op': op, 'user_id': uid, **({'target': int(parts[3])} if op == 'transfer' else {})})
        elif data.startswith(('mute:', 'unblock:')):
            parts = data.split(':')
            duration = {'1d': 86400, '1w': 604800, '1m': 2592000, 'forever': None}
            draft = {'kind': 'case', 'op': 'mute' if parts[0] == 'mute' else 'unblock', 'user_id': int(parts[1])}
            if parts[0] == 'mute':
                draft['seconds'] = duration[parts[2]]
            await self._preview(query, context, actor, draft)
        elif data == 'blacklist:search':
            self._draft(actor, 'blacklist_search', {'kind': 'blacklist'})
            await self._say(query, '发送用户ID、姓名或用户名。')
        elif data.startswith('menu:'):
            kind = data.split(':')[1]
            if kind == 'blacklist':
                await self._blacklist(query)
            elif kind == 'groups':
                await self._groups(query)
            elif kind == 'broadcast':
                await self._broadcast_list(query)
            else:
                details = {'keyboard': get_reply_kb_config(self.bot_id), 'admins': get_bot_admins(self.bot_id), 'visitor': {k: get_setting(self.bot_id, k, '') for k in ('visitor_notify', 'visitor_reminder_enabled', 'visitor_reminder_seconds', 'visitor_reminder_limit')}, 'routing': get_setting(self.bot_id, 'routing_mode', 'shared'), 'verification': {'channel_id': self.get_bot_info().get('channel_id'), 'channel_link': get_setting(self.bot_id, 'channel_link', '')}}
                await self._say(query, json.dumps(details[kind], ensure_ascii=False, indent=2)[:3500], [[('修改', f'cfg:{kind}:edit'), ('管理面板', 'cad:back_panel')]])
        elif data.startswith('broadcast:'):
            parts = data.split(':')
            job = int(parts[2])
            from .broadcast import broadcasts
            row = self._row('SELECT id FROM broadcast_jobs WHERE bot_id=? AND id=?', (job,))
            if not row:
                raise ValueError('广播不属于当前机器人')
            if parts[1] not in ('view', 'unknown'):
                if parts[1] == 'retry_unknown' and len(parts) < 4:
                    await self._say(query, '结果未知的收件人可能已经收到；重试可能重复发送。确定？', [[('确认重试', f'broadcast:retry_unknown:{job}:yes'), ('返回', f'broadcast:view:{job}')]])
                    return
                broadcasts.action(job, actor, parts[1])
            await self._broadcast_detail(query, actor, job)
        elif data in ('noop', 'cad:cad_vip'):
            await self._say(query, '高级功能权限与升级请前往主机器人。', [[('管理面板', 'cad:back_panel')]])
        else:
            raise ValueError('旧按钮已失效，请重新打开 /admin。')

    async def _broadcast_list(self, target):
        jobs = self._rows('SELECT id,status FROM broadcast_jobs WHERE bot_id=? ORDER BY id DESC LIMIT 20')
        rows = [[(f"#{j['id']} {j['status']}", f"broadcast:view:{j['id']}")] for j in jobs]
        rows += [[('新广播', 'cfg:broadcast:add'), ('管理面板', 'cad:back_panel')]]
        await self._say(target, '广播队列', rows)

    async def _broadcast_detail(self, target, actor, job):
        from .broadcast import broadcasts
        stats = broadcasts.stats(job, actor)
        await self._say(target, json.dumps(stats, ensure_ascii=False, default=str)[:3500],
                        [[('刷新', f'broadcast:view:{job}'), ('暂停', f'broadcast:pause:{job}'), ('恢复', f'broadcast:resume:{job}')],
                         [('重试未知（有重复风险）', f'broadcast:retry_unknown:{job}'), ('跳过未知', f'broadcast:skip_unknown:{job}')],
                         [('取消任务', f'broadcast:cancel:{job}'), ('广播列表', 'menu:broadcast')]])

    async def reminder_tick(self, bot):
        if get_setting(self.bot_id, 'visitor_reminder_enabled', '0') != '1':
            return
        delay = max(60, int(get_setting(self.bot_id, 'visitor_reminder_seconds', '1800')))
        limit = max(1, int(get_setting(self.bot_id, 'visitor_reminder_limit', '3')))
        now = time.time()
        for case in self._pending():
            if case['reminder_count'] >= limit or now - max(case.get('last_reminded_at') or 0, case['last_inbound_at']) < delay:
                continue
            admins = [case['assigned_admin_id']] if case.get('assigned_admin_id') and self._admin(case['assigned_admin_id']) else get_bot_admins(self.bot_id)
            for admin in admins:
                if self._admin(admin):
                    try:
                        await self._staff_send(bot, admin, 'send_message', text=f"客户 {case['user_id']} 仍待回复。", reply_markup=self._case_markup(case['user_id']))
                    except TelegramError:
                        continue
            with transaction() as db:
                db.execute('UPDATE client_cases SET reminder_count=reminder_count+1,last_reminded_at=? WHERE bot_id=? AND user_id=?', (now, self.bot_id, case['user_id']))

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
