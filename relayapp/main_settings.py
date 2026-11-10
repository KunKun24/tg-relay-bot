# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Platform wording, button metadata, payment configuration and quotas."""
from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from .configuration import (get_main_text, set_main_text, get_main_button, set_main_button,
                            get_setting, set_setting, is_text_modified, is_button_modified)
from .defaults import DEFAULT_TEXTS, DEFAULT_BUTTONS
from .formatting import extract_emoji_from_text_html, render_emoji_html
from .main_sessions import put_session, get_session, validate_session_actor, consume_session

COLORS = {"default": "⚪ 默认", "primary": "🔵 蓝色", "success": "🟢 绿色", "danger": "🔴 红色"}
OKPAY_FIELDS = {"appid": "商户ID", "token": "密钥", "api_url": "API地址", "callback_url": "回调地址", "rate": "USDT汇率"}
LIMITS = {"free_bot_limit": "普通版新建机器人上限", "free_welcome_limit": "普通版欢迎语上限", "free_auto_reply_limit": "普通版自动回复上限"}


def valid_url(value, *, optional=False):
    if optional and value in ("无", ""):
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "http", "tg") or (parsed.scheme != "tg" and not parsed.netloc):
        raise ValueError("请输入有效的 http/https/tg 链接")
    return value


class MainSettingsMixin:
    async def _show_text_settings(self, query, page=1):
        await self._show_config_list(query, "text", page)

    async def _show_button_settings(self, query, page=1):
        await self._show_config_list(query, "button", page)

    async def _show_config_list(self, query, kind, page=1):
        keys = list(DEFAULT_TEXTS if kind == "text" else DEFAULT_BUTTONS)
        check = is_text_modified if kind == "text" else is_button_modified
        pages = max(1, (len(keys) + 9) // 10)
        page = max(1, min(int(page), pages))
        prefix = "texts" if kind == "text" else "btns"
        buttons = []
        for key in keys[(page - 1) * 10:page * 10]:
            label = get_main_text(key) if kind == "text" else get_main_button(key).get("text", key)
            dest = f"admin:text:{key}" if kind == "text" else f"admin:btn:{key}"
            buttons.append([B(f"{'✅' if check(key) else '⭕'} {key}: {label[:25]}", callback_data=dest)])
        nav = []
        if page > 1:
            nav.append(B("⬅️ 上一页", callback_data=f"admin:{prefix}_page:{page-1}"))
        if page < pages:
            nav.append(B("下一页 ➡️", callback_data=f"admin:{prefix}_page:{page+1}"))
        if nav:
            buttons.append(nav)
        buttons += [[B("⚡ 逐个修改", callback_data=f"admin:{prefix}_walk"), B("📝 全部修改", callback_data=f"admin:{prefix}_walk_all")],
                    [B("🔙 返回", callback_data="admin:back")]]
        await query.edit_message_text(f"{'📝 文案' if kind == 'text' else '🔘 按钮'}设置\n已修改：{sum(check(k) for k in keys)}/{len(keys)}\n第{page}/{pages}页", reply_markup=K(buttons))

    async def _show_button_edit(self, query, key):
        if key not in DEFAULT_BUTTONS:
            raise ValueError("按钮不存在")
        btn = get_main_button(key)
        rows = [[B("📝 修改文字", callback_data=f"admin:btn_text:{key}"), B("🎨 颜色", callback_data=f"admin:btn_color:{key}")],
                [B("🔗 修改链接", callback_data=f"admin:btn_url:{key}"), B("😀 会员图标", callback_data=f"admin:btn_icon:{key}")],
                [B("🔙 返回", callback_data="admin:buttons")]]
        await query.edit_message_text(f"🔘 编辑按钮：{key}\n文字：{btn.get('text', '')}\n链接：{btn.get('url', '')}\n颜色：{btn.get('color') or '默认'}\n会员图标ID：{btn.get('emoji_id', '')}", reply_markup=K(rows))

    async def _start_text_walk(self, query, context, skip_modified=True):
        await self._start_walk(query, "text", skip_modified)

    async def _start_btn_walk(self, query, context, skip_modified=True):
        await self._start_walk(query, "button", skip_modified)

    async def _start_walk(self, query, kind, skip_modified=True, start=0):
        keys = list(DEFAULT_TEXTS if kind == "text" else DEFAULT_BUTTONS)
        check = is_text_modified if kind == "text" else is_button_modified
        for index in range(start, len(keys)):
            if skip_modified and check(keys[index]):
                continue
            data = {"admin": True, "kind": kind, "key": keys[index], "field": "text", "walk": True,
                    "index": index, "skip_modified": skip_modified}
            await self._prompt_setting(query, data)
            return
        await query.edit_message_text("✅ 所有项目已修改完成", reply_markup=K([[B("🔙 返回", callback_data="admin:back")]]))

    async def _prompt_setting(self, query, data):
        nonce = put_session(query.from_user.id, "setting_input", data)
        kind, key, field = data["kind"], data["key"], data.get("field", "text")
        if kind == "text":
            current = get_main_text(key)
        elif kind == "button":
            current = get_main_button(key).get(field, "")
        else:
            current = "（已设置，隐藏）" if key == "okpay_token" else get_setting(0, key, "")
        rows = []
        if data.get("walk"):
            rows.append([B("⏭️ 跳过", callback_data=f"settings_skip:{nonce}")])
        rows.append([B("🔙 返回", callback_data="admin:back")])
        await query.edit_message_text(f"📝 编辑 {key} · {field}\n当前：{current}\n\n请发送新内容（15分钟内有效），提交后预览确认。链接或图标发送 无 可清除。", reply_markup=K(rows))

    async def _show_color_picker(self, query, key, data=None):
        if key not in DEFAULT_BUTTONS:
            raise ValueError("按钮不存在")
        data = data or {"admin": True, "kind": "button", "key": key, "field": "color"}
        nonce = put_session(query.from_user.id, "color_input", data)
        buttons = [[B(label, callback_data=f"settings_color:{nonce}:{color}", **({"style": color} if color != "default" else {}))]
                   for color, label in COLORS.items()]
        if data.get("walk"):
            buttons.append([B("⏭️ 跳过颜色", callback_data=f"settings_skip:{nonce}")])
        buttons.append([B("🔙 返回", callback_data="admin:buttons")])
        await query.edit_message_text(f"🎨 选择按钮颜色：{key}", reply_markup=K(buttons))

    async def _setting_preview(self, query, data, value):
        data = dict(data, value=value)
        nonce = put_session(query.from_user.id, "setting_confirm", data)
        display = "（密钥已隐藏）" if data["key"] == "okpay_token" else value
        preview = render_emoji_html(display) if data["kind"] == "text" else html.escape(str(display))
        await query.edit_message_text(f"待保存：{html.escape(data['key'])} · {html.escape(data.get('field', 'value'))}\n\n{preview}\n\n确认后生效。", parse_mode="HTML", reply_markup=K([
            [B("✅ 确认保存", callback_data=f"settings_save:{nonce}")], [B("❌ 取消", callback_data="admin:back")]]))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def _settings_text(self, update, session):
        from .main_sessions import MessageQuery
        # Recheck authority both on input and on the final nonce submission.
        data = validate_session_actor(session, update.effective_user.id)
        message = update.effective_message
        value = (message.text or "").strip()
        kind, key, field = data["kind"], data["key"], data.get("field", "text")
        if kind == "text":
            value = extract_emoji_from_text_html(message)
        elif kind == "button" and field == "text":
            # Button labels are plain text; retain a custom emoji as icon metadata.
            encoded = (message.text or "").encode("utf-16-le")
            for entity in sorted(message.entities or (), key=lambda item: item.offset, reverse=True):
                if getattr(entity, "custom_emoji_id", None):
                    marker = f"[emoji:{entity.custom_emoji_id}]".encode("utf-16-le")
                    encoded = encoded[:entity.offset * 2] + marker + encoded[(entity.offset + entity.length) * 2:]
            value = encoded.decode("utf-16-le").strip()
            if not value or len(value) > 128:
                raise ValueError("按钮文字应为1至128个字符")
        elif kind == "button" and field == "url":
            value = valid_url(value, optional=True)
        elif kind == "button" and field == "emoji_id":
            entities = tuple(message.entities or ())
            emoji = next((getattr(e, "custom_emoji_id", None) for e in entities if getattr(e, "custom_emoji_id", None)), None)
            value = str(emoji or ("" if value == "无" else value))
            if value and not re.fullmatch(r"\d+", value):
                raise ValueError("请输入数字图标ID或发送一个自定义表情")
        elif key in LIMITS:
            if not value.isdigit() or not 1 <= int(value) <= 100000:
                raise ValueError("额度应为 1 至 100000 的整数")
        elif key == "okpay_rate":
            try:
                rate = Decimal(value)
                if not rate.is_finite() or rate <= 0:
                    raise ValueError("汇率必须为正数")
            except InvalidOperation:
                raise ValueError("汇率必须为正数") from None
        elif key in ("okpay_api_url", "okpay_callback_url"):
            value = valid_url(value, optional=key == "okpay_callback_url")
            if value and urlsplit(value).scheme != "https":
                raise ValueError("支付API与回调地址必须使用 HTTPS")
        if not value and not (kind == "button" and field in ("url", "emoji_id")) and key != "okpay_callback_url":
            raise ValueError("内容不能为空")
        await self._setting_preview(MessageQuery(message), data, value)

    async def _settings_callback(self, query, context):
        parts = query.data.split(":")
        head = parts[0]
        if head in ("settings_save", "settings_skip", "settings_color"):
            session = get_session(query.from_user.id, parts[1])
            data = validate_session_actor(session, query.from_user.id)
            if head == "settings_color":
                if session["state"] != "color_input" or parts[2] not in COLORS:
                    raise ValueError("操作已过期")
                await self._setting_preview(query, data, "" if parts[2] == "default" else parts[2])
                return True
            if head == "settings_save":
                if session["state"] != "setting_confirm":
                    raise ValueError("没有待确认配置")
                consume_session(query.from_user.id, parts[1])
                if data["kind"] == "text":
                    set_main_text(data["key"], data["value"])
                elif data["kind"] == "button":
                    btn = get_main_button(data["key"])
                    btn[data["field"]] = data["value"]
                    if data["field"] == "url" and data["value"]:
                        btn["type"] = "url"
                    set_main_button(data["key"], btn)
                else:
                    set_setting(0, data["key"], data["value"])
                await query.answer("配置已保存")
            else:
                consume_session(query.from_user.id, parts[1])
            if data.get("walk"):
                if data["kind"] == "button" and data["field"] == "text" and head == "settings_save":
                    await self._show_color_picker(query, data["key"], dict(data, field="color"))
                elif data["kind"] == "button" and data["field"] == "color" and (DEFAULT_BUTTONS[data["key"]].get("type") == "url" or get_main_button(data["key"]).get("url")):
                    await self._prompt_setting(query, dict(data, field="url"))
                else:
                    await self._start_walk(query, data["kind"], data.get("skip_modified", True), data["index"] + 1)
            else:
                await query.edit_message_text("✅ 配置已保存" if head == "settings_save" else "已跳过", reply_markup=K([[B("🔙 返回", callback_data="admin:back")]]))
            return True
        if query.data == "admin:texts":
            await self._show_text_settings(query)
        elif query.data == "admin:buttons":
            await self._show_button_settings(query)
        elif query.data.startswith("admin:texts_page:"):
            await self._show_text_settings(query, int(parts[2]))
        elif query.data.startswith("admin:btns_page:"):
            await self._show_button_settings(query, int(parts[2]))
        elif query.data in ("admin:texts_walk", "admin:texts_walk_all", "admin:btns_walk", "admin:btns_walk_all"):
            await self._start_walk(query, "text" if "texts" in parts[1] else "button", not parts[1].endswith("_all"))
        elif query.data.startswith("admin:text:"):
            if parts[2] not in DEFAULT_TEXTS:
                raise ValueError("文案不存在")
            await self._prompt_setting(query, {"admin": True, "kind": "text", "key": parts[2], "field": "text"})
        elif query.data.startswith("admin:btn:"):
            await self._show_button_edit(query, parts[2])
        elif query.data.startswith("admin:btn_color:"):
            await self._show_color_picker(query, parts[2])
        elif parts[1] in ("btn_text", "btn_url", "btn_icon"):
            if parts[2] not in DEFAULT_BUTTONS:
                raise ValueError("按钮不存在")
            await self._prompt_setting(query, {"admin": True, "kind": "button", "key": parts[2], "field": {"btn_text": "text", "btn_url": "url", "btn_icon": "emoji_id"}[parts[1]]})
        elif query.data == "admin:okpay":
            rows = [[B(label, callback_data=f"admin:okpay:{key}")] for key, label in OKPAY_FIELDS.items()]
            rows += [[B("✅ 启用 / ❌ 禁用", callback_data="admin:okpay:toggle")], [B("🔙 返回", callback_data="admin:back")]]
            await query.edit_message_text(f"💳 OkPay 支付配置\n状态：{'已启用' if get_setting(0, 'okpay_enabled', '0') == '1' else '未启用'}\n商户ID：{get_setting(0, 'okpay_appid', '')}\n密钥：已隐藏\nAPI：{get_setting(0, 'okpay_api_url', '')}\n汇率：{get_setting(0, 'okpay_rate', '7.0')}", reply_markup=K(rows))
        elif query.data.startswith("admin:okpay:"):
            if parts[2] == "toggle":
                await self._setting_preview(query, {"admin": True, "kind": "setting", "key": "okpay_enabled"}, "0" if get_setting(0, "okpay_enabled", "0") == "1" else "1")
            elif parts[2] in OKPAY_FIELDS:
                await self._prompt_setting(query, {"admin": True, "kind": "setting", "key": f"okpay_{parts[2]}"})
            else:
                raise ValueError("配置项不存在")
        elif query.data == "admin:limits":
            rows = [[B(f"{label}：{get_setting(0, key, str({'free_bot_limit': 5, 'free_welcome_limit': 3, 'free_auto_reply_limit': 10}[key]))}", callback_data=f"admin:limit:{key}")] for key, label in LIMITS.items()]
            rows.append([B("🔙 返回", callback_data="admin:back")])
            await query.edit_message_text("⚙️ 普通版额度（仅约束新增，不删除既有资源）", reply_markup=K(rows))
        elif query.data.startswith("admin:limit:") and parts[2] in LIMITS:
            await self._prompt_setting(query, {"admin": True, "kind": "setting", "key": parts[2]})
        else:
            return False
        return True

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
