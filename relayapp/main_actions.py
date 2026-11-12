# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Confirmation driven owner actions, separate from lifecycle implementation."""
from __future__ import annotations

import html
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from .bots import get_bots_by_owner
from .configuration import set_setting
from .main_sessions import (owner_bot, put_session, get_session, validate_session_actor,
                            consume_session, MessageQuery)


class MainActionsMixin:
    async def _confirm_owner_action(self, query, action, bot_id, extra=None):
        owner_bot(bot_id, query.from_user.id)
        data = {"bot_id": bot_id, "action": action, **(extra or {})}
        nonce = put_session(query.from_user.id, "owner_confirm", data)
        labels = {"delete": "永久删除（不可恢复）", "disconnect": "断开连接", "reconnect": "恢复连接", "restart": "重启",
                  "transfer": "发起所属权转移（接收方仍需确认）", "time": "转移全部剩余专业版时间（源机器人归零）", "timezone": "修改时区"}
        await query.edit_message_text(f"⚠️ 确认{labels[action]}？\n机器人ID：{bot_id}" + (f"\n目标：{data['target_id']}" if "target_id" in data else ""), reply_markup=K([
            [B("✅ 确认", callback_data=f"owner_confirm:{nonce}")], [B("❌ 取消", callback_data=f"manage:{bot_id}")]]))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


    async def _owner_callback(self, query, context):
        parts = query.data.split(":")
        action = parts[0]
        if action == "owner_confirm":
            session = get_session(query.from_user.id, parts[1])
            data = validate_session_actor(session, query.from_user.id)
            if session["state"] != "owner_confirm":
                raise ValueError("确认已过期")
            consume_session(query.from_user.id, parts[1])
            bot_id, kind = data["bot_id"], data["action"]
            if kind == "transfer":
                from .store import request_transfer
                token = request_transfer(bot_id, query.from_user.id, data["target_id"])
                from .formatting import api_call
                await api_call(context.bot, data["target_id"], "send_message", text=f"🔄 用户 {query.from_user.id} 希望把机器人 {bot_id} 转交给你。\n确认后原管理员和旧会话将清除，15分钟内有效。", reply_markup=K([
                    [B("✅ 接受所属权", callback_data=f"transfer_accept:{token}")], [B("❌ 不接受", callback_data="main:home")]]))
                await query.edit_message_text("✅ 转移邀请已发送，等待对方确认。", reply_markup=K([[B("🔙 返回", callback_data=f"manage:{bot_id}")]]))
                return True
            if kind == "time":
                from .payments import transfer_vip_time
                transfer_vip_time(bot_id, data["target_id"], query.from_user.id)
            elif kind == "timezone":
                set_setting(bot_id, "timezone", data["value"])
            else:
                methods = {"delete": "_delete_clone_bot", "disconnect": "_disconnect_clone_bot", "reconnect": "_reconnect_clone_bot", "restart": "_restart_clone_bot"}
                await getattr(self, methods[kind])(bot_id, actor_id=query.from_user.id)
            if kind == "delete":
                await self._show_my_bots(query, query.from_user.id)
            else:
                await self._show_bot_settings(query, bot_id, context)
            return True
        if action == "transfer_accept":
            from .store import accept_transfer
            result = accept_transfer(parts[1], query.from_user.id)
            bot_id = int(result.get("bot_id", result.get("id")))
            # Relay handlers resolve current roles dynamically; restart also purges cached state.
            bot = owner_bot(bot_id, query.from_user.id)
            if bot.get("desired_state") == "RUNNING":
                await self._restart_clone_bot(bot_id, actor_id=query.from_user.id)
            await query.edit_message_text("✅ 已接收所属权。旧管理员和旧会话已撤销。", reply_markup=K([[B("⚙️ 设置", callback_data=f"manage:{bot_id}")]]))
            return True
        mapping = {"bot_delete": "delete", "delete_confirm": "delete", "bot_disconnect": "disconnect", "bot_disconnect_confirm": "disconnect", "bot_reconnect": "reconnect", "bot_restart": "restart"}
        if action in mapping:
            await self._confirm_owner_action(query, mapping[action], int(parts[1]))
            return True
        if action in ("bot_reset_token", "bot_transfer", "bot_timezone"):
            bot_id = int(parts[1])
            owner_bot(bot_id, query.from_user.id)
            state = {"bot_reset_token": "rotate_input", "bot_transfer": "transfer_input", "bot_timezone": "timezone_input"}[action]
            put_session(query.from_user.id, state, {"bot_id": bot_id})
            prompts = {"rotate_input": "请输入新的 Bot Token。只允许更换为同一 Telegram 机器人的Token，不允许更换机器人身份。",
                       "transfer_input": "请输入接收方的 Telegram 数字用户ID。对方须先启动主机器人；最终由双方确认。",
                       "timezone_input": "请输入 IANA 时区，例如 Asia/Shanghai 或 UTC。"}
            await query.edit_message_text(prompts[state] + "\n15分钟内有效。", reply_markup=K([[B("❌ 取消", callback_data=f"manage:{bot_id}")]]))
            return True
        if action == "bot_transfer_time":
            bot_id = int(parts[1])
            owner_bot(bot_id, query.from_user.id)
            targets = [b for b in get_bots_by_owner(query.from_user.id) if b["id"] != bot_id and not b.get("deleted_at") and b.get("desired_state") != "DELETED"]
            rows = [[B(f"@{b['bot_username']} · {b['id']}", callback_data=f"time_target:{bot_id}:{b['id']}")] for b in targets]
            rows.append([B("🔙 返回", callback_data=f"manage:{bot_id}")])
            await query.edit_message_text("选择接收剩余专业版时间的机器人。永久会员不可转移，源机器人剩余时间将归零。", reply_markup=K(rows))
            return True
        if action == "time_target":
            source, target = int(parts[1]), int(parts[2])
            owner_bot(source, query.from_user.id)
            owner_bot(target, query.from_user.id)
            if source == target:
                raise ValueError("不能转移给自身")
            await self._confirm_owner_action(query, "time", source, {"target_id": target})
            return True
        return False

    async def _owner_text(self, update, context, session):
        data = validate_session_actor(session, update.effective_user.id)
        text = (update.effective_message.text or "").strip()
        query = MessageQuery(update.effective_message)
        if session["state"] == "transfer_input":
            if not text.isdigit() or int(text) <= 0 or int(text) == update.effective_user.id:
                raise ValueError("请输入另一位用户的有效数字ID")
            from .database import get_db
            if not get_db().execute("SELECT 1 FROM main_users WHERE user_id=?", (int(text),)).fetchone():
                raise ValueError("接收方须先启动主机器人")
            await self._confirm_owner_action(query, "transfer", data["bot_id"], {"target_id": int(text)})
        elif session["state"] == "timezone_input":
            try:
                ZoneInfo(text)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("无效时区，请输入如 Asia/Shanghai、UTC") from None
            await self._confirm_owner_action(query, "timezone", data["bot_id"], {"value": text})
        elif session["state"] == "rotate_input":
            import re
            if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", text):
                raise ValueError("Token格式不正确")
            # Lifecycle validates get_me identity while holding its per-bot lock.
            nonce = put_session(query.from_user.id, "rotate_confirm", {**data, "token": text})
            await query.edit_message_text("Token已收到（不回显）。确认验证同一机器人身份并替换？", reply_markup=K([
                [B("✅ 验证并替换", callback_data=f"rotate_confirm:{nonce}")], [B("❌ 取消", callback_data=f"manage:{data['bot_id']}")]]))
        else:
            return False
        return True

    async def _rotate_confirm(self, query):
        nonce = query.data.split(":", 1)[1]
        session = get_session(query.from_user.id, nonce)
        data = validate_session_actor(session, query.from_user.id)
        if session["state"] != "rotate_confirm":
            raise ValueError("操作已过期")
        consume_session(query.from_user.id, nonce)
        await self._rotate_clone_token(data["bot_id"], data["token"], actor_id=query.from_user.id)
        await query.edit_message_text("✅ Token已验证并更新。", reply_markup=K([[B("⚙️ 设置", callback_data=f"manage:{data['bot_id']}")]]))

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
