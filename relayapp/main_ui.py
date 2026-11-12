# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Main platform entry points. No polling or production configuration on import."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets
import time
from urllib.parse import quote
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from .bots import touch_main_user, inc_main_user_click, inc_main_user_msg, get_bots_by_owner
from .configuration import get_main_text, get_main_button, format_bot_time
from .config import MAIN_ADMIN_ID, MAIN_BOT_USERNAME
from .defaults import BUTTON_LAYOUT
from .formatting import render_emoji_html
from .lifecycle import LifecycleMixin
from .managed import ManagedMixin
from .main_settings import MainSettingsMixin
from .main_payments import MainPaymentsMixin
from .main_actions import MainActionsMixin
from .main_admin import MainAdminMixin
from .main_broadcast import MainBroadcastMixin
from .main_sessions import (put_session, get_session, clear_session, owner_bot,
                            validate_session_actor, MessageQuery, PacedUpdate)

logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{30,}")


class MainBotHandlers(ManagedMixin, MainSettingsMixin, MainPaymentsMixin, MainActionsMixin,
                      MainAdminMixin, MainBroadcastMixin, LifecycleMixin):
    def __init__(self):
        self.clone_runners = {}
        self._managed_sync_lock = asyncio.Lock()
        self._runner_locks = {}
        self._jobs_lock = asyncio.Lock()
        self.bot = None

    def _make_inline_btn(self, key, callback_data=None, url=None, **values):
        btn = get_main_button(key)
        text = btn.get("text", key) or " "
        for name, value in values.items():
            text = text.replace("{" + name + "}", str(value))
        emoji = re.search(r"\[emoji:+(\d+)\]", text)
        text = re.sub(r"\[emoji:+\d+\]", "", text).strip() or " "
        kwargs = {"text": text}
        if btn.get("color") in ("primary", "success", "danger"):
            kwargs["style"] = btn["color"]
        icon = emoji.group(1) if emoji else btn.get("emoji_id")
        if icon:
            kwargs["icon_custom_emoji_id"] = str(icon)
        if url is not None:
            kwargs["url"] = url
        elif callback_data is not None:
            kwargs["callback_data"] = callback_data
        elif btn.get("type") == "url" and btn.get("url"):
            kwargs["url"] = btn["url"]
        else:
            kwargs["callback_data"] = f"main:{btn.get('action')}" if btn.get("type") == "fixed" else f"main:url_notset:{key}"
        return B(**kwargs)

    def _build_start_keyboard(self, user_id=None):
        rows = [[self._make_inline_btn(key) for key in keys] for keys in BUTTON_LAYOUT]
        if user_id == MAIN_ADMIN_ID:
            rows.append([B("⚙️ 管理后台", callback_data="main:admin")])
        return K(rows)

    def _build_add_bot_keyboard(self, user=None):
        rows = [[self._make_inline_btn("btn_add_token", callback_data="main:add_token")]]
        if user is not None:
            username = f"SX{time.strftime('%y%m%d%H%M%S')}{secrets.token_hex(3)}bot"
            name = ((user.full_name or "用户") + "的双向机器人")[:64]
            link = f"https://t.me/newbot/{MAIN_BOT_USERNAME}/{username}?name={quote(name)}"
            rows.append([self._make_inline_btn("btn_add_oneclick", url=link)])
        rows.append([self._make_inline_btn("btn_cancel", callback_data="main:home")])
        return K(rows)

    @staticmethod
    def _private(update):
        return bool(update.effective_chat and update.effective_chat.type == "private" and update.effective_user and not update.effective_user.is_bot)

    async def start(self, update, context):
        if not self._private(update):
            return
        update = PacedUpdate(update, context.bot)
        user = update.effective_user
        touch_main_user(user.id, user.username, user.first_name)
        clear_session(user.id)
        await update.effective_message.reply_text(render_emoji_html(get_main_text("welcome")), parse_mode="HTML", reply_markup=self._build_start_keyboard(user.id))

    async def cmd_admin(self, update, context):
        if not self._private(update) or update.effective_user.id != MAIN_ADMIN_ID:
            return
        clear_session(update.effective_user.id)
        update = PacedUpdate(update, context.bot)
        query = MessageQuery(update.effective_message)
        query.data = "admin:back"
        await self._admin_callback(query, context)

    async def _show_my_bots(self, query, user_id, page=1):
        bots = [b for b in get_bots_by_owner(user_id) if b.get("desired_state") != "DELETED"]
        if not bots:
            await query.edit_message_text(render_emoji_html(get_main_text("mybots_empty")), parse_mode="HTML", reply_markup=K([[self._make_inline_btn("btn_add", callback_data="main:add_bot")], [B("🏠 首页", callback_data="main:home")]]))
            return
        pages = max(1, (len(bots) + 7) // 8)
        page = max(1, min(int(page), pages))
        rows = []
        for bot in bots[(page - 1) * 8:page * 8]:
            rows.append([B(f"@{bot['bot_username']}", url=f"https://t.me/{bot['bot_username']}"), B("⚙️ 设置", callback_data=f"manage:{bot['id']}")])
        nav = []
        if page > 1:
            nav.append(B("⬅️ 上一页", callback_data=f"mybots_page:{page-1}"))
        if page < pages:
            nav.append(B("下一页 ➡️", callback_data=f"mybots_page:{page+1}"))
        if nav:
            rows.append(nav)
        rows.append([B("🏠 首页", callback_data="main:home")])
        await query.edit_message_text(render_emoji_html(get_main_text("mybots_title")) + f"\n\n{render_emoji_html(get_main_text('mybots_desc'))}\n第{page}/{pages}页", parse_mode="HTML", reply_markup=K(rows))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


    async def _show_bot_settings(self, query, bot_id, context):
        bot = owner_bot(bot_id, query.from_user.id)
        state = f"{bot.get('desired_state', '-')} / {bot.get('actual_state', '-')}"
        text = render_emoji_html(get_main_text("bot_settings_title")) + "\n\n" + render_emoji_html(get_main_text("bot_settings_info", username=html.escape(bot['bot_username'] or ''), version=html.escape(bot.get('version') or '普通版'), status=state,
            expire=html.escape(format_bot_time(bot_id, bot.get('expire_time') or '－'))))
        rows = [[self._make_inline_btn("btn_upgrade", callback_data=f"bot_upgrade:{bot_id}")],
                [self._make_inline_btn("btn_restart_bot", callback_data=f"bot_restart:{bot_id}"), self._make_inline_btn("btn_reset_token", callback_data=f"bot_reset_token:{bot_id}")],
                [self._make_inline_btn("btn_reconnect" if bot.get('desired_state') != 'RUNNING' else "btn_disconnect", callback_data=f"{'bot_reconnect' if bot.get('desired_state') != 'RUNNING' else 'bot_disconnect'}:{bot_id}")],
                [self._make_inline_btn("btn_transfer_owner", callback_data=f"bot_transfer:{bot_id}"), self._make_inline_btn("btn_transfer_time", callback_data=f"bot_transfer_time:{bot_id}")],
                [B("🌐 时区", callback_data=f"bot_timezone:{bot_id}"), self._make_inline_btn("btn_bot_delete", callback_data=f"bot_delete:{bot_id}")],
                [self._make_inline_btn("btn_back_mybots", callback_data="main:my_bots")]]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=K(rows))

    async def callback(self, update, context):
        if not self._private(update):
            return
        update = PacedUpdate(update, context.bot)
        query, user = update.callback_query, update.effective_user
        if not query or not query.data:
            return
        touch_main_user(user.id, user.username, user.first_name)
        inc_main_user_click(user.id)
        data = query.data
        try:
            if data.startswith(("admin:", "settings_", "vip_toggle_confirm:", "manual_vip_confirm:", "admin_lifecycle_confirm:", "main_job", "main_broadcast")) or data == "main:admin":
                if user.id != MAIN_ADMIN_ID:
                    raise PermissionError("无权操作")
                if data.startswith("admin:") or data in ("main:admin",) or data.startswith("main_job:"):
                    clear_session(user.id)
                if await self._main_broadcast_callback(query, context):
                    return
                if await self._settings_callback(query, context):
                    return
                if await self._admin_callback(query, context):
                    return
            elif data.startswith("token_confirm:"):
                await self.confirm_token(query, context)
                return
            elif data in ("main:home", "main:cancel", "main:back_start"):
                clear_session(user.id)
                await query.edit_message_text(render_emoji_html(get_main_text("welcome")), parse_mode="HTML", reply_markup=self._build_start_keyboard(user.id))
                return
            elif data == "main:add_bot":
                clear_session(user.id)
                await query.edit_message_text(render_emoji_html(get_main_text("add_bot_page")), parse_mode="HTML", reply_markup=self._build_add_bot_keyboard(user))
                return
            elif data == "main:add_token":
                put_session(user.id, "token_input")
                await query.edit_message_text(render_emoji_html(get_main_text("add_token_page")), parse_mode="HTML", reply_markup=K([[B("❌ 取消", callback_data="main:home")]]))
                return
            elif data == "main:my_bots" or data.startswith("mybots_page:"):
                clear_session(user.id)
                await self._show_my_bots(query, user.id, int(data.split(":")[1]) if data.startswith("mybots_page:") else 1)
                return
            elif data.startswith("manage:"):
                clear_session(user.id)
                await self._show_bot_settings(query, int(data.split(":")[1]), context)
                return
            elif data.startswith("rotate_confirm:"):
                await self._rotate_confirm(query)
                return
            elif await self._owner_callback(query, context):
                return
            elif await self._payment_callback(query, context):
                return
            elif data.startswith("main:url_notset:"):
                await query.answer("链接尚未设置，请联系管理员", show_alert=True)
                return
            elif data == "main:add_oneclick":
                await query.edit_message_text(render_emoji_html(get_main_text("add_bot_page")), parse_mode="HTML", reply_markup=self._build_add_bot_keyboard(user))
                return
            raise ValueError("菜单已失效，请发送 /start")
        except (ValueError, PermissionError) as exc:
            await query.answer(str(exc)[:180], show_alert=True)
        except Exception as exc:
            logger.error("Main callback failed: %s", type(exc).__name__)
            await query.answer("操作失败，请重新打开菜单后重试", show_alert=True)

    async def handle_text(self, update, context):
        if not self._private(update):
            return
        update = PacedUpdate(update, context.bot)
        message, user = update.effective_message, update.effective_user
        touch_main_user(user.id, user.username, user.first_name)
        inc_main_user_msg(user.id)
        session = get_session(user.id)
        try:
            if session:
                validate_session_actor(session, user.id)
                state = session["state"]
                if state == "setting_input":
                    await self._settings_text(update, session)
                    return
                if state == "main_broadcast_input":
                    await self._main_broadcast_text(update, context, session)
                    return
                if state == "manual_vip_input":
                    await self._manual_vip_text(update, session)
                    return
                if state in ("transfer_input", "timezone_input", "rotate_input"):
                    await self._owner_text(update, context, session)
                    return
                if state == "token_confirm" or state.endswith("confirm"):
                    await message.reply_text("请使用预览下方的确认或取消按钮。")
                    return
            text = (message.text or "").strip()
            if TOKEN_RE.fullmatch(text) and (not session or session["state"] == "token_input"):
                nonce = put_session(user.id, "token_confirm", {"token": text})
                await message.reply_text("已收到Token（不回显）。确认验证并添加机器人？", reply_markup=K([
                    [B("✅ 确认添加", callback_data=f"token_confirm:{nonce}")], [B("❌ 取消", callback_data="main:home")]]))
            elif session and session["state"] == "token_input":
                raise ValueError("Token格式不正确，请重新发送")
        except (ValueError, PermissionError) as exc:
            await message.reply_text(str(exc))
        except Exception as exc:
            logger.error("Main message failed: %s", type(exc).__name__)
            await message.reply_text("操作失败，请重新打开菜单后重试。")

    async def confirm_token(self, query, context):
        from .main_sessions import consume_session
        nonce = query.data.split(":", 1)[1]
        session = get_session(query.from_user.id, nonce)
        data = validate_session_actor(session, query.from_user.id)
        if session["state"] != "token_confirm":
            raise ValueError("操作已过期")
        consume_session(query.from_user.id, nonce)
        async def notify(text, **kwargs):
            return await self._send_main_user_message(context, query.from_user.id, text, **kwargs)
        await self._setup_new_bot(query.from_user.id, data["token"], notify)

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
