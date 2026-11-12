# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

from __future__ import annotations

from datetime import datetime, timedelta
import json
import time
import regex

from .database import get_db, transaction
from .configuration import get_setting, set_setting, get_bot_now


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def add_user(bot_id, user_id, username, first_name, verified=0):
    con=get_db()
    con.execute('INSERT INTO users(bot_id,user_id,username,first_name,verified,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(bot_id,user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,verified=max(users.verified,excluded.verified),blocked_by_bot=0',
                (bot_id,user_id,username or '',first_name or '',int(verified),_now()))
    con.commit()


def get_user(bot_id,user_id):
    row=get_db().execute('SELECT * FROM users WHERE bot_id=? AND user_id=?',(bot_id,user_id)).fetchone()
    return dict(row) if row else None


def update_user_tip_count(bot_id,user_id,tip_count):
    get_db().execute('UPDATE users SET tip_count=? WHERE bot_id=? AND user_id=?',(tip_count,bot_id,user_id));get_db().commit()


def update_user_last_op_notify(bot_id,user_id,time_str):
    get_db().execute('UPDATE users SET last_op_notify=? WHERE bot_id=? AND user_id=?',(time_str,bot_id,user_id));get_db().commit()


def expire_mutes(bot_id=None):
    args=(time.time(),) if bot_id is None else (time.time(),bot_id)
    where='expires_at IS NOT NULL AND expires_at<=?' + ('' if bot_id is None else ' AND bot_id=?')
    with transaction() as con:
        rows=con.execute('SELECT bot_id,user_id FROM blacklist WHERE '+where,args).fetchall()
        for row in rows:
            con.execute('UPDATE users SET blocked=0 WHERE bot_id=? AND user_id=?',(row['bot_id'],row['user_id']))
        con.execute('DELETE FROM blacklist WHERE '+where,args)
    return len(rows)


def get_all_users(bot_id):
    expire_mutes(bot_id)
    return [dict(r) for r in get_db().execute('SELECT * FROM users WHERE bot_id=? AND blocked=0 ORDER BY id DESC',(bot_id,))]


def get_recent_users(bot_id,limit=20):
    return [dict(r) for r in get_db().execute('SELECT u.*,max(m.created_at) last_active FROM users u LEFT JOIN messages m ON u.bot_id=m.bot_id AND u.user_id=m.user_id AND m.direction=\'user_to_admin\' WHERE u.bot_id=? GROUP BY u.user_id ORDER BY last_active DESC,u.id DESC LIMIT ?',(bot_id,limit))]


def format_relative_time(time_str):
    if not time_str:return '从未'
    try:
        seconds=max(0,int((datetime.now()-datetime.strptime(time_str,'%Y-%m-%d %H:%M:%S')).total_seconds()))
        return '刚刚' if seconds<60 else f'{seconds//60}分钟前' if seconds<3600 else f'{seconds//3600}小时前' if seconds<86400 else f'{seconds//86400}天前'
    except (ValueError,TypeError):return str(time_str)


def get_welcome_messages(bot_id):
    return [dict(r) for r in get_db().execute('SELECT * FROM welcome_messages WHERE bot_id=? ORDER BY sort_order,id',(bot_id,))]


def get_welcome_count(bot_id):
    return get_db().execute('SELECT count(*) FROM welcome_messages WHERE bot_id=?',(bot_id,)).fetchone()[0]


def get_welcome_message(bot_id,wm_id):
    row=get_db().execute('SELECT * FROM welcome_messages WHERE bot_id=? AND id=?',(bot_id,wm_id)).fetchone()
    return dict(row) if row else None


def add_welcome_message(bot_id,content_type,content_text='',file_id=''):
    with transaction() as con:
        order=con.execute('SELECT coalesce(max(sort_order),0)+1 FROM welcome_messages WHERE bot_id=?',(bot_id,)).fetchone()[0]
        return con.execute('INSERT INTO welcome_messages(bot_id,content_type,content_text,file_id,sort_order,created_at) VALUES(?,?,?,?,?,?)',(bot_id,content_type,content_text,file_id,order,_now())).lastrowid


def update_welcome_message(bot_id,wm_id,**fields):
    allowed={'content_type','content_text','file_id','payload','enabled','sort_order'}
    if not fields or set(fields)-allowed:raise ValueError('无效欢迎语字段')
    values=[json.dumps(v,ensure_ascii=False) if k=='payload' and isinstance(v,dict) else v for k,v in fields.items()]
    get_db().execute('UPDATE welcome_messages SET '+','.join(k+'=?' for k in fields)+' WHERE bot_id=? AND id=?',values+[bot_id,wm_id]);get_db().commit()


def delete_welcome_message(bot_id,wm_id):
    get_db().execute('DELETE FROM welcome_messages WHERE bot_id=? AND id=?',(bot_id,wm_id));get_db().commit()


def get_random_welcome(bot_id):
    row=get_db().execute('SELECT * FROM welcome_messages WHERE bot_id=? AND enabled=1 ORDER BY sort_order,id LIMIT 1',(bot_id,)).fetchone()
    return dict(row) if row else None


def update_user_welcome_time(bot_id,user_id):
    get_db().execute('UPDATE users SET last_welcome_time=? WHERE bot_id=? AND user_id=?',(_now(),bot_id,user_id));get_db().commit()


def should_send_welcome(bot_id,user_id):
    user=get_user(bot_id,user_id)
    try:return not user or not user['last_welcome_time'] or (datetime.now()-datetime.strptime(user['last_welcome_time'],'%Y-%m-%d %H:%M:%S')).total_seconds()>=86400
    except ValueError:return True


def get_auto_replies(bot_id,enabled_only=False):
    return [dict(r) for r in get_db().execute('SELECT * FROM auto_replies WHERE bot_id=?'+(' AND enabled=1' if enabled_only else '')+' ORDER BY sort_order,id',(bot_id,))]


def get_auto_reply(bot_id,ar_id):
    row=get_db().execute('SELECT * FROM auto_replies WHERE bot_id=? AND id=?',(bot_id,ar_id)).fetchone()
    return dict(row) if row else None
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询



def add_auto_reply(bot_id,keyword,match_mode='contains'):
    if match_mode not in ('contains','exact','regex'):raise ValueError('匹配模式无效')
    if not keyword or len(keyword)>512:raise ValueError('关键词长度必须为1至512')
    if match_mode=='regex':regex.compile(keyword)
    con=get_db();cursor=con.execute('INSERT INTO auto_replies(bot_id,keyword,match_mode,enabled,created_at) VALUES(?,?,?,0,?)',(bot_id,keyword,match_mode,_now()));con.commit()
    return cursor.lastrowid


def update_auto_reply(bot_id,ar_id,**fields):
    allowed={'keyword','match_mode','reply_type','reply_text','file_id','inline_kb','reply_kb','payload','enabled','sort_order'}
    if not fields or set(fields)-allowed:raise ValueError('无效自动回复字段')
    vals=[json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for v in fields.values()]
    get_db().execute('UPDATE auto_replies SET '+','.join(k+'=?' for k in fields)+' WHERE bot_id=? AND id=?',vals+[bot_id,ar_id]);get_db().commit()


def delete_auto_reply(bot_id,ar_id):
    get_db().execute('DELETE FROM auto_replies WHERE bot_id=? AND id=?',(bot_id,ar_id));get_db().commit()


def match_auto_reply(bot_id,text):
    if not text:return None
    for row in get_auto_replies(bot_id,True):
        key=row['keyword'] or ''
        if not key:continue
        mode=row['match_mode']
        try:
            matched=(text.strip()==key.strip()) if mode=='exact' else bool(regex.search(key,text[:10000],regex.IGNORECASE,timeout=0.02)) if mode=='regex' else key.casefold() in text.casefold()
            if matched:return row
        except (regex.error,TimeoutError):continue
    return None


def get_reply_kb_config(bot_id):
    try:buttons=json.loads(get_setting(bot_id,'reply_kb_buttons','[]'))
    except ValueError:buttons=[]
    try:per_row=max(1,min(10,int(get_setting(bot_id,'reply_kb_per_row','2'))))
    except ValueError:per_row=2
    return {'enabled':get_setting(bot_id,'reply_kb_enabled','0')=='1','per_row':per_row,'buttons':buttons}


def set_reply_kb_buttons(bot_id,buttons):set_setting(bot_id,'reply_kb_buttons',json.dumps(buttons,ensure_ascii=False))
def set_reply_kb_enabled(bot_id,enabled):set_setting(bot_id,'reply_kb_enabled','1' if enabled else '0')
def set_reply_kb_per_row(bot_id,per_row):
    if not 1<=int(per_row)<=10:raise ValueError('每行按钮数1至10')
    set_setting(bot_id,'reply_kb_per_row',str(per_row))


def build_reply_keyboard(bot_id):
    from .formatting import build_reply_keyboard as build
    return build(bot_id)


def get_bot_stats(bot_id):
    expire_mutes(bot_id)
    con=get_db();today=get_bot_now(bot_id).strftime('%Y-%m-%d')
    total=con.execute('SELECT count(*) FROM users WHERE bot_id=?',(bot_id,)).fetchone()[0]
    blocked=con.execute('SELECT count(*) FROM blacklist WHERE bot_id=?',(bot_id,)).fetchone()[0]
    pending=con.execute("SELECT count(*) FROM client_cases WHERE bot_id=? AND state!='CLOSED' AND last_inbound_at IS NOT NULL AND (last_outbound_at IS NULL OR last_inbound_at>last_outbound_at)",(bot_id,)).fetchone()[0]
    return {'total_users':total,'today_new':con.execute('SELECT count(*) FROM users WHERE bot_id=? AND created_at>=?',(bot_id,today)).fetchone()[0],
            'blocked':blocked,'blocked_pct':f'{blocked/total*100:.2f}' if total else '0.00','pending':pending,
            'active_today':con.execute('SELECT count(DISTINCT user_id) FROM messages WHERE bot_id=? AND created_at>=?',(bot_id,today)).fetchone()[0],
            'messages_today':con.execute('SELECT count(*) FROM messages WHERE bot_id=? AND created_at>=?',(bot_id,today)).fetchone()[0],
            'update_time':get_bot_now(bot_id).strftime('%H:%M:%S')}


def set_conversation(bot_id,admin_id,user_id):
    con=get_db();con.execute('INSERT INTO conversations(bot_id,admin_id,current_user_id,updated_at) VALUES(?,?,?,?) ON CONFLICT(bot_id,admin_id) DO UPDATE SET current_user_id=excluded.current_user_id,updated_at=excluded.updated_at',(bot_id,admin_id,user_id,_now()));con.commit()


def get_conversation(bot_id,admin_id=None):
    if admin_id is None:return None
    row=get_db().execute('SELECT * FROM conversations WHERE bot_id=? AND admin_id=?',(bot_id,admin_id)).fetchone()
    return dict(row) if row else None


def is_blocked(bot_id,user_id):
    row=get_db().execute('SELECT expires_at FROM blacklist WHERE bot_id=? AND user_id=?',(bot_id,user_id)).fetchone()
    if not row:return False
    if row[0] is not None and row[0]<=time.time():
        unblock_user(bot_id,user_id);return False
    return True


def block_user(bot_id,user_id,reason='',duration_seconds=None):
    deadline=time.time()+float(duration_seconds) if duration_seconds is not None else None
    if duration_seconds is not None and float(duration_seconds)<=0:raise ValueError('禁言时长必须大于0')
    with transaction() as con:
        con.execute('INSERT INTO blacklist(bot_id,user_id,reason,created_at,expires_at) VALUES(?,?,?,?,?) ON CONFLICT(bot_id,user_id) DO UPDATE SET reason=excluded.reason,created_at=excluded.created_at,expires_at=excluded.expires_at',(bot_id,user_id,reason,_now(),deadline))
        con.execute('UPDATE users SET blocked=1 WHERE bot_id=? AND user_id=?',(bot_id,user_id))


def unblock_user(bot_id,user_id):
    with transaction() as con:
        con.execute('DELETE FROM blacklist WHERE bot_id=? AND user_id=?',(bot_id,user_id))
        con.execute('UPDATE users SET blocked=0 WHERE bot_id=? AND user_id=?',(bot_id,user_id))


def find_user_by_admin_message(bot_id,message_id,admin_chat_id=None):
    if admin_chat_id is None:return None
    row=get_db().execute('SELECT user_id FROM relay_routes WHERE bot_id=? AND admin_chat_id=? AND admin_message_id=?',(bot_id,admin_chat_id,message_id)).fetchone()
    return int(row[0]) if row else None


def save_message(bot_id,user_id,direction,content,admin_msg_id=0,user_msg_id=0,admin_chat_id=0,delivery_status='SUCCESS'):
    with transaction() as con:
        cursor=con.execute('INSERT INTO messages(bot_id,user_id,direction,content,admin_message_id,user_message_id,created_at,admin_chat_id,delivery_status) VALUES(?,?,?,?,?,?,?,?,?)',(bot_id,user_id,direction,content,admin_msg_id,user_msg_id,_now(),admin_chat_id,delivery_status))
        if direction=='user_to_admin' and delivery_status=='SUCCESS' and admin_msg_id and admin_chat_id:
            con.execute('INSERT OR REPLACE INTO relay_routes VALUES(?,?,?,?,?,?)',(bot_id,admin_chat_id,admin_msg_id,user_id,user_msg_id,time.time()))
        if delivery_status=='SUCCESS':
            column='last_inbound_at' if direction=='user_to_admin' else 'last_outbound_at'
            con.execute(f'INSERT INTO client_cases(bot_id,user_id,{column}) VALUES(?,?,?) ON CONFLICT(bot_id,user_id) DO UPDATE SET {column}=excluded.{column}',(bot_id,user_id,time.time()))
            if direction=='user_to_admin':
                con.execute("UPDATE client_cases SET state='OPEN',reminder_count=0 WHERE bot_id=? AND user_id=?",(bot_id,user_id))
        return cursor.lastrowid

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
