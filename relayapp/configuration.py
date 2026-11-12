# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

from __future__ import annotations
import json
from datetime import datetime
from .database import get_db
from .defaults import *

def get_setting(bot_id: int, key: str, default: str = "") -> str:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE bot_id = ? AND key = ?", (bot_id, key))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(bot_id: int, key: str, value: str):
    from .database import transaction
    with transaction() as conn:
        conn.execute('INSERT INTO settings(bot_id,key,value) VALUES(?,?,?) ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value', (bot_id,key,str(value)))


def get_bot_timezone(bot_id: int) -> str:
    """获取机器人设置的时区，默认 Asia/Shanghai"""
    return get_setting(bot_id, "timezone", "Asia/Shanghai") or "Asia/Shanghai"


def get_bot_now(bot_id: int) -> datetime:
    """获取机器人时区下的当前时间"""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(get_bot_timezone(bot_id))
        return datetime.now(tz)
    except:
        return datetime.now()


def format_bot_time(bot_id: int, time_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """把服务器本地时间字符串转换为机器人时区的可读时间（服务器在美国，默认转上海）"""
    if not time_str or time_str in ("-", "永久", "－"):
        return time_str
    try:
        from zoneinfo import ZoneInfo
        naive = datetime.strptime(time_str, fmt)
        # 用服务器本地时区解析存储的naive时间
        server_tz = datetime.now().astimezone().tzinfo
        localized = naive.replace(tzinfo=server_tz)
        bot_tz = ZoneInfo(get_bot_timezone(bot_id))
        converted = localized.astimezone(bot_tz)
        return converted.strftime(fmt)
    except:
        return time_str


def get_main_text(key: str, **kwargs) -> str:
    """获取主机器人文案，支持变量替换（用replace避免值中含{}导致format报错）"""
    val = get_setting(0, f"text_{key}", DEFAULT_TEXTS.get(key, ""))
    for k, v in kwargs.items():
        val = val.replace("{" + k + "}", str(v))
    return val


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

def set_main_text(key: str, value: str):
    set_setting(0, f"text_{key}", value)


def get_main_button(key: str) -> dict:
    """获取主机器人按钮配置"""
    import json
    val = get_setting(0, f"btn_{key}", "")
    if val:
        try:
            return json.loads(val)
        except:
            pass
    return DEFAULT_BUTTONS.get(key, {}).copy()


def set_main_button(key: str, btn: dict):
    import json
    set_setting(0, f"btn_{key}", json.dumps(btn, ensure_ascii=False))


def get_all_main_buttons() -> dict:
    """获取所有按钮配置"""
    result = {}
    for key in DEFAULT_BUTTONS:
        result[key] = get_main_button(key)
    return result


def is_text_modified(key: str) -> bool:
    """判断文案是否已被用户修改过"""
    return get_setting(0, f"text_{key}", "") != ""


def is_button_modified(key: str) -> bool:
    """判断按钮是否已被用户修改过"""
    return get_setting(0, f"btn_{key}", "") != ""


def init_vip_features():
    conn = get_db()
    c = conn.cursor()
    for key, name in DEFAULT_VIP_FEATURES.items():
        c.execute("INSERT OR IGNORE INTO vip_features (key, name, enabled) VALUES (?,?,0)", (key, name))
    conn.commit()
    conn.close()


def get_vip_features():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM vip_features")
    rows = c.fetchall()
    conn.close()
    return {r["key"]: {"name": r["name"], "enabled": r["enabled"]} for r in rows}


def toggle_vip_feature(key):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE vip_features SET enabled = 1 - enabled WHERE key=?", (key,))
    conn.commit()
    conn.close()

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
