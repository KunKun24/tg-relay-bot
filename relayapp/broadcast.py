# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""SQLite durable per-bot recipient queues, without replaying uncertain sends."""
from __future__ import annotations

import asyncio
import json
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from .bots import get_bot, is_bot_admin
from .config import MAIN_ADMIN_ID
from .database import get_db, transaction
from .formatting import send_payload, api_call, api_cooldown
from .payments import require_capability


class _SendAborted(Exception):
    """No API call happened; a control or ownership change cancelled the claim."""


class BroadcastService:
    def __init__(self):
        self._tick_lock = asyncio.Lock()

    def _authorize(self, bot_id, actor_id):
        if int(bot_id) == 0:
            if int(actor_id) != MAIN_ADMIN_ID:
                raise PermissionError('仅平台管理员可操作主平台广播')
        elif not is_bot_admin(bot_id, actor_id):
            raise PermissionError('无权操作此机器人广播')

    def create_in_transaction(self, con, bot_id, actor_id, payload, progress_chat_id, progress_message_id=None):
        self._authorize(bot_id, actor_id)
        if bot_id:
            require_capability(bot_id, 'broadcast')
            bot = get_bot(bot_id)
            if bot['desired_state'] != 'RUNNING':
                raise ValueError('请先恢复机器人运行')
        if not isinstance(payload, dict) or not payload.get('type'):
            raise ValueError('广播内容无效')
        now = time.time()
        job_id = con.execute('INSERT INTO broadcast_jobs(bot_id,actor_id,payload,progress_chat_id,progress_message_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
            (bot_id,actor_id,json.dumps(payload,ensure_ascii=False),progress_chat_id,progress_message_id,now,now)).lastrowid
        if bot_id == 0:
            con.execute("INSERT INTO broadcast_recipients(job_id,user_id,updated_at) SELECT ?,user_id,? FROM main_users WHERE blocked=0",(job_id,now))
        else:
            con.execute("INSERT INTO broadcast_recipients(job_id,user_id,updated_at) SELECT ?,u.user_id,? FROM users u WHERE u.bot_id=? AND u.blocked_by_bot=0 AND NOT EXISTS(SELECT 1 FROM blacklist b WHERE b.bot_id=u.bot_id AND b.user_id=u.user_id AND (b.expires_at IS NULL OR b.expires_at>?))",(job_id,now,bot_id,now))
        con.execute('INSERT INTO audit_logs(bot_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)',(bot_id,actor_id,'CREATE_BROADCAST',json.dumps({'job_id':job_id}),now))
        return job_id

    def create(self, bot_id, actor_id, payload, progress_chat_id, progress_message_id=None):
        with transaction() as con:
            return self.create_in_transaction(con,bot_id,actor_id,payload,progress_chat_id,progress_message_id)

    def _job(self, job_id, actor_id):
        row = get_db().execute('SELECT * FROM broadcast_jobs WHERE id=?',(job_id,)).fetchone()
        if not row:
            raise ValueError('广播任务不存在')
        self._authorize(row['bot_id'],actor_id)
        return dict(row)

    def stats(self, job_id, actor_id):
        job = self._job(job_id,actor_id)
        counts = {status: 0 for status in ('PENDING','SENDING','RETRY','SENT','FAILED','UNKNOWN','SKIPPED','CANCELLED')}
        counts.update({r['status']:r['n'] for r in get_db().execute('SELECT status,count(*) n FROM broadcast_recipients WHERE job_id=? GROUP BY status',(job_id,))})
        total = sum(counts.values())
        done = counts['SENT']+counts['FAILED']+counts['SKIPPED']+counts['CANCELLED']
        filled = int(20*done/total) if total else 20
        return {'id':job_id,'bot_id':job['bot_id'],'status':job['status'],'total':total,'counts':counts,
                'progress':'█'*filled+'░'*(20-filled),'completed':done}

    def action(self, job_id, actor_id, action):
        job = self._job(job_id,actor_id)
        with transaction() as con:
            if action == 'pause':
                con.execute("UPDATE broadcast_jobs SET status='PAUSED',updated_at=? WHERE id=? AND status IN ('RUNNING','PENDING')",(time.time(),job_id))
            elif action == 'resume':
                if con.execute("SELECT 1 FROM broadcast_recipients WHERE job_id=? AND status='UNKNOWN'",(job_id,)).fetchone():
                    raise ValueError('请先明确处理UNKNOWN，重试可能重复送达')
                if job['bot_id'] and get_bot(job['bot_id'])['desired_state'] != 'RUNNING':
                    raise ValueError('机器人尚未恢复运行')
                con.execute("UPDATE broadcast_jobs SET status='RUNNING',updated_at=? WHERE id=? AND status='PAUSED'",(time.time(),job_id))
            elif action == 'cancel':
                con.execute("UPDATE broadcast_jobs SET status='CANCELLED',updated_at=? WHERE id=? AND status!='COMPLETED'",(time.time(),job_id))
                con.execute("UPDATE broadcast_recipients SET status='CANCELLED',updated_at=? WHERE job_id=? AND status IN ('PENDING','RETRY')",(time.time(),job_id))
            elif action in ('retry_unknown','skip_unknown'):
                if job['status'] == 'CANCELLED' and action == 'retry_unknown':
                    raise ValueError('已取消的任务不能重试，请创建新任务')
                status = 'PENDING' if action == 'retry_unknown' else 'SKIPPED'
                con.execute("UPDATE broadcast_recipients SET status=?,next_attempt=0,error=NULL,updated_at=? WHERE job_id=? AND status='UNKNOWN'",(status,time.time(),job_id))
                # Stay paused: resuming is an independent explicit operation.
            else:
                raise ValueError('广播操作无效')
            con.execute('INSERT INTO audit_logs(bot_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)',(job['bot_id'],actor_id,'BROADCAST_'+action.upper(),json.dumps({'job_id':job_id}),time.time()))

    def recover(self):
        with transaction() as con:
            affected = [r[0] for r in con.execute("SELECT DISTINCT job_id FROM broadcast_recipients WHERE status='SENDING'")]
            con.execute("UPDATE broadcast_recipients SET status='UNKNOWN',error='process_interrupted',updated_at=? WHERE status='SENDING'",(time.time(),))
            for job_id in affected:
                con.execute("UPDATE broadcast_jobs SET status='PAUSED',updated_at=? WHERE id=? AND status IN ('PENDING','RUNNING')",(time.time(),job_id))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


    async def tick(self, bot_lookup):
        if self._tick_lock.locked():
            return
        async with self._tick_lock:
            # Paused jobs have a separate progress lane and never consume send slots.
            rows = get_db().execute("""SELECT j.* FROM broadcast_jobs j WHERE j.status IN ('PENDING','RUNNING')
                AND (EXISTS(SELECT 1 FROM broadcast_recipients r WHERE r.job_id=j.id AND r.status IN ('PENDING','RETRY') AND r.next_attempt<=?)
                  OR NOT EXISTS(SELECT 1 FROM broadcast_recipients r WHERE r.job_id=j.id AND r.status IN ('PENDING','RETRY','SENDING')))
                ORDER BY j.updated_at,j.id LIMIT 32""",(time.time(),)).fetchall()
            await asyncio.gather(*(self._process(dict(row),bot_lookup) for row in rows))
            progress = get_db().execute("SELECT * FROM broadcast_jobs WHERE status IN ('PAUSED','COMPLETED','CANCELLED') AND progress_chat_id IS NOT NULL AND COALESCE(last_progress,0)<updated_at ORDER BY last_progress,id LIMIT 8").fetchall()
            for row in progress:
                bot=bot_lookup(row['bot_id'])
                if bot is not None:
                    await self._progress(row['id'],bot)

    async def _process(self, job, bot_lookup):
        bot = bot_lookup(job['bot_id'])
        if bot is None:
            return
        if job['status'] in ('PENDING','RUNNING'):
            try:
                self._authorize(job['bot_id'],job['actor_id'])
            except PermissionError:
                get_db().execute("UPDATE broadcast_jobs SET status='PAUSED',updated_at=? WHERE id=?",(time.time(),job['id']));get_db().commit()
                return
            with transaction() as con:
                current = con.execute('SELECT status FROM broadcast_jobs WHERE id=?',(job['id'],)).fetchone()
                if current['status'] not in ('PENDING','RUNNING'):
                    return
                rec = con.execute("SELECT * FROM broadcast_recipients WHERE job_id=? AND status IN ('PENDING','RETRY') AND next_attempt<=? ORDER BY user_id LIMIT 1",(job['id'],time.time())).fetchone()
                if rec:
                    con.execute("UPDATE broadcast_recipients SET status='SENDING',attempts=attempts+1,updated_at=? WHERE job_id=? AND user_id=?",(time.time(),job['id'],rec['user_id']))
                con.execute("UPDATE broadcast_jobs SET status='RUNNING',updated_at=? WHERE id=?",(time.time(),job['id']))
            if rec:
                await self._send(job,dict(rec),bot)
            with transaction() as con:
                pending = con.execute("SELECT 1 FROM broadcast_recipients WHERE job_id=? AND status IN ('PENDING','RETRY','SENDING')",(job['id'],)).fetchone()
                unknown = con.execute("SELECT 1 FROM broadcast_recipients WHERE job_id=? AND status='UNKNOWN'",(job['id'],)).fetchone()
                if not pending:
                    con.execute("UPDATE broadcast_jobs SET status=?,updated_at=? WHERE id=? AND status IN ('RUNNING','PENDING')",('PAUSED' if unknown else 'COMPLETED',time.time(),job['id']))
        await self._progress(job['id'],bot)

    async def _send(self, job, rec, bot):
        status, message_id, error, next_at = 'FAILED',None,None,0
        try:
            def before_send():
                current=get_db().execute('SELECT status FROM broadcast_jobs WHERE id=?',(job['id'],)).fetchone()
                try:
                    self._authorize(job['bot_id'],job['actor_id'])
                    clone=get_bot(job['bot_id']) if job['bot_id'] else None
                    if not current or current['status']!='RUNNING' or (clone and clone['desired_state']!='RUNNING'):
                        raise _SendAborted()
                except PermissionError:
                    raise _SendAborted() from None
            result = await send_payload(bot,rec['user_id'],json.loads(job['payload']),before_send=before_send)
            status,message_id = 'SENT',result['message_id']
        except _SendAborted:
            current=get_db().execute('SELECT status FROM broadcast_jobs WHERE id=?',(job['id'],)).fetchone()
            status='CANCELLED' if not current or current['status']=='CANCELLED' else 'PENDING'
            error='control_changed_before_send'
        except RetryAfter as exc:
            delay = exc.retry_after.total_seconds() if hasattr(exc.retry_after,'total_seconds') else float(exc.retry_after)
            await api_cooldown(bot.id,delay)
            if int(rec['attempts'])+1 < 5:
                status,next_at,error = 'RETRY',time.time()+delay+1,'RetryAfter'
            else:
                error='RetryAfter_exhausted'
        except (BadRequest,Forbidden,ValueError) as exc:
            error = type(exc).__name__
            if isinstance(exc,Forbidden):
                con=get_db()
                if job['bot_id']==0:
                    con.execute('UPDATE main_users SET blocked=1 WHERE user_id=?',(rec['user_id'],))
                else:
                    con.execute('UPDATE users SET blocked_by_bot=1 WHERE bot_id=? AND user_id=?',(job['bot_id'],rec['user_id']))
                con.commit()
        except NetworkError:
            status,error = 'UNKNOWN','NetworkError'
        except TelegramError as exc:
            error = type(exc).__name__
        except Exception as exc:
            # A programming error after entering the API path can also be uncertain.
            status,error = 'UNKNOWN',type(exc).__name__
        with transaction() as con:
            con.execute("UPDATE broadcast_recipients SET status=?,message_id=?,error=?,next_attempt=?,updated_at=? WHERE job_id=? AND user_id=? AND status='SENDING'",(status,message_id,error,next_at,time.time(),job['id'],rec['user_id']))
            if status == 'UNKNOWN':
                con.execute("UPDATE broadcast_jobs SET status='PAUSED',updated_at=? WHERE id=? AND status IN ('PENDING','RUNNING')",(time.time(),job['id']))

    async def _progress(self, job_id, bot):
        job = dict(get_db().execute('SELECT * FROM broadcast_jobs WHERE id=?',(job_id,)).fetchone())
        if not job['progress_chat_id'] or (job['last_progress'] or 0)>time.time()-5:
            return
        try:
            stat=self.stats(job_id,job['actor_id'])
        except PermissionError:
            return
        text=f"📣 广播 #{job_id} · {stat['status']}\n{stat['progress']}\n已处理 {stat['completed']}/{stat['total']}\n成功 {stat['counts']['SENT']} · 失败 {stat['counts']['FAILED']} · 未知 {stat['counts']['UNKNOWN']}"
        callback=f"main_job:{job_id}" if job['bot_id']==0 else f"broadcast:view:{job_id}"
        markup=InlineKeyboardMarkup([[InlineKeyboardButton('查看进度与控制',callback_data=callback)]])
        try:
            if job['progress_message_id']:
                await api_call(bot,job['progress_chat_id'],'edit_message_text',message_id=job['progress_message_id'],text=text,reply_markup=markup)
            else:
                sent=await api_call(bot,job['progress_chat_id'],'send_message',text=text,reply_markup=markup)
                get_db().execute('UPDATE broadcast_jobs SET progress_message_id=? WHERE id=?',(sent.message_id,job_id));get_db().commit()
        except TelegramError:
            pass
        finally:
            get_db().execute('UPDATE broadcast_jobs SET last_progress=? WHERE id=?',(time.time(),job_id));get_db().commit()


broadcasts = BroadcastService()

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
