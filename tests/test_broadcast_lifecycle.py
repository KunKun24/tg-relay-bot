# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Durable broadcast/lifecycle tests using synthetic SQLite and local fakes only."""
import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'

import asyncio
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter

from relayapp import bots, broadcast, clients, database, formatting, lifecycle


@pytest.fixture
def db(tmp_path):
    previous = database._db_path
    database.init_db(tmp_path / 'broadcast.sqlite3')
    try:
        yield database.get_db()
    finally:
        database.configure_database(previous)


@pytest.fixture
def bot_id(db):
    row_id = db.execute("INSERT INTO bots(owner_id,bot_name,telegram_bot_id,version,expire_time,desired_state) VALUES(101,'Synthetic',900001,'高级版','永久','RUNNING')").lastrowid
    db.commit()
    bots.ensure_owner_admin(row_id, 101)
    return row_id


@pytest.fixture
def service(monkeypatch):
    async def no_cooldown(*args):
        pass
    monkeypatch.setattr(broadcast, 'api_cooldown', no_cooldown)
    return broadcast.BroadcastService()


def add_recipient(bot_id, user_id=301):
    clients.add_user(bot_id, user_id, 'synthetic', 'Synthetic')


def create_job(service, bot_id):
    return service.create(bot_id, 101, {'type': 'text', 'text': 'synthetic'}, 0)


def job_row(db, job_id):
    return dict(db.execute('SELECT * FROM broadcast_jobs WHERE id=?', (job_id,)).fetchone())


def recipient(db, job_id):
    return dict(db.execute('SELECT * FROM broadcast_recipients WHERE job_id=?', (job_id,)).fetchone())


def lookup(bot_id):
    return SimpleNamespace(id=900001)


def test_broadcast_recipients_scoped_and_blocked_excluded(db, bot_id, service):
    for user_id in (301, 302, 303, 304):
        add_recipient(bot_id, user_id)
    add_recipient(bot_id + 1, 999)
    clients.block_user(bot_id, 302)
    clients.block_user(bot_id, 303, duration_seconds=10)
    db.execute('UPDATE users SET blocked_by_bot=1 WHERE bot_id=? AND user_id=304', (bot_id,))
    db.commit()
    job = create_job(service, bot_id)
    assert [r[0] for r in db.execute('SELECT user_id FROM broadcast_recipients WHERE job_id=?', (job,))] == [301]
    for action in ('pause', 'cancel', 'retry_unknown'):
        with pytest.raises(PermissionError):
            service.action(job, 999, action)
    with pytest.raises(PermissionError):
        service.stats(job, 999)
    with pytest.raises(PermissionError):
        service.create(bot_id, 999, {'type': 'text'}, 0)
    with pytest.raises(PermissionError):
        service.create(0, -999, {'type': 'text'}, 0)


@pytest.mark.asyncio
async def test_recover_sending_unknown_no_automatic_replay(db, bot_id, service, monkeypatch):
    add_recipient(bot_id)
    job = create_job(service, bot_id)
    db.execute("UPDATE broadcast_recipients SET status='SENDING' WHERE job_id=?", (job,))
    db.commit()
    service.recover()
    service.recover()
    assert recipient(db, job)['status'] == 'UNKNOWN'
    assert job_row(db, job)['status'] == 'PAUSED'
    calls = []
    async def send(*args, **kwargs):
        calls.append(args)
        return {'message_id': 77}
    monkeypatch.setattr(broadcast, 'send_payload', send)
    await service.tick(lookup)
    assert calls == []
    with pytest.raises(ValueError, match='UNKNOWN'):
        service.action(job, 101, 'resume')
    service.action(job, 101, 'retry_unknown')
    assert job_row(db, job)['status'] == 'PAUSED'
    await service.tick(lookup)
    assert calls == []
    service.action(job, 101, 'resume')
    await service.tick(lookup)
    assert len(calls) == 1
    assert recipient(db, job)['status'] == 'SENT'
    assert job_row(db, job)['status'] == 'COMPLETED'
    await service.tick(lookup)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('error,status,job_status,blocked', [
    (BadRequest('invalid content'), 'FAILED', 'COMPLETED', 0),
    (Forbidden('blocked'), 'FAILED', 'COMPLETED', 1),
    (NetworkError('uncertain'), 'UNKNOWN', 'PAUSED', 0),
])
async def test_broadcast_error_classification(db, bot_id, service, monkeypatch, error, status, job_status, blocked):
    add_recipient(bot_id)
    job = create_job(service, bot_id)
    calls = []
    async def send(*args, **kwargs):
        calls.append(args)
        raise error
    monkeypatch.setattr(broadcast, 'send_payload', send)
    await service.tick(lookup)
    assert recipient(db, job)['status'] == status
    assert recipient(db, job)['attempts'] == 1
    assert job_row(db, job)['status'] == job_status
    assert clients.get_user(bot_id, 301)['blocked_by_bot'] == blocked
    await service.tick(lookup)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retry_after_eventually_stops_automatic_retries(db, bot_id, service, monkeypatch):
    add_recipient(bot_id)
    job = create_job(service, bot_id)
    calls = []
    async def send(*args, **kwargs):
        calls.append(args)
        raise RetryAfter(1)
    monkeypatch.setattr(broadcast, 'send_payload', send)
    for _ in range(12):
        db.execute('UPDATE broadcast_recipients SET next_attempt=0 WHERE job_id=?', (job,))
        db.commit()
        await service.tick(lookup)
    assert len(calls) < 12
    assert recipient(db, job)['status'] not in ('PENDING', 'RETRY', 'SENDING')


@pytest.mark.asyncio
async def test_many_old_paused_jobs_cannot_starve_active_job(db, bot_id, service, monkeypatch):
    add_recipient(bot_id)
    for _ in range(32):
        paused = create_job(service, bot_id)
        service.action(paused, 101, 'pause')
        db.execute('UPDATE broadcast_jobs SET updated_at=0 WHERE id=?', (paused,))
        db.commit()
    active = create_job(service, bot_id)
    calls = []
    async def send(*args, **kwargs):
        calls.append(args)
        return {'message_id': 77}
    monkeypatch.setattr(broadcast, 'send_payload', send)
    await service.tick(lookup)
    assert len(calls) == 1
    assert recipient(db, active)['status'] == 'SENT'


@pytest.mark.asyncio
@pytest.mark.parametrize('control', ['pause', 'cancel', 'transfer', 'disconnect'])
async def test_control_change_during_throttle_prevents_send(db, bot_id, service, monkeypatch, control):
    add_recipient(bot_id)
    job = create_job(service, bot_id)
    calls = []
    class LocalBot:
        id = 900001
        async def send_message(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(message_id=77)
    async def change_during_wait(*args, **kwargs):
        if control in ('pause', 'cancel'):
            service.action(job, 101, control)
        elif control == 'transfer':
            bots.touch_main_user(201, 'synthetic_target', 'Target')
            nonce = bots.request_transfer(bot_id, 101, 201)
            bots.accept_transfer(nonce, 201)
        else:
            runtime = FakeRuntime()
            await runtime._disconnect_clone_bot(bot_id, 101)
    monkeypatch.setattr(formatting, 'api_throttle', change_during_wait)
    monkeypatch.setattr(broadcast, 'send_payload', formatting.send_payload)
    await service.tick(lambda _: LocalBot())
    assert calls == []
    assert recipient(db, job)['status'] == ('CANCELLED' if control == 'cancel' else 'PENDING')
    assert recipient(db, job)['error'] == 'control_changed_before_send'


def test_cancel_unknown_needs_explicit_skip_and_cannot_retry(db, bot_id, service):
    add_recipient(bot_id)
    job = create_job(service, bot_id)
    db.execute("UPDATE broadcast_recipients SET status='UNKNOWN' WHERE job_id=?", (job,))
    db.commit()
    service.action(job, 101, 'cancel')
    with pytest.raises(ValueError):
        service.action(job, 101, 'retry_unknown')
    service.action(job, 101, 'skip_unknown')
    assert recipient(db, job)['status'] == 'SKIPPED'
    assert job_row(db, job)['status'] == 'CANCELLED'


class FakeUpdater:
    def __init__(self, events, stop_error=False):
        self.running = False
        self.events = events
        self.stop_error = stop_error

    async def start_polling(self, **kwargs):
        self.events.append('polling')
        self.running = True

    async def stop(self):
        self.events.append('polling_stop')
        if self.stop_error:
            raise RuntimeError('synthetic stop failure')
        self.running = False


class FakeApp:
    def __init__(self, telegram_id=900001, stop_error=False):
        self.events = []
        self.bot = SimpleNamespace(id=telegram_id)
        self.updater = FakeUpdater(self.events, stop_error)
        self.running = False

    async def initialize(self):
        self.events.append('initialize')

    async def start(self):
        self.events.append('start')
        self.running = True

    async def stop(self):
        self.events.append('stop')
        self.running = False

    async def shutdown(self):
        self.events.append('shutdown')


class FakeRuntime(lifecycle.LifecycleMixin):
    def __init__(self):
        self.clone_runners = {}
        self._runner_locks = {}
        self.apps = []
        self.next_id = 900001
        self.stop_error = False

    def _build_clone(self, row):
        app = FakeApp(self.next_id, self.stop_error)
        self.apps.append(app)
        return {'app': app, 'handler': None, 'generation': row['generation']}


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

def fake_probe(monkeypatch, identity_id):
    class Probe:
        def __init__(self, token):
            self.token = token
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get_me(self):
            return SimpleNamespace(id=identity_id, username='synthetic_bot', first_name='Synthetic')
    monkeypatch.setattr(lifecycle, 'Bot', Probe)


@pytest.mark.asyncio
async def test_lifecycle_same_id_rotation_preserves_business_rows(db, bot_id, monkeypatch):
    add_recipient(bot_id)
    runtime = FakeRuntime()
    await runtime._start_clone_bot(bot_id, 101)
    old = runtime.clone_runners[bot_id]['app']
    fake_probe(monkeypatch, 900001)
    await runtime._rotate_clone_token(bot_id, 'SYNTHETIC-ONLY-REPLACEMENT', 101)
    assert old.events == ['initialize', 'start', 'polling', 'polling_stop', 'stop', 'shutdown']
    assert len(runtime.apps) == 2
    assert clients.get_user(bot_id, 301) is not None
    assert bots.get_bot(bot_id)['telegram_bot_id'] == 900001
    assert bots.get_bot(bot_id)['bot_token'] == 'SYNTHETIC-ONLY-REPLACEMENT'
    assert bots.get_bot(bot_id)['actual_state'] == 'RUNNING'


@pytest.mark.asyncio
async def test_wrong_identity_rotation_does_not_stop_running_app(db, bot_id, monkeypatch):
    runtime = FakeRuntime()
    await runtime._start_clone_bot(bot_id, 101)
    old = runtime.clone_runners[bot_id]['app']
    fake_probe(monkeypatch, 900002)
    with pytest.raises(ValueError):
        await runtime._rotate_clone_token(bot_id, 'SYNTHETIC-WRONG-IDENTITY', 101)
    assert runtime.clone_runners[bot_id]['app'] is old
    assert old.events == ['initialize', 'start', 'polling']
    assert len(runtime.apps) == 1


@pytest.mark.asyncio
async def test_delete_tombstone_survives_and_blocks_reconnect(db, bot_id, service):
    add_recipient(bot_id)
    clients.set_conversation(bot_id, 101, 301)
    db.execute("INSERT INTO ui_sessions(bot_id,user_id,state,data) VALUES(?,101,'draft','{}')", (bot_id,))
    db.commit()
    job = create_job(service, bot_id)
    runtime = FakeRuntime()
    await runtime._start_clone_bot(bot_id, 101)
    await runtime._delete_clone_bot(bot_id, 101)
    row = bots.get_bot(bot_id)
    assert row['desired_state'] == 'DELETED' and row['deleted_at'] is not None
    assert row['actual_state'] == 'STOPPED'
    assert bot_id not in runtime.clone_runners
    assert clients.get_user(bot_id, 301) is not None
    assert clients.get_conversation(bot_id, 101) is None
    assert db.execute('SELECT count(*) FROM ui_sessions').fetchone()[0] == 0
    assert job_row(db, job)['status'] == 'CANCELLED'
    for operation in (runtime._reconnect_clone_bot, runtime._start_clone_bot):
        with pytest.raises(ValueError):
            await operation(bot_id, 101)


@pytest.mark.asyncio
async def test_stop_failure_keeps_runner_and_does_not_build_duplicate(db, bot_id):
    runtime = FakeRuntime()
    runtime.stop_error = True
    await runtime._start_clone_bot(bot_id, 101)
    old = runtime.clone_runners[bot_id]
    with pytest.raises(RuntimeError, match='synthetic stop failure'):
        await runtime._restart_clone_bot(bot_id, 101)
    assert runtime.clone_runners[bot_id] is old
    assert len(runtime.apps) == 1
    assert bots.get_bot(bot_id)['actual_state'] == 'ERROR'
    assert bots.get_bot(bot_id)['last_error'] == 'RuntimeError'


@pytest.mark.asyncio
async def test_token_rotation_stop_failure_preserves_token(db, bot_id, monkeypatch):
    runtime = FakeRuntime()
    runtime.stop_error = True
    await runtime._start_clone_bot(bot_id, 101)
    before = bots.get_bot(bot_id)['bot_token']
    fake_probe(monkeypatch, 900001)
    with pytest.raises(RuntimeError):
        await runtime._rotate_clone_token(bot_id, 'SYNTHETIC-ONLY-REPLACEMENT', 101)
    assert bots.get_bot(bot_id)['bot_token'] == before
    assert len(runtime.apps) == 1


@pytest.mark.asyncio
async def test_partial_start_failure_keeps_runner_when_cleanup_fails(db, bot_id):
    class BrokenRuntime(FakeRuntime):
        def _build_clone(self, row):
            runner = super()._build_clone(row)
            async def start_then_fail(**kwargs):
                runner['app'].updater.running = True
                raise NetworkError('synthetic polling failure')
            runner['app'].updater.start_polling = start_then_fail
            runner['app'].updater.stop_error = True
            return runner
    runtime = BrokenRuntime()
    with pytest.raises(NetworkError):
        await runtime._start_clone_bot(bot_id, 101)
    assert runtime.apps[0].running
    # Running app whose cleanup failed must remain discoverable for a later stop.
    assert bot_id in runtime.clone_runners
    with pytest.raises(Exception):
        await runtime._restart_clone_bot(bot_id, 101)
    assert len(runtime.apps) == 1


@pytest.mark.asyncio
async def test_lifecycle_lock_serializes_reconnect(db, bot_id):
    runtime = FakeRuntime()
    await asyncio.gather(*(runtime._reconnect_clone_bot(bot_id, 101) for _ in range(6)))
    assert len(runtime.apps) == 1
    assert bots.get_bot(bot_id)['actual_state'] == 'RUNNING'
    with pytest.raises(PermissionError):
        await runtime._disconnect_clone_bot(bot_id, 999)
    assert bot_id in runtime.clone_runners


def retry_candidate(db, *, error='NetworkError', desired='RUNNING', actual='ERROR', deleted_at=None):
    telegram_id = db.execute('SELECT COALESCE(MAX(telegram_bot_id),900000)+1 FROM bots').fetchone()[0]
    row_id = db.execute(
        "INSERT INTO bots(owner_id,bot_name,telegram_bot_id,desired_state,actual_state,last_error,deleted_at) VALUES(101,'Synthetic retry',?,?,?,?,?)",
        (telegram_id, desired, actual, error, deleted_at),
    ).lastrowid
    db.commit()
    return row_id


class RetryRuntime(FakeRuntime):
    def _build_clone(self, row):
        runner = super()._build_clone(row)
        runner['app'].bot.id = row['telegram_bot_id']
        return runner


@pytest.mark.asyncio
async def test_retry_clones_only_transient_errors_with_running_desire(db):
    runtime = RetryRuntime()
    eligible = {retry_candidate(db, error=error) for error in ('TimedOut', 'NetworkError', 'RetryAfter')}
    excluded = {
        retry_candidate(db, error='InvalidToken'),
        retry_candidate(db, error='BadRequest'),
        retry_candidate(db, error='RuntimeError'),
        retry_candidate(db, desired='DISCONNECTED'),
        retry_candidate(db, desired='STOPPED'),
        retry_candidate(db, desired='DELETED', deleted_at=1),
        retry_candidate(db, deleted_at=1),
        retry_candidate(db, actual='STOPPED'),
        retry_candidate(db, actual='RUNNING'),
    }
    await runtime.retry_failed_clones()
    assert set(runtime.clone_runners) == eligible
    assert len(runtime.apps) == 3
    assert all(bots.get_bot(row_id)['actual_state'] == 'RUNNING' for row_id in eligible)
    assert not (excluded & set(runtime.clone_runners))


@pytest.mark.asyncio
async def test_retry_clones_concurrency_is_two_and_failure_does_not_block_others(db):
    row_ids = [retry_candidate(db) for _ in range(5)]
    active = 0
    peak = 0
    called = []
    paired = asyncio.Event()

    class ObservedRuntime(RetryRuntime):
        async def _start_locked(self, row_id):
            nonlocal active, peak
            called.append(row_id)
            active += 1
            peak = max(peak, active)
            if active == 2:
                paired.set()
            try:
                if not paired.is_set():
                    await asyncio.wait_for(paired.wait(), timeout=1)
                if row_id == row_ids[0]:
                    raise NetworkError('synthetic retry failure')
                return await super()._start_locked(row_id)
            finally:
                active -= 1

    runtime = ObservedRuntime()
    await runtime.retry_failed_clones()
    assert peak == 2
    assert set(called) == set(row_ids)
    assert set(runtime.clone_runners) == set(row_ids[1:])
    assert bots.get_bot(row_ids[0])['actual_state'] == 'ERROR'


@pytest.mark.asyncio
@pytest.mark.parametrize('changed_field,changed_value', [
    ('desired_state', 'DISCONNECTED'),
    ('desired_state', 'DELETED'),
    ('actual_state', 'RUNNING'),
    ('last_error', 'InvalidToken'),
    ('deleted_at', 1),
])
async def test_retry_clones_revalidates_after_waiting_for_bot_lock(db, changed_field, changed_value):
    row_id = retry_candidate(db)
    runtime = FakeRuntime()
    lock = runtime._lock_for(row_id)
    original_lock_for = runtime._lock_for
    reached_lock = asyncio.Event()

    def observed_lock_for(candidate):
        if candidate == row_id:
            reached_lock.set()
        return original_lock_for(candidate)

    runtime._lock_for = observed_lock_for
    await lock.acquire()
    task = asyncio.create_task(runtime.retry_failed_clones())
    try:
        await asyncio.wait_for(reached_lock.wait(), timeout=1)
        with database.transaction() as con:
            con.execute('UPDATE bots SET ' + changed_field + '=? WHERE id=?', (changed_value, row_id))
    finally:
        lock.release()
        await task
    assert runtime.apps == []
    assert runtime.clone_runners == {}
    assert bots.get_bot(row_id)[changed_field] == changed_value


@pytest.mark.asyncio
async def test_retry_clones_concurrent_sweeps_do_not_rebuild_running_clone(db):
    row_id = retry_candidate(db)
    runtime = FakeRuntime()
    await asyncio.gather(*(runtime.retry_failed_clones() for _ in range(4)))
    assert set(runtime.clone_runners) == {row_id}
    assert len(runtime.apps) == 1
    await runtime.retry_failed_clones()
    assert len(runtime.apps) == 1


@pytest.mark.asyncio
async def test_retry_clones_backoff_caps_and_clears_after_success(db, monkeypatch):
    row_id = retry_candidate(db)
    now = [1000.0]
    monkeypatch.setattr(lifecycle.time, 'monotonic', lambda: now[0])
    fail = [True]
    calls = []

    class FailingRuntime(RetryRuntime):
        async def _start_locked(self, candidate):
            calls.append(candidate)
            if fail[0]:
                raise NetworkError('synthetic transient failure')
            return await super()._start_locked(candidate)

    runtime = FailingRuntime()
    for number, delay in enumerate((30, 60, 120, 240, 480, 900, 900), start=1):
        await runtime.retry_failed_clones()
        assert len(calls) == number
        deadline = runtime._clone_retry_after[row_id]
        assert deadline == now[0] + delay
        now[0] = deadline - 0.01
        await runtime.retry_failed_clones()
        assert len(calls) == number
        now[0] = deadline
    fail[0] = False
    await runtime.retry_failed_clones()
    assert len(calls) == 8
    assert bots.get_bot(row_id)['actual_state'] == 'RUNNING'
    assert row_id not in runtime._clone_retry_attempts
    assert row_id not in runtime._clone_retry_after

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
