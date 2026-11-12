# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

from __future__ import annotations

from datetime import datetime
import json
import secrets
import time

from .config import MAIN_ADMIN_ID
from .database import get_db, transaction


def audit(bot_id, actor_id, action, detail=None):
    con = get_db()
    con.execute('INSERT INTO audit_logs(bot_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)',
                (bot_id,actor_id,action,json.dumps(detail or {},ensure_ascii=False),time.time()))
    con.commit()


def get_bot(bot_id):
    row = get_db().execute('SELECT * FROM bots WHERE id=?',(bot_id,)).fetchone()
    return dict(row) if row else None


def get_bot_by_token(bot_token):
    row = get_db().execute('SELECT * FROM bots WHERE bot_token=?',(bot_token,)).fetchone()
    return dict(row) if row else None


def get_bot_by_telegram_id(telegram_bot_id):
    row = get_db().execute('SELECT * FROM bots WHERE telegram_bot_id=?',(telegram_bot_id,)).fetchone()
    return dict(row) if row else None


def get_bots_by_owner(owner_id):
    return [dict(r) for r in get_db().execute('SELECT * FROM bots WHERE owner_id=? AND deleted_at IS NULL ORDER BY id DESC',(owner_id,))]


def get_all_active_bots():
    return [dict(r) for r in get_db().execute("SELECT * FROM bots WHERE desired_state='RUNNING' AND deleted_at IS NULL ORDER BY id")]


def get_user_bots_count(user_id):
    return get_db().execute('SELECT count(*) FROM bots WHERE owner_id=? AND deleted_at IS NULL',(user_id,)).fetchone()[0]


def add_bot(bot_token, bot_username, bot_name, owner_id):
    identity = str(bot_token).partition(':')[0]
    if not identity.isdigit():
        raise ValueError('Token格式无效')
    with transaction() as con:
        limit_row=con.execute("SELECT value FROM settings WHERE bot_id=0 AND key='free_bot_limit'").fetchone()
        limit=int(limit_row[0]) if limit_row else 5
        count=con.execute('SELECT count(*) FROM bots WHERE owner_id=? AND deleted_at IS NULL',(owner_id,)).fetchone()[0]
        vip_required=con.execute("SELECT enabled FROM vip_features WHERE key='unlimited_bots'").fetchone()
        vip=con.execute("SELECT 1 FROM bots WHERE owner_id=? AND version='高级版' AND deleted_at IS NULL AND (expire_time='永久' OR expires_at>?)",(owner_id,time.time())).fetchone()
        privileged=bool(vip) and (vip_required is None or bool(vip_required[0]))
        if vip_required is not None and not vip_required[0]:
            privileged=True
        if count>=limit and not privileged and owner_id!=MAIN_ADMIN_ID:
            raise ValueError(f'普通账号最多新增至{limit}个机器人；现有机器人不会被移除')
        cursor=con.execute('INSERT INTO bots(bot_token,telegram_bot_id,bot_username,bot_name,owner_id,created_at) VALUES(?,?,?,?,?,?)',
                           (bot_token,int(identity),bot_username,bot_name,owner_id,datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        return cursor.lastrowid


def touch_main_user(user_id, username, first_name):
    con=get_db()
    con.execute('INSERT INTO main_users(user_id,username,first_name,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,blocked=0',
                (user_id,username or '',first_name or '',datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    con.commit()


def inc_main_user_click(user_id):
    get_db().execute('UPDATE main_users SET click_count=click_count+1 WHERE user_id=?',(user_id,));get_db().commit()


def inc_main_user_msg(user_id):
    get_db().execute('UPDATE main_users SET msg_count=msg_count+1 WHERE user_id=?',(user_id,));get_db().commit()
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询



def get_all_main_users():
    return [dict(r) for r in get_db().execute('SELECT * FROM main_users ORDER BY created_at DESC')]


def ensure_owner_admin(bot_id, owner_id):
    con=get_db()
    con.execute('INSERT OR IGNORE INTO bot_admins(bot_id,admin_id,added_by,created_at) VALUES(?,?,?,?)',(bot_id,owner_id,owner_id,datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    con.commit()


def is_bot_admin(bot_id, user_id):
    bot=get_bot(bot_id)
    if not bot or bot.get('deleted_at') is not None:return False
    return int(bot.get('owner_id') or 0)==int(user_id) or bool(get_db().execute('SELECT 1 FROM bot_admins WHERE bot_id=? AND admin_id=?',(bot_id,user_id)).fetchone())


def get_bot_admins(bot_id):
    bot=get_bot(bot_id)
    if not bot or bot.get('deleted_at') is not None:return []
    rows=get_db().execute('SELECT admin_id FROM bot_admins WHERE bot_id=?',(bot_id,))
    return sorted({int(bot['owner_id'])}|{int(r[0]) for r in rows if r[0]})


def add_bot_admin(bot_id, admin_id, added_by):
    bot=get_bot(bot_id)
    if not bot or int(bot['owner_id'])!=int(added_by):raise ValueError('仅机器人主人可添加管理员')
    if int(admin_id)<=0:raise ValueError('用户ID必须为正整数')
    con=get_db()
    con.execute('INSERT OR IGNORE INTO bot_admins(bot_id,admin_id,added_by,created_at) VALUES(?,?,?,?)',(bot_id,admin_id,added_by,datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    con.commit();audit(bot_id,added_by,'ADD_ADMIN',{'admin_id':admin_id})


def remove_bot_admin(bot_id, admin_id, actor_id=None):
    bot=get_bot(bot_id)
    if not bot:raise ValueError('机器人不存在')
    if actor_id is not None and int(bot['owner_id'])!=int(actor_id):raise ValueError('仅主人可移除管理员')
    if int(bot['owner_id'])==int(admin_id):raise ValueError('不能移除机器人主人')
    with transaction() as con:
        con.execute('DELETE FROM bot_admins WHERE bot_id=? AND admin_id=?',(bot_id,admin_id))
        con.execute('DELETE FROM conversations WHERE bot_id=? AND admin_id=?',(bot_id,admin_id))
        con.execute('DELETE FROM ui_sessions WHERE bot_id=? AND user_id=?',(bot_id,admin_id))
        con.execute('UPDATE client_cases SET assigned_admin_id=NULL WHERE bot_id=? AND assigned_admin_id=?',(bot_id,admin_id))
    audit(bot_id,actor_id or bot['owner_id'],'REMOVE_ADMIN',{'admin_id':admin_id})


def request_transfer(bot_id, actor_id, target_id):
    if int(target_id)<=0 or int(target_id)==int(actor_id):raise ValueError('请输入不同的有效接收者ID')
    nonce=secrets.token_urlsafe(12)
    with transaction() as con:
        bot=con.execute('SELECT * FROM bots WHERE id=? AND deleted_at IS NULL',(bot_id,)).fetchone()
        if not bot or int(bot['owner_id'])!=int(actor_id):raise ValueError('机器人归属已变化，请重新操作')
        con.execute("UPDATE owner_transfers SET state='CANCELLED' WHERE bot_id=? AND state='PENDING'",(bot_id,))
        con.execute('INSERT INTO owner_transfers(nonce,bot_id,from_user_id,to_user_id,expires_at) VALUES(?,?,?,?,?)',(nonce,bot_id,actor_id,target_id,time.time()+900))
    audit(bot_id,actor_id,'REQUEST_TRANSFER',{'target_id':target_id})
    return nonce


def accept_transfer(nonce, target_id):
    with transaction() as con:
        row=con.execute("SELECT * FROM owner_transfers WHERE nonce=? AND state='PENDING'",(nonce,)).fetchone()
        if not row or int(row['to_user_id'])!=int(target_id) or row['expires_at']<=time.time():raise ValueError('转移邀请无效或已过期')
        bot=con.execute('SELECT * FROM bots WHERE id=? AND deleted_at IS NULL',(row['bot_id'],)).fetchone()
        if not bot or int(bot['owner_id'])!=int(row['from_user_id']):raise ValueError('机器人归属已变化')
        if not con.execute('SELECT 1 FROM main_users WHERE user_id=?',(target_id,)).fetchone():
            raise ValueError('接收者须先启动主机器人')
        con.execute('UPDATE bots SET owner_id=?,generation=generation+1 WHERE id=? AND owner_id=?',(target_id,row['bot_id'],row['from_user_id']))
        con.execute('DELETE FROM bot_admins WHERE bot_id=?',(row['bot_id'],))
        con.execute('INSERT INTO bot_admins(bot_id,admin_id,added_by,created_at) VALUES(?,?,?,?)',(row['bot_id'],target_id,target_id,datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        con.execute('DELETE FROM conversations WHERE bot_id=?',(row['bot_id'],))
        con.execute('DELETE FROM ui_sessions WHERE bot_id=?',(row['bot_id'],))
        con.execute('UPDATE client_cases SET assigned_admin_id=NULL WHERE bot_id=?',(row['bot_id'],))
        con.execute("UPDATE owner_transfers SET state='ACCEPTED' WHERE nonce=?",(nonce,))
        con.execute("UPDATE managed_setup_jobs SET state='cancelled' WHERE telegram_bot_id=?",(bot['telegram_bot_id'],))
        con.execute("UPDATE broadcast_jobs SET status='PAUSED',updated_at=? WHERE bot_id=? AND status IN ('PENDING','RUNNING')",(time.time(),row['bot_id']))
        result=dict(row)
    audit(result['bot_id'],target_id,'ACCEPT_TRANSFER',{'from_user_id':result['from_user_id']})
    return result

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
