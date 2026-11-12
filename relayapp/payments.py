# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

from __future__ import annotations
import hashlib,secrets,logging
from datetime import datetime,timedelta
import aiohttp
from .database import get_db, transaction
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import json
import time
from .config import MAIN_ADMIN_ID
from .bots import get_bot, audit
from .configuration import get_setting,set_setting
from .defaults import OKPAY_API_URL,VIP_PLANS
logger=logging.getLogger(__name__)

def get_okpay_config() -> dict:
    """获取OkPay支付配置（bot_id=0）"""
    return {
        "appid": get_setting(0, "okpay_appid", ""),
        "token": get_setting(0, "okpay_token", ""),
        "api_url": get_setting(0, "okpay_api_url", OKPAY_API_URL),
        "callback_url": get_setting(0, "okpay_callback_url", ""),
        "rate": float(get_setting(0, "okpay_rate", "7.0")),
}


def set_okpay_config(key, value):
    set_setting(0, f"okpay_{key}", value)


def create_order(order_no, bot_id, owner_id, plan_key, plan_name, amount):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO orders (order_no, bot_id, owner_id, plan_key, plan_name, amount, status, created_at) VALUES (?,?,?,?,?,?, 'pending', ?)",
        (order_no, bot_id, owner_id, plan_key, plan_name, amount, now)
    )
    conn.commit()
    oid = c.lastrowid
    conn.close()
    return oid


def update_order_pay_info(order_no, pay_url, okpay_order_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE orders SET pay_url=?, okpay_order_id=? WHERE order_no=?", (pay_url, okpay_order_id, order_no))
    conn.commit()
    conn.close()


def get_order(order_no):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_no=?", (order_no,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_order_status(order_no, status):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE orders SET status=?, paid_at=? WHERE order_no=?", (status, now, order_no))
    conn.commit()
    conn.close()


def _grant(con, bot_id, plan_key):
    plan = VIP_PLANS.get(plan_key)
    bot = con.execute('SELECT * FROM bots WHERE id=? AND deleted_at IS NULL', (bot_id,)).fetchone()
    if not plan or not bot:
        raise ValueError('套餐或机器人不存在')
    if bot['expire_time'] == '永久' or plan['days'] == 0:
        con.execute("UPDATE bots SET version='高级版',expire_time='永久',expires_at=NULL WHERE id=?", (bot_id,))
    else:
        expiry = max(time.time(), bot['expires_at'] or 0) + plan['days'] * 86400
        display = datetime.fromtimestamp(expiry, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        con.execute("UPDATE bots SET version='高级版',expire_time=?,expires_at=? WHERE id=?", (display, expiry, bot_id))


def activate_vip(bot_id, plan_key):
    with transaction() as con:
        _grant(con, bot_id, plan_key)
    audit(bot_id, MAIN_ADMIN_ID, 'MANUAL_VIP', {'plan_key': plan_key})
    return get_bot(bot_id)


def verify_paid_evidence(order, evidence):
    if not isinstance(evidence, dict) or str(evidence.get('status')) != '1':
        raise ValueError('支付尚未成功')
    for key in ('unique_id', 'out_trade_no', 'merchant_order_no'):
        if evidence.get(key) is not None and str(evidence[key]) != str(order['order_no']):
            raise ValueError('支付订单号不匹配')
    if evidence.get('order_id') is not None and order.get('okpay_order_id') and str(evidence['order_id']) != str(order['okpay_order_id']):
        raise ValueError('支付平台订单号不匹配')
    for key in ('amount', 'pay_amount', 'paid_amount'):
        if evidence.get(key) is not None:
            try:
                value, expected = Decimal(str(evidence[key])), Decimal(str(order['amount']))
                if not value.is_finite() or abs(value - expected) > Decimal('0.000001'):
                    raise ValueError('支付金额不匹配')
            except InvalidOperation as exc:
                raise ValueError('支付金额无效') from exc
    for key in ('coin', 'currency'):
        if evidence.get(key) is not None and str(evidence[key]).upper() != str(order.get('currency') or 'USDT').upper():
            raise ValueError('支付币种不匹配')
    return True


def settle_order(order_no, actor_id, evidence=None):
    with transaction() as con:
        row = con.execute('SELECT * FROM orders WHERE order_no=?', (order_no,)).fetchone()
        if not row:
            raise ValueError('订单不存在')
        order = dict(row)
        if int(order['owner_id']) != int(actor_id) and int(actor_id) != MAIN_ADMIN_ID:
            raise PermissionError('无权操作此订单')
        bot = con.execute('SELECT * FROM bots WHERE id=? AND deleted_at IS NULL', (order['bot_id'],)).fetchone()
        if not bot or int(bot['owner_id']) != int(order['owner_id']):
            raise ValueError('机器人归属已变化，订单不能自动结算，请联系管理员')
        if order['status'] == 'paid':
            order['already_paid'] = True
            return order
        if order['status'] != 'pending':
            raise ValueError('订单已关闭')
        verify_paid_evidence(order, evidence)
        inserted = con.execute('INSERT OR IGNORE INTO entitlement_grants VALUES(?,?,?,?,?)', (order_no, order['bot_id'], actor_id, order['plan_key'], time.time())).rowcount
        if inserted:
            _grant(con, order['bot_id'], order['plan_key'])
        con.execute("UPDATE orders SET status='paid',paid_at=?,evidence=? WHERE order_no=? AND status='pending'", (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), json.dumps(evidence, ensure_ascii=False), order_no))
        con.execute('INSERT INTO audit_logs(bot_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)', (order['bot_id'], actor_id, 'SETTLE_ORDER', json.dumps({'order_no': order_no, 'granted': bool(inserted)}), time.time()))
        result = dict(con.execute('SELECT * FROM orders WHERE order_no=?',(order_no,)).fetchone())
        result['already_paid'] = not bool(inserted)
        return result


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def has_capability(bot_id, feature):
    bot = get_bot(bot_id)
    if not bot or bot.get('deleted_at') is not None:
        return False
    row = get_db().execute('SELECT enabled FROM vip_features WHERE key=?', (feature,)).fetchone()
    if not row or not row[0]:
        return True
    return bot['version'] == '高级版' and (bot['expire_time'] == '永久' or (bot.get('expires_at') or 0) > time.time())


def require_capability(bot_id, feature):
    if not has_capability(bot_id, feature):
        raise ValueError('此功能当前需高级版；原有配置仍保留，可升级后新增或修改')


def transfer_vip_time(source_id, target_id, actor_id):
    if int(source_id) == int(target_id):
        raise ValueError('不能转给同一个机器人')
    with transaction() as con:
        source = con.execute('SELECT * FROM bots WHERE id=? AND deleted_at IS NULL', (source_id,)).fetchone()
        target = con.execute('SELECT * FROM bots WHERE id=? AND deleted_at IS NULL', (target_id,)).fetchone()
        if not source or not target or int(source['owner_id']) != int(actor_id) or int(target['owner_id']) != int(actor_id):
            raise PermissionError('只可在自己拥有的机器人之间转移')
        if source['expire_time'] == '永久':
            raise ValueError('永久套餐不能转移剩余时间')
        if source['version'] != '高级版' or (source['expire_time'] != '永久' and (source['expires_at'] or 0) <= time.time()):
            raise ValueError('来源机器人没有可转移权益')
        if target['expire_time'] == '永久':
            raise ValueError('目标已是永久高级版')
        if source['expire_time'] == '永久':
            con.execute("UPDATE bots SET version='高级版',expire_time='永久',expires_at=NULL WHERE id=?", (target_id,))
        else:
            expiry = max(time.time(), target['expires_at'] or 0) + source['expires_at'] - time.time()
            con.execute("UPDATE bots SET version='高级版',expire_time=?,expires_at=? WHERE id=?", (datetime.fromtimestamp(expiry, ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'), expiry, target_id))
        con.execute("UPDATE bots SET version='普通版',expire_time='－',expires_at=NULL WHERE id=?", (source_id,))
        con.execute('INSERT INTO audit_logs(bot_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)', (source_id, actor_id, 'TRANSFER_VIP', json.dumps({'target_id': target_id}), time.time()))
    return get_bot(target_id)


def get_all_orders(limit=50, offset=0):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_orders_count():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM orders")
    row = c.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def check_expired_vips():
    with transaction() as con:
        rows = con.execute("SELECT * FROM bots WHERE version='高级版' AND expire_time!='永久' AND expires_at IS NOT NULL AND expires_at<=?", (time.time(),)).fetchall()
        for row in rows:
            con.execute("UPDATE bots SET version='普通版',expire_time='－',expires_at=NULL WHERE id=?", (row['id'],))
    return [dict(row) for row in rows]


class OkayPay:
    """OkPay支付API封装（对齐商城机器人实现）"""
    def __init__(self):
        cfg = get_okpay_config()
        self.appid = str(cfg["appid"])
        self.token = str(cfg["token"])
        self.api_url = cfg["api_url"].rstrip("/") + "/"
        self.callback_url = cfg["callback_url"]

    def _flatten(self, data, prefix=""):
        out = {}
        for k, v in data.items():
            key = str(k) if prefix == "" else f"{prefix}.{k}"
            if isinstance(v, dict):
                out.update(self._flatten(v, key))
                continue
            if isinstance(v, bool):
                out[key] = "true" if v else "false"
                continue
            if v is None or v == "":
                continue
            out[key] = str(v)
        return out

    def _build_base(self, params):
        data = {k: v for k, v in params.items() if k != "sign"}
        flat = self._flatten(data)
        sorted_keys = sorted(flat.keys())
        return "&".join(f"{k}={flat[k]}" for k in sorted_keys)

    def _sign(self, params):
        import hmac
        base = self._build_base(params).encode("utf-8")
        return hmac.new(self.token.encode("utf-8"), base, hashlib.sha256).hexdigest().upper()

    def _signed_request(self, params):
        p = dict(params)
        p["id"] = self.appid
        p["timestamp"] = int(datetime.now().timestamp())
        p["nonce"] = secrets.token_hex(8)
        p["sign"] = self._sign(p)
        return p

    async def _request(self, endpoint, params):
        submit_params = self._signed_request(params)
        url = self.api_url + endpoint
        logger.info('[OkPay] 请求 endpoint=%s', endpoint)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=submit_params, timeout=15) as resp:
                    result = await resp.json(content_type=None)
                    logger.info('[OkPay] 响应 endpoint=%s code=%s', endpoint, result.get('code') if isinstance(result, dict) else 'invalid')
                    return result
        except Exception as e:
            logger.error(f"[OkPay] 请求异常: {e}")
            return {"code": -1, "error": str(e)}

    async def pay_link(self, amount, unique_id, name="商品购买", coin="USDT", return_url=None):
        params = {
            "unique_id": unique_id,
"name": name,
            "amount": str(amount),
            "coin": coin,
        }
        if self.callback_url:
            params["callback_url"] = self.callback_url
        if return_url:
            params["return_url"] = return_url
        return await self._request("payLink", params)

    async def check_deposit(self, unique_id):
        return await self._request("checkDeposit", {"unique_id": unique_id})


def get_okpay_client():
    cfg = get_okpay_config()
    if not cfg["appid"] or not cfg["token"]:
        return None
    return OkayPay()

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
