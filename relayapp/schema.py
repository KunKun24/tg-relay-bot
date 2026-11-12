# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

from __future__ import annotations

from datetime import datetime, time as day_time
import json
import time
from zoneinfo import ZoneInfo

BASE = '''
CREATE TABLE IF NOT EXISTS bots(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_token TEXT UNIQUE,bot_username TEXT,bot_name TEXT,owner_id INTEGER,channel_id TEXT,welcome_text TEXT,status TEXT DEFAULT 'active',created_at TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,user_id INTEGER,username TEXT,first_name TEXT,verified INTEGER DEFAULT 0,blocked INTEGER DEFAULT 0,created_at TEXT,UNIQUE(bot_id,user_id));
CREATE TABLE IF NOT EXISTS conversations(bot_id INTEGER,admin_id INTEGER,current_user_id INTEGER,updated_at TEXT,PRIMARY KEY(bot_id,admin_id));
CREATE TABLE IF NOT EXISTS bot_admins(bot_id INTEGER NOT NULL,admin_id INTEGER NOT NULL,added_by INTEGER,created_at TEXT,PRIMARY KEY(bot_id,admin_id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,user_id INTEGER,direction TEXT,content TEXT,admin_message_id INTEGER,user_message_id INTEGER,created_at TEXT);
CREATE TABLE IF NOT EXISTS blacklist(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,user_id INTEGER,reason TEXT,created_at TEXT,UNIQUE(bot_id,user_id));
CREATE TABLE IF NOT EXISTS settings(bot_id INTEGER,key TEXT,value TEXT,PRIMARY KEY(bot_id,key));
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,order_no TEXT UNIQUE,bot_id INTEGER,owner_id INTEGER,plan_key TEXT,plan_name TEXT,amount REAL,pay_url TEXT,okpay_order_id TEXT,status TEXT DEFAULT 'pending',created_at TEXT,paid_at TEXT);
CREATE TABLE IF NOT EXISTS managed_setup_jobs(telegram_bot_id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL,bot_username TEXT,update_id INTEGER NOT NULL,attempts INTEGER DEFAULT 0,next_retry REAL DEFAULT 0,state TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS main_users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,click_count INTEGER DEFAULT 0,msg_count INTEGER DEFAULT 0,created_at TEXT);
CREATE TABLE IF NOT EXISTS vip_features(key TEXT PRIMARY KEY,name TEXT,enabled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS welcome_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,content_type TEXT,content_text TEXT,file_id TEXT,sort_order INTEGER DEFAULT 0,created_at TEXT);
CREATE TABLE IF NOT EXISTS auto_replies(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,keyword TEXT,match_mode TEXT DEFAULT 'contains',reply_type TEXT DEFAULT 'text',reply_text TEXT,file_id TEXT,inline_kb TEXT,reply_kb TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at REAL);
'''

EXTRA = '''
CREATE TABLE IF NOT EXISTS client_cases(bot_id INTEGER,user_id INTEGER,assigned_admin_id INTEGER,state TEXT DEFAULT 'OPEN',last_inbound_at REAL,last_outbound_at REAL,reminder_count INTEGER DEFAULT 0,last_reminded_at REAL,notes TEXT DEFAULT '',PRIMARY KEY(bot_id,user_id));
CREATE TABLE IF NOT EXISTS relay_routes(bot_id INTEGER,admin_chat_id INTEGER,admin_message_id INTEGER,user_id INTEGER,original_message_id INTEGER,created_at REAL,PRIMARY KEY(bot_id,admin_chat_id,admin_message_id));
CREATE TABLE IF NOT EXISTS ui_sessions(bot_id INTEGER,user_id INTEGER,state TEXT,data TEXT,nonce TEXT,expires_at REAL,PRIMARY KEY(bot_id,user_id));
CREATE TABLE IF NOT EXISTS group_bindings(bot_id INTEGER,chat_id INTEGER,title TEXT,kind TEXT,enabled INTEGER DEFAULT 1,staff_group INTEGER DEFAULT 0,welcome_payload TEXT DEFAULT '{}',welcome_enabled INTEGER DEFAULT 0,PRIMARY KEY(bot_id,chat_id));
CREATE TABLE IF NOT EXISTS filter_rules(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,pattern TEXT,mode TEXT,action TEXT,duration_seconds INTEGER,enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS commands(bot_id INTEGER,command TEXT,description TEXT,payload TEXT,enabled INTEGER DEFAULT 1,PRIMARY KEY(bot_id,command));
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,actor_id INTEGER,action TEXT,detail TEXT,created_at REAL);
CREATE TABLE IF NOT EXISTS owner_transfers(nonce TEXT PRIMARY KEY,bot_id INTEGER,from_user_id INTEGER,to_user_id INTEGER,expires_at REAL,state TEXT DEFAULT 'PENDING');
CREATE TABLE IF NOT EXISTS entitlement_grants(order_no TEXT PRIMARY KEY,bot_id INTEGER,actor_id INTEGER,plan_key TEXT,created_at REAL);
CREATE TABLE IF NOT EXISTS broadcast_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,actor_id INTEGER,payload TEXT,status TEXT DEFAULT 'PENDING',progress_chat_id INTEGER,progress_message_id INTEGER,created_at REAL,updated_at REAL,last_progress REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS broadcast_recipients(job_id INTEGER,user_id INTEGER,status TEXT DEFAULT 'PENDING',attempts INTEGER DEFAULT 0,next_attempt REAL DEFAULT 0,message_id INTEGER,error TEXT,updated_at REAL,PRIMARY KEY(job_id,user_id));
CREATE TABLE IF NOT EXISTS relay_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,bot_id INTEGER,target_chat_id INTEGER,payload TEXT,status TEXT DEFAULT 'PENDING',message_id INTEGER,error TEXT,created_at REAL,updated_at REAL);
CREATE INDEX IF NOT EXISTS idx_messages_admin_msg ON messages(bot_id,admin_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(bot_id,user_id,created_at);
CREATE INDEX IF NOT EXISTS idx_recipients_due ON broadcast_recipients(status,next_attempt,job_id);
CREATE INDEX IF NOT EXISTS idx_cases_pending ON client_cases(bot_id,state,last_inbound_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expire ON ui_sessions(expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_telegram_identity ON bots(telegram_bot_id) WHERE telegram_bot_id IS NOT NULL;
'''
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询


COLUMNS = {
    'bots': {'version': "TEXT DEFAULT '普通版'", 'expire_time': "TEXT DEFAULT '－'", 'telegram_bot_id': 'INTEGER', 'desired_state': "TEXT DEFAULT 'RUNNING'", 'actual_state': "TEXT DEFAULT 'STOPPED'", 'last_error': "TEXT DEFAULT ''", 'generation': 'INTEGER DEFAULT 0', 'expires_at': 'REAL', 'deleted_at': 'REAL'},
    'users': {'tip_count': 'INTEGER DEFAULT 0', 'last_op_notify': "TEXT DEFAULT ''", 'last_welcome_time': "TEXT DEFAULT ''", 'verified_at': 'REAL', 'blocked_by_bot': 'INTEGER DEFAULT 0'},
    'messages': {'admin_chat_id': 'INTEGER DEFAULT 0', 'delivery_status': "TEXT DEFAULT 'SUCCESS'"},
    'blacklist': {'expires_at': 'REAL'},
    'welcome_messages': {'payload': "TEXT DEFAULT '{}'", 'enabled': 'INTEGER DEFAULT 1'},
    'auto_replies': {'payload': "TEXT DEFAULT '{}'", 'enabled': 'INTEGER DEFAULT 1', 'sort_order': 'INTEGER DEFAULT 0'},
    'main_users': {'blocked': 'INTEGER DEFAULT 0'},
    'managed_setup_jobs': {'generation': 'INTEGER DEFAULT 0', 'last_error': "TEXT DEFAULT ''"},
    'orders': {'currency': "TEXT DEFAULT 'USDT'", 'evidence': "TEXT DEFAULT '{}'"},
}


def migrate(con):
    con.executescript(BASE)
    con.execute('BEGIN IMMEDIATE')
    try:
        fresh = con.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone() is None
        for table, columns in COLUMNS.items():
            current = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
            for name, definition in columns.items():
                if name not in current:
                    con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        pk = [r[1] for r in con.execute('PRAGMA table_info(conversations)') if r[5]]
        if pk != ['bot_id', 'admin_id']:
            con.execute('ALTER TABLE conversations RENAME TO conversations_v1')
            con.execute('CREATE TABLE conversations(bot_id INTEGER,admin_id INTEGER,current_user_id INTEGER,updated_at TEXT,PRIMARY KEY(bot_id,admin_id))')
            con.execute('INSERT OR IGNORE INTO conversations SELECT bot_id,admin_id,current_user_id,updated_at FROM conversations_v1 WHERE admin_id IS NOT NULL')
            con.execute('DROP TABLE conversations_v1')
        # Execute individual statements to keep the migration within one transaction.
        for statement in EXTRA.split(';'):
            if statement.strip():
                con.execute(statement)
        if fresh:
            for r in con.execute('SELECT id,bot_token,status,expire_time FROM bots').fetchall():
                identity = str(r['bot_token'] or '').partition(':')[0]
                if identity.isdigit():
                    con.execute('UPDATE bots SET telegram_bot_id=? WHERE id=?', (int(identity),r['id']))
                desired = 'DISCONNECTED' if r['status']=='disconnected' else 'STOPPED' if r['status']=='stopped' else 'RUNNING'
                con.execute('UPDATE bots SET desired_state=?,actual_state=? WHERE id=?',(desired,'STOPPED',r['id']))
                expiry = r['expire_time']
                if expiry and expiry not in ('永久','－','-',''):
                    try:
                        dt = datetime.strptime(expiry,'%Y-%m-%d')
                        end = datetime.combine(dt.date(),day_time(23,59,59),ZoneInfo('Asia/Shanghai')).timestamp()
                        con.execute('UPDATE bots SET expires_at=? WHERE id=?',(end,r['id']))
                    except ValueError:
                        pass
            # Historical unscoped routes belonged to the then sole owner; do not guess for other admins.
            con.execute('UPDATE messages SET admin_chat_id=coalesce((SELECT owner_id FROM bots WHERE bots.id=messages.bot_id),0) WHERE admin_chat_id=0 AND admin_message_id>0')
            con.execute('INSERT OR IGNORE INTO relay_routes SELECT bot_id,admin_chat_id,admin_message_id,user_id,user_message_id,? FROM messages WHERE admin_message_id>0 AND admin_chat_id!=0',(time.time(),))
            con.execute("UPDATE auto_replies SET enabled=0 WHERE coalesce(reply_text,'')='' AND coalesce(file_id,'')=''")
            con.execute("UPDATE welcome_messages SET enabled=0 WHERE coalesce(content_text,'')='' AND coalesce(file_id,'')=''")
            con.execute("INSERT OR IGNORE INTO entitlement_grants(order_no,bot_id,actor_id,plan_key,created_at) SELECT order_no,bot_id,owner_id,plan_key,? FROM orders WHERE status='paid'",(time.time(),))
            for r in con.execute('SELECT DISTINCT bot_id,user_id FROM messages').fetchall():
                inbound=con.execute("SELECT max(created_at) FROM messages WHERE bot_id=? AND user_id=? AND direction='user_to_admin'",(r['bot_id'],r['user_id'])).fetchone()[0]
                outbound=con.execute("SELECT max(created_at) FROM messages WHERE bot_id=? AND user_id=? AND direction='admin_to_user'",(r['bot_id'],r['user_id'])).fetchone()[0]
                def stamp(s):
                    try:return datetime.strptime(s,'%Y-%m-%d %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Shanghai')).timestamp() if s else None
                    except ValueError:return None
                con.execute('INSERT OR IGNORE INTO client_cases(bot_id,user_id,last_inbound_at,last_outbound_at) VALUES(?,?,?,?)',(r['bot_id'],r['user_id'],stamp(inbound),stamp(outbound)))
            con.execute('INSERT INTO schema_migrations VALUES(2,?)',(time.time(),))
        con.commit()
    except BaseException:
        con.rollback()
        raise

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
