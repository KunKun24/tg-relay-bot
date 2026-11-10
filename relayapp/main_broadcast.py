# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Platform-only durable announcements; never sends through clone bots."""
from __future__ import annotations

import time
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from .config import MAIN_ADMIN_ID
from .database import transaction
from .configuration import get_main_text
from .formatting import capture_payload, send_payload
from .main_sessions import put_session, get_session, validate_session_actor


class MainBroadcastMixin:
    async def _show_main_job(self, query, job_id):
        from .broadcast import broadcasts
        if query.from_user.id != MAIN_ADMIN_ID:
            raise PermissionError("无权操作")
        stat = broadcasts.stats(job_id, query.from_user.id)
        if int(stat.get("bot_id", -1)) != 0:
            raise PermissionError("主平台只能查看主平台任务")
        counts = stat.get("counts", stat)
        progress = stat.get("progress", "")
        lines = [f"📣 主平台广播 #{job_id}", f"状态：{stat.get('status', '-')}",
                 f"总收件人：{stat.get('total', 0)} · 已完成：{stat.get('completed', 0)}", str(progress)]
        for key in ("PENDING", "RETRY", "SENDING", "SENT", "FAILED", "UNKNOWN", "SKIPPED", "CANCELLED"): 
            lines.append(f"{key}：{counts.get(key, counts.get(key.lower(), 0))}")
        rows = [[B("🔄 刷新", callback_data=f"main_job:{job_id}")],
                [B("⏸️ 暂停", callback_data=f"main_job_action:{job_id}:pause"), B("▶️ 继续", callback_data=f"main_job_action:{job_id}:resume")],
                [B("❌ 取消剩余", callback_data=f"main_job_action:{job_id}:cancel")]]
        if counts.get("UNKNOWN", counts.get("unknown", 0)):
            lines.append("UNKNOWN表示发送结果不确定：重试可能重复送达，跳过可能漏发。请明确选择。")
            rows.append([B("⚠️ 重试UNKNOWN", callback_data=f"main_job_action:{job_id}:retry_unknown"), B("⏭️ 跳过UNKNOWN", callback_data=f"main_job_action:{job_id}:skip_unknown")])
        rows.append([B("🔙 返回", callback_data="admin:back")])
        await query.edit_message_text("\n".join(lines), reply_markup=K(rows))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def _main_broadcast_callback(self, query, context):
        data = query.data
        if query.from_user.id != MAIN_ADMIN_ID:
            raise PermissionError("无权操作")
        if data == "admin:broadcast":
            put_session(query.from_user.id, "main_broadcast_input", {"admin": True})
            await query.edit_message_text("请发送主平台公告。支持文字、图片、视频和文件，可回复一条帖子。\n只投递给启动过主机器人的用户，不投递克隆客户。", reply_markup=K([[B("❌ 取消", callback_data="admin:back")]]))
        elif data == "admin:mass_start":
            from .formatting import render_emoji_html
            payload = {"type": "text", "text": render_emoji_html(get_main_text("welcome")), "legacy_html": True,
                       "buttons": self._build_start_keyboard().to_dict()["inline_keyboard"]}
            # Formatting module normalizes serializable payloads for the durable queue.
            await self._main_broadcast_preview(query, context, payload, welcome=True)
        elif data.startswith("main_broadcast_confirm:"):
            nonce = data.split(":", 1)[1]
            from .broadcast import broadcasts
            with transaction() as con:
                session = get_session(query.from_user.id, nonce)
                draft = validate_session_actor(session, query.from_user.id)
                if session["state"] != "main_broadcast_confirm":
                    raise ValueError("操作已过期")
                job_id = broadcasts.create_in_transaction(con, 0, query.from_user.id, draft["payload"], query.message.chat_id, query.message.message_id)
                changed = con.execute("DELETE FROM ui_sessions WHERE bot_id=0 AND user_id=? AND nonce=? AND expires_at>?", (query.from_user.id, nonce, time.time())).rowcount
                if changed != 1:
                    raise ValueError("操作已过期或已提交")
            await self._show_main_job(query, job_id)
        elif data.startswith("main_job:"):
            await self._show_main_job(query, int(data.split(":")[1]))
        elif data.startswith("main_job_action:"):
            _, raw_id, action = data.split(":")
            if action not in ("pause", "resume", "cancel", "retry_unknown", "skip_unknown"):
                raise ValueError("操作不存在")
            from .broadcast import broadcasts
            stat = broadcasts.stats(int(raw_id), query.from_user.id)
            if int(stat.get("bot_id", -1)) != 0:
                raise PermissionError("主平台只能控制主平台任务")
            nonce = put_session(query.from_user.id, "main_job_action_confirm", {"admin": True, "job_id": int(raw_id), "action": action})
            warning = "\n⚠️ 结果不确定的消息重试可能重复送达。" if action == "retry_unknown" else "\n跳过可能漏发。" if action == "skip_unknown" else ""
            await query.edit_message_text(f"确认对任务 #{raw_id} 执行 {action}？{warning}", reply_markup=K([
                [B("✅ 确认", callback_data=f"main_job_action_confirm:{nonce}")], [B("❌ 取消", callback_data=f"main_job:{raw_id}")]]))
        elif data.startswith("main_job_action_confirm:"):
            from .broadcast import broadcasts
            from .main_sessions import consume_session
            session = get_session(query.from_user.id, data.split(":")[1])
            draft = validate_session_actor(session, query.from_user.id)
            if session["state"] != "main_job_action_confirm":
                raise ValueError("操作已过期")
            stat = broadcasts.stats(draft["job_id"], query.from_user.id)
            if int(stat.get("bot_id", -1)) != 0:
                raise PermissionError("无权操作")
            consume_session(query.from_user.id, data.split(":")[1])
            broadcasts.action(draft["job_id"], query.from_user.id, draft["action"])
            await self._show_main_job(query, draft["job_id"])
        else:
            return False
        return True

    async def _main_broadcast_preview(self, query, context, payload, welcome=False):
        nonce = put_session(query.from_user.id, "main_broadcast_confirm", {"admin": True, "payload": payload, "welcome": welcome})
        await send_payload(context.bot, query.from_user.id, payload)
        await query.edit_message_text("📣 主平台欢迎语重发预览" if welcome else "📣 主平台公告预览", reply_markup=K([
            [B("✅ 确认创建广播任务", callback_data=f"main_broadcast_confirm:{nonce}")], [B("❌ 取消", callback_data="admin:back")]]))

    async def _main_broadcast_text(self, update, context, session):
        from .main_sessions import MessageQuery
        validate_session_actor(session, update.effective_user.id)
        message = update.effective_message.reply_to_message or update.effective_message
        payload = capture_payload(message)
        if not payload:
            raise ValueError("不支持该消息，请发送文字、图片、视频或文件")
        await self._main_broadcast_preview(MessageQuery(update.effective_message), context, payload)

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
