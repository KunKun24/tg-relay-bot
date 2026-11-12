# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Single platform administrator pages, pagination and confirmed VIP grants."""
from __future__ import annotations

import math
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from .config import MAIN_ADMIN_ID
from .database import get_db, transaction
from .configuration import get_vip_features
from .main_sessions import put_session, get_session, validate_session_actor, consume_session, MessageQuery


class MainAdminMixin:
    async def _show_admin_panel(self, query):
        if query.from_user.id != MAIN_ADMIN_ID:
            raise PermissionError("无权操作")
        rows = [[B("📝 文案设置", callback_data="admin:texts"), B("🔘 按钮设置", callback_data="admin:buttons")],
                [B("💳 支付设置", callback_data="admin:okpay"), B("⚙️ 普通版额度", callback_data="admin:limits")],
                [B("👥 用户列表", callback_data="admin:users:1"), B("🤖 机器人列表", callback_data="admin:bots:1")],
                [B("🧾 订单列表", callback_data="admin:orders:1"), B("💎 手动开通", callback_data="admin:manual_vip")],
                [B("🔐 VIP功能开关", callback_data="admin:vip_features")],
                [B("📣 主平台公告", callback_data="admin:broadcast"), B("▶️ 重发主平台欢迎语", callback_data="admin:mass_start")],
                [B("📋 广播任务", callback_data="admin:jobs:1")], [B("🏠 首页", callback_data="main:home")]]
        await query.edit_message_text("⚙️ 主平台管理后台", reply_markup=K(rows))

    async def _show_admin_list(self, query, kind, page=1):
        con = get_db()
        configs = {"users": ("main_users", "created_at DESC", "用户"), "bots": ("bots", "id DESC", "机器人"),
                   "orders": ("orders", "id DESC", "订单"), "jobs": ("broadcast_jobs", "id DESC", "广播任务")}
        table, order, label = configs[kind]
        where = " WHERE bot_id=0" if kind == "jobs" else ""
        total = con.execute(f"SELECT COUNT(*) FROM {table}{where}").fetchone()[0]
        pages = max(1, math.ceil(total / 8))
        page = max(1, min(int(page), pages))
        rows = con.execute(f"SELECT * FROM {table}{where} ORDER BY {order} LIMIT 8 OFFSET ?", ((page - 1) * 8,)).fetchall()
        lines, buttons = [f"📋 {label}列表 · 总计{total} · 第{page}/{pages}页"], []
        for raw in rows:
            item = dict(raw)
            if kind == "users":
                lines.append(f"\n{item['user_id']} · {item.get('first_name') or ''} · @{item.get('username') or '-'}\n最近：{item.get('last_seen') or '-'}")
            elif kind == "bots":
                lines.append(f"\n#{item['id']} @{item['bot_username']} · owner {item['owner_id']}\n{item.get('desired_state')}/{item.get('actual_state')} · {item.get('version')} · {item.get('expire_time') or '-'}")
                buttons.append([B(f"⚙️ #{item['id']} 管理", callback_data=f"admin:bot:{item['id']}")])
            elif kind == "orders":
                lines.append(f"\n{item['order_no']} · {item['plan_name']}\n{item['amount']} {item.get('currency') or 'USDT'} · {item['status']} · owner {item['owner_id']} · bot {item['bot_id']}")
            else:
                lines.append(f"\n#{item['id']} · {item['status']}")
                buttons.append([B(f"📣 任务 #{item['id']}", callback_data=f"main_job:{item['id']}")])
        nav = []
        if page > 1:
            nav.append(B("⬅️ 上一页", callback_data=f"admin:{kind}:{page-1}"))
        if page < pages:
            nav.append(B("下一页 ➡️", callback_data=f"admin:{kind}:{page+1}"))
        if nav:
            buttons.append(nav)
        buttons.append([B("🔙 返回", callback_data="admin:back")])
        await query.edit_message_text("\n".join(lines), reply_markup=K(buttons))

    async def _show_vip_features(self, query):
        features = get_vip_features()
        rows = [[B(f"{'🔒 专业版' if val['enabled'] else '🔓 所有人'} · {val['name']}", callback_data=f"admin:vip_toggle:{key}")] for key, val in features.items()]
        rows.append([B("🔙 返回", callback_data="admin:back")])
        await query.edit_message_text("🔐 VIP功能要求\n关闭要求后，普通用户也可使用该功能；既有资源不会被删除。", reply_markup=K(rows))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


    async def _admin_callback(self, query, context):
        parts = query.data.split(":")
        if query.from_user.id != MAIN_ADMIN_ID:
            raise PermissionError("无权操作")
        if query.data in ("main:admin", "admin:back"):
            await self._show_admin_panel(query)
        elif len(parts) == 3 and parts[1] in ("users", "bots", "orders", "jobs"):
            await self._show_admin_list(query, parts[1], int(parts[2]))
        elif query.data == "admin:vip_features":
            await self._show_vip_features(query)
        elif query.data.startswith("admin:vip_toggle:"):
            features = get_vip_features()
            if parts[2] not in features:
                raise ValueError("功能不存在")
            target = 0 if features[parts[2]]["enabled"] else 1
            nonce = put_session(query.from_user.id, "vip_toggle_confirm", {"admin": True, "key": parts[2], "enabled": target})
            await query.edit_message_text(f"确认把 {features[parts[2]]['name']} 设为{'仅专业版' if target else '所有用户可用'}？", reply_markup=K([
                [B("✅ 确认", callback_data=f"vip_toggle_confirm:{nonce}")], [B("❌ 取消", callback_data="admin:vip_features")]]))
        elif query.data.startswith("vip_toggle_confirm:"):
            session = get_session(query.from_user.id, parts[1])
            data = validate_session_actor(session, query.from_user.id)
            if session["state"] != "vip_toggle_confirm":
                raise ValueError("操作已过期")
            consume_session(query.from_user.id, parts[1])
            with transaction() as con:
                con.execute("UPDATE vip_features SET enabled=? WHERE key=?", (data["enabled"], data["key"]))
            await self._show_vip_features(query)
        elif query.data == "admin:manual_vip":
            put_session(query.from_user.id, "manual_vip_input", {"admin": True})
            await query.edit_message_text("请输入：机器人ID 套餐\n套餐为 1m / 3m / forever，例如 12 1m\n提交后需再次确认。", reply_markup=K([[B("🔙 返回", callback_data="admin:back")]]))
        elif query.data.startswith("manual_vip_confirm:"):
            session = get_session(query.from_user.id, parts[1])
            data = validate_session_actor(session, query.from_user.id)
            if session["state"] != "manual_vip_confirm":
                raise ValueError("操作已过期")
            consume_session(query.from_user.id, parts[1])
            from .payments import activate_vip
            activate_vip(data["bot_id"], data["plan"])
            await query.edit_message_text("✅ 高级版已开通。", reply_markup=K([[B("🔙 返回", callback_data="admin:back")]]))
        elif query.data.startswith("admin:bot:"):
            bot_id = int(parts[2])
            from .main_sessions import owner_bot
            bot = owner_bot(bot_id, query.from_user.id, platform=True)
            await query.edit_message_text(f"🤖 #{bot_id} @{bot['bot_username']}\nowner {bot['owner_id']}\n{bot.get('desired_state')}/{bot.get('actual_state')}\nToken不展示。", reply_markup=K([
                [B("🔄 平台重启", callback_data=f"admin:lifecycle:restart:{bot_id}"), B("⛔ 平台断开", callback_data=f"admin:lifecycle:disconnect:{bot_id}")],
                [B("✅ 平台恢复", callback_data=f"admin:lifecycle:reconnect:{bot_id}"), B("🗑️ 平台删除", callback_data=f"admin:lifecycle:delete:{bot_id}")],
                [B("🔙 返回", callback_data="admin:bots:1")]]))
        elif query.data.startswith("admin:lifecycle:"):
            kind, bot_id = parts[2], int(parts[3])
            if kind not in ("restart", "disconnect", "reconnect", "delete"):
                raise ValueError("操作不存在")
            nonce = put_session(query.from_user.id, "admin_lifecycle_confirm", {"admin": True, "platform": True, "bot_id": bot_id, "action": kind})
            await query.edit_message_text(f"⚠️ 确认平台 {kind} 机器人 #{bot_id}？删除不可恢复。", reply_markup=K([
                [B("✅ 确认", callback_data=f"admin_lifecycle_confirm:{nonce}")], [B("❌ 取消", callback_data="admin:bots:1")]]))
        elif query.data.startswith("admin_lifecycle_confirm:"):
            session = get_session(query.from_user.id, parts[1])
            data = validate_session_actor(session, query.from_user.id)
            if session["state"] != "admin_lifecycle_confirm":
                raise ValueError("操作已过期")
            consume_session(query.from_user.id, parts[1])
            await getattr(self, {"restart": "_restart_clone_bot", "disconnect": "_disconnect_clone_bot", "reconnect": "_reconnect_clone_bot", "delete": "_delete_clone_bot"}[data["action"]])(data["bot_id"], actor_id=query.from_user.id)
            await self._show_admin_list(query, "bots")
        else:
            return False
        return True

    async def _manual_vip_text(self, update, session):
        validate_session_actor(session, update.effective_user.id)
        text = (update.effective_message.text or "").split()
        if len(text) != 2 or not text[0].isdigit() or text[1] not in ("1m", "3m", "forever"):
            raise ValueError("格式错误，请输入：机器人ID 1m/3m/forever")
        from .main_sessions import owner_bot
        bot = owner_bot(int(text[0]), update.effective_user.id, platform=True)
        nonce = put_session(update.effective_user.id, "manual_vip_confirm", {"admin": True, "platform": True, "bot_id": bot["id"], "plan": text[1]})
        await update.effective_message.reply_text(f"确认给机器人 #{bot['id']} @{bot['bot_username']} 开通 {text[1]}？", reply_markup=K([
            [B("✅ 确认开通", callback_data=f"manual_vip_confirm:{nonce}")], [B("❌ 取消", callback_data="admin:back")]]))

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
