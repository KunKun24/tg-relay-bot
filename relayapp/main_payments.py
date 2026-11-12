# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

"""Owner checked purchase UI; grants are exclusively the payment transaction's job."""
from __future__ import annotations

import html
import secrets
import time
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from .configuration import get_main_text, get_setting
from .defaults import VIP_PLANS
from .formatting import render_emoji_html
from .main_sessions import owner_bot
from .payments import (get_order, get_okpay_client, create_order, update_order_pay_info,
                       settle_order, verify_paid_evidence)


class MainPaymentsMixin:
    async def _paid_display(self, query, order):
        bot = owner_bot(order["bot_id"], query.from_user.id)
        await query.edit_message_text(render_emoji_html(get_main_text("vip_paid_success", plan_name=html.escape(order["plan_name"]),
            expire=html.escape(bot.get("expire_time") or "－"))), parse_mode="HTML", reply_markup=K([
                [self._make_inline_btn("btn_back_settings", callback_data=f"manage:{bot['id']}")]]))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


    async def _payment_callback(self, query, context):
        data = query.data
        if data.startswith("bot_upgrade:"):
            bot_id = int(data.split(":")[1])
            owner_bot(bot_id, query.from_user.id)
            await query.edit_message_text("\n\n".join(render_emoji_html(get_main_text(key)) for key in ("vip_title", "vip_plans", "vip_prompt")), parse_mode="HTML", reply_markup=K([
                [self._make_inline_btn("btn_plan_1m", callback_data=f"vip_plan:1m:{bot_id}"), self._make_inline_btn("btn_plan_3m", callback_data=f"vip_plan:3m:{bot_id}")],
                [self._make_inline_btn("btn_plan_forever", callback_data=f"vip_plan:forever:{bot_id}")],
                [self._make_inline_btn("btn_back_settings", callback_data=f"manage:{bot_id}")]]))
            return True
        if data.startswith("vip_plan:"):
            _, plan_key, raw_id = data.split(":")
            bot_id = int(raw_id)
            bot = owner_bot(bot_id, query.from_user.id)
            if plan_key not in VIP_PLANS:
                raise ValueError("套餐不存在")
            if bot.get("expire_time") == "永久":
                raise ValueError("该机器人已是永久高级版，无需重复购买")
            if get_setting(0, "okpay_enabled", "0") != "1":
                raise ValueError("OkPay支付未启用")
            client = get_okpay_client()
            if client is None:
                raise ValueError("支付未配置，请联系管理员")
            plan = VIP_PLANS[plan_key]
            order_no = f"VIP{int(time.time())}{secrets.token_hex(6)}"
            create_order(order_no, bot_id, query.from_user.id, plan_key, plan["name"], plan["amount"])
            await query.answer("正在创建订单")
            result = await client.pay_link(plan["amount"], order_no, f"双向机器人-{plan['name']}", "USDT")
            if result.get("code") != 200:
                raise ValueError("支付订单创建失败，请稍后重试或联系管理员")
            response = result.get("data") or {}
            pay_url = response.get("pay_url", "")
            from .main_settings import valid_url
            valid_url(pay_url)
            owner_bot(bot_id, query.from_user.id)
            update_order_pay_info(order_no, pay_url, response.get("order_id", ""))
            await query.edit_message_text(render_emoji_html(get_main_text("vip_pay_info", plan_name=plan["name"], amount=plan["amount"], order_id=order_no)), parse_mode="HTML", reply_markup=K([
                [self._make_inline_btn("btn_go_pay", url=pay_url)],
                [self._make_inline_btn("btn_i_paid", callback_data=f"vip_check:{order_no}")],
                [self._make_inline_btn("btn_back_settings", callback_data=f"manage:{bot_id}")]]))
            return True
        if data.startswith("vip_check:"):
            order_no = data.split(":", 1)[1]
            order = get_order(order_no)
            if not order or int(order["owner_id"]) != query.from_user.id:
                raise PermissionError("订单不存在或无权操作")
            owner_bot(order["bot_id"], query.from_user.id)
            # Historical paid rows are display-only; never call activate_vip here.
            if order["status"] == "paid":
                await self._paid_display(query, order)
                return True
            if order["status"] != "pending":
                raise ValueError("订单已关闭或过期")
            client = get_okpay_client()
            if client is None:
                raise ValueError("支付未配置")
            await query.answer("正在查询")
            result = await client.check_deposit(order_no)
            owner_bot(order["bot_id"], query.from_user.id)
            if result.get("code") != 200:
                raise ValueError("订单查询失败，请稍后重试")
            evidence = result.get("data") or {}
            if str(evidence.get("status")) == "0":
                rows = []
                if order.get("pay_url"):
                    rows.append([self._make_inline_btn("btn_go_pay", url=order["pay_url"])])
                rows += [[self._make_inline_btn("btn_i_paid", callback_data=f"vip_check:{order_no}")],
                         [self._make_inline_btn("btn_back_settings", callback_data=f"manage:{order['bot_id']}")]]
                await query.edit_message_text(render_emoji_html(get_main_text("vip_paid_pending")), parse_mode="HTML", reply_markup=K(rows))
                return True
            verified = verify_paid_evidence(order, evidence)
            if verified is False:
                raise ValueError("支付凭据与订单不符，未开通高级版")
            settle_order(order_no, query.from_user.id, evidence=evidence)
            await self._paid_display(query, get_order(order_no))
            return True
        return False

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
