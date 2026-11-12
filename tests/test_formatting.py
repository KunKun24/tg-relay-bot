# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

import asyncio
from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace

import pytest
from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message, MessageEntity, User
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from relayapp import formatting as f


class FakeBot:
    id = 654321

    def __init__(self, failures=()):
        self.calls = []
        self.failures = list(failures)

    def __getattr__(self, method):
        if not method.startswith('send_'):
            raise AttributeError(method)

        async def send(**kwargs):
            self.calls.append((method, kwargs))
            if self.failures:
                failure = self.failures.pop(0)
                if failure is not None:
                    raise failure
            return SimpleNamespace(message_id=77)
        return send


@pytest.fixture
def no_throttle(monkeypatch):
    events = []

    async def throttle(bot_id, chat_id, group=False):
        events.append((bot_id, chat_id, group))

    async def cooldown(bot_id, seconds):
        events.append(('cooldown', bot_id, seconds))

    monkeypatch.setattr(f, 'api_throttle', throttle)
    monkeypatch.setattr(f, 'api_cooldown', cooldown)
    return events


def msg(**kwargs):
    defaults = dict(text=None, caption=None, entities=(), caption_entities=())
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def entity(kind='bold', offset=0, length=1, **kwargs):
    return dict(type=kind, offset=offset, length=length, **kwargs)


def test_native_entities_utf16_and_json():
    text = '😀bold & <safe>'
    entities = [entity('bold', 2, 4), entity('custom_emoji', 0, 2, custom_emoji_id='12345678901234567890')]
    captured = f.capture_payload(msg(text=text, entities=entities, has_protected_content=True))
    assert captured['text'] == text
    assert captured['entities'] == entities
    assert captured['protect_content'] is True
    assert json.loads(json.dumps(captured)) == captured


@pytest.mark.parametrize('offset,length', [(-1, 1), (1, 1), (0, 1), (2, 0), (2, 9), (True, 2), (0, -1), (0.0, 2)])
def test_invalid_utf16_boundaries(offset, length):
    with pytest.raises(ValueError):
        f.capture_payload(msg(text='😀x', entities=[entity(offset=offset, length=length)]))


@pytest.mark.parametrize('entities', [
    [entity('bold', 0, 3), entity('italic', 2, 2)],
    [entity('pre', 0, 4), entity('bold', 1, 1)],
    [entity('unknown', 0, 1)],
    [entity('custom_emoji', 0, 1, custom_emoji_id='bad')],
    [entity('text_link', 0, 1)],
    [entity('text_mention', 0, 1)],
    [entity('text_link', 0, 4, url='https://example.org'), entity('text_link', 1, 1, url='https://example.com')],
    [entity('blockquote', 0, 4), entity('expandable_blockquote', 1, 1)],
])
def test_entity_schema_rejects_bad_ranges_or_metadata(entities):
    with pytest.raises(ValueError):
        f.capture_payload(msg(text='abcd', entities=entities))


def test_nested_and_adjacent_entities_preserved():
    entities = [entity('bold', 0, 4), entity('italic', 1, 2), entity('code', 4, 1)]
    assert f.capture_payload(msg(text='abcde', entities=entities))['entities'] == entities


def test_html_uses_ptb_escaping_and_caption_styles():
    message = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(1, 'private'),
                      text='<i>A & B</i> 😀', entities=[MessageEntity('bold', 0, 3),
                          MessageEntity('custom_emoji', 13, 2, custom_emoji_id='123')])
    result = f.extract_emoji_from_text_html(message)
    assert '&lt;i&gt;' in result and '&amp;' in result and '<b>' in result
    assert '<tg-emoji emoji-id="123">' in result
    caption = msg(caption='<safe>', caption_html='<i>&lt;safe&gt;</i>')
    assert f.extract_emoji_from_text_html(caption) == '<i>&lt;safe&gt;</i>'
    assert f.extract_emoji_from_text_html(msg(text='<b>plain</b>')) == '&lt;b&gt;plain&lt;/b&gt;'
    assert f.render_emoji_html('<b>&amp;</b>[emoji:123]') == '<b>&amp;</b><tg-emoji emoji-id="123">⭐</tg-emoji>'


def test_buttons_styles_icons_utf16_and_rows():
    text = '😀 First #p | https://example.org && Second #g - tg://user?id=42\nThird #r|http://example.com'
    buttons = f.parse_inline_buttons(text, [entity('custom_emoji', 0, 2, custom_emoji_id='999999999999999999')])
    assert len(buttons) == 2 and len(buttons[0]) == 2
    assert buttons[0][0] == dict(text='First', url='https://example.org', style='primary', icon_custom_emoji_id='999999999999999999')
    markup = f.build_inline_markup(buttons).to_dict()['inline_keyboard']
    assert markup[0][0]['icon_custom_emoji_id'] == '999999999999999999'
    assert markup[0][1]['style'] == 'success' and markup[1][0]['style'] == 'danger'


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:text/html,hi', 'file:///etc/passwd',
    'https:///nohost', 'https://user:pass@example.com', 'http://example.com:bad',
    'https://exa\\mple.org', 'https://example.org\x00x', 'tg:/user?id=1', 'https://a b',
    'https://bad%20host.org', 'https://-bad.org', 'https://bad..org'])
def test_buttons_reject_unsafe_urls(url):
    with pytest.raises(ValueError):
        f.parse_inline_buttons('Open|' + url)
    with pytest.raises(ValueError):
        f.build_inline_markup([[{'text': 'Open', 'url': url}]])


def test_button_count_limits():
    with pytest.raises(ValueError):
        f.parse_inline_buttons(' && '.join(['x|https://x.org'] * 11))
    with pytest.raises(ValueError):
        f.parse_inline_buttons('\n'.join(['x|https://x.org'] * 101))
    assert len(f.parse_inline_buttons('\n'.join(['x|https://x.org'] * 100))) == 100


def test_reply_keyboard_json_and_string_ids(monkeypatch):
    values = {'reply_kb_enabled': '1', 'reply_kb_per_row': '2', 'reply_kb_buttons': json.dumps([
        {'text': 'One', 'color': 'success', 'emoji_id': '11111111111111111'}, {'text': 'Two', 'style': 'danger'}])}
    monkeypatch.setattr(f, 'get_setting', lambda bot_id, key, default='': values.get(key, default))
    data = f.build_reply_keyboard(3).to_dict()
    assert data['keyboard'][0][0]['icon_custom_emoji_id'] == '11111111111111111'
    assert data['keyboard'][0][0]['style'] == 'success'
    assert data['keyboard'][0][1]['style'] == 'danger'
    values['reply_kb_enabled'] = '0'
    assert f.build_reply_keyboard(3) is None


def test_user_names_and_id_links_are_html_safe():
    assert f.user_display(User(1, '<b>&"', False)) == '&lt;b&gt;&amp;&quot;'
    assert f.user_display({'user_id': 1, 'first_name': '<x>', 'last_name': '&y'}) == '&lt;x&gt; &amp;y'
    assert f.user_id_link('12') == '<a href="tg://user?id=12">12</a>'
    with pytest.raises(ValueError):
        f.user_id_link('1"><script>')
    username = f.gen_bot_username()
    assert username.endswith('_bot') and username.isascii() and len(username) <= 32


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['text', 'photo', 'video', 'animation', 'document', 'voice', 'audio', 'sticker', 'video_note', 'contact', 'location'])
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

async def test_capture_and_send_all_media(kind, no_throttle):
    kwargs = dict(text='😀text', entities=[entity('bold', 2, 4)]) if kind == 'text' else dict(
        caption='😀text', caption_entities=[entity('bold', 2, 4)])
    if kind in f._MEDIA:
        media = SimpleNamespace(file_id='file-' + kind)
        kwargs[kind] = [SimpleNamespace(file_id='small'), media] if kind == 'photo' else media
    elif kind == 'contact':
        kwargs['contact'] = SimpleNamespace(phone_number='123', first_name='Name', last_name='Last', vcard='vcard')
    elif kind == 'location':
        kwargs['location'] = SimpleNamespace(latitude=1.5, longitude=2.5, horizontal_accuracy=3)
    kwargs['reply_markup'] = InlineKeyboardMarkup([[InlineKeyboardButton('Open', url='https://example.com', style='primary', icon_custom_emoji_id='77')]])
    captured = f.capture_payload(msg(**kwargs))
    bot = FakeBot()
    result = await f.send_payload(bot, -33, captured)
    assert result == {'message_id': 77, 'degraded': False}
    method, sent = bot.calls[0]
    assert method == ('send_message' if kind == 'text' else 'send_' + kind)
    if kind == 'text' or kind in f._CAPTION_MEDIA:
        key = 'entities' if kind == 'text' else 'caption_entities'
        assert sent[key][0].offset == 2
        assert sent['parse_mode'] is None
    if kind in f._MEDIA:
        assert sent[kind] == 'file-' + kind
    assert no_throttle == [(bot.id, -33, True)]
    assert sent['reply_markup'].inline_keyboard[0][0].style == 'primary'


@pytest.mark.asyncio
async def test_legacy_html_is_separate(no_throttle):
    bot = FakeBot()
    await f.send_payload(bot, 1, {'content_type': 'text', 'content_text': '<b>&amp;</b>[emoji:12]'})
    sent = bot.calls[0][1]
    assert sent['parse_mode'] == 'HTML' and 'entities' not in sent
    assert sent['text'] == '<b>&amp;</b><tg-emoji emoji-id="12">⭐</tg-emoji>'
    with pytest.raises(ValueError):
        await f.send_payload(bot, 1, {'text': 'abc', 'legacy_html': True, 'entities': [entity()]})


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [BadRequest('chat not found'), BadRequest('CUSTOM_EMOJI_INVALID'),
    BadRequest("Can't parse entities"), BadRequest('PREMIUM_ACCOUNT_REQUIRED'),
    TimedOut(), NetworkError('Connection lost')])
async def test_unrelated_errors_and_uncertain_results_never_retry(failure, no_throttle):
    bot = FakeBot([failure])
    with pytest.raises(type(failure)):
        await f.send_payload(bot, 1, {'text': '😀', 'entities': [entity('custom_emoji', 0, 2, custom_emoji_id='12')]})
    assert len(bot.calls) == 1


@pytest.mark.asyncio
async def test_emoji_permission_downgrade_preserves_text_styles_and_button_colors(no_throttle):
    payload = {'text': '😀text', 'entities': [entity('custom_emoji', 0, 2, custom_emoji_id='123'), entity('bold', 2, 4)],
               'buttons': [[dict(text='Button', url='https://example.org', style='success', icon_custom_emoji_id='456')]]}
    bot = FakeBot([BadRequest('Custom emoji entities are not allowed for this bot')])
    result = await f.send_payload(bot, 1, payload)
    assert result['degraded'] is True and len(bot.calls) == 2
    sent = bot.calls[1][1]
    assert sent['text'] == '😀text'
    assert [e.to_dict() for e in sent['entities']] == [entity('bold', 2, 4)]
    button = sent['reply_markup'].to_dict()['inline_keyboard'][0][0]
    assert button['style'] == 'success' and 'icon_custom_emoji_id' not in button
    assert payload['entities'][0]['type'] == 'custom_emoji' and payload['buttons'][0][0]['icon_custom_emoji_id'] == '456'


@pytest.mark.asyncio
async def test_emoji_downgrade_only_once_and_no_downgrade_without_emoji(no_throttle):
    bot = FakeBot([BadRequest('Custom emoji entities are not allowed'), BadRequest('Custom emoji entities are not allowed')])
    with pytest.raises(BadRequest):
        await f.send_payload(bot, 1, {'text': 'x', 'entities': [entity('custom_emoji', custom_emoji_id='1')]})
    assert len(bot.calls) == 2
    bot = FakeBot([BadRequest('Custom emoji entities are not allowed')])
    with pytest.raises(BadRequest):
        await f.send_payload(bot, 1, {'text': 'x'})
    assert len(bot.calls) == 1


@pytest.mark.asyncio
async def test_retryafter_retries_once_but_timeout_after_rejection_does_not(no_throttle):
    bot = FakeBot([RetryAfter(1), RetryAfter(2)])
    with pytest.raises(RetryAfter):
        await f.send_payload(bot, 1, {'text': 'x'})
    assert len(bot.calls) == 2
    assert len([x for x in no_throttle if x[0] == 'cooldown']) == 2
    bot = FakeBot([RetryAfter(timedelta(seconds=1)), TimedOut()])
    with pytest.raises(TimedOut):
        await f.send_payload(bot, 1, {'text': 'x'})
    assert len(bot.calls) == 2


@pytest.mark.asyncio
async def test_retry_budget_shared_with_emoji_degradation(no_throttle):
    bot = FakeBot([RetryAfter(1), BadRequest('Custom emoji entities are not allowed'), RetryAfter(1)])
    with pytest.raises(RetryAfter):
        await f.send_payload(bot, 1, {'text': 'x', 'entities': [entity('custom_emoji', custom_emoji_id='1')]})
    assert len(bot.calls) == 3


@pytest.mark.asyncio
async def test_legacy_emoji_degradation_keeps_html(no_throttle):
    bot = FakeBot([BadRequest('Custom emoji entities are not allowed')])
    result = await f.send_payload(bot, 1, {'content_text': '<b>&lt;safe&gt;</b>[emoji:123]'})
    assert result['degraded'] is True
    assert bot.calls[1][1]['text'] == '<b>&lt;safe&gt;</b>⭐'
    assert bot.calls[1][1]['parse_mode'] == 'HTML'


@pytest.mark.parametrize('label', ['#pOpen', 'Open#p', 'Open #p'])
def test_button_color_markers_attached_or_spaced(label):
    assert f.parse_inline_buttons(label + '|https://example.org')[0][0]['style'] == 'primary'


@pytest.mark.asyncio
async def test_api_call_supports_bound_callable(no_throttle):
    bot = FakeBot()
    result = await f.api_call(bot, 1, bot.send_message, text='safe')
    assert result.message_id == 77 and bot.calls[0][1]['chat_id'] == 1


def test_animation_preferred_over_document_and_mentions_preserved():
    captured = f.capture_payload(msg(caption='x', animation=SimpleNamespace(file_id='anim'), document=SimpleNamespace(file_id='doc')))
    assert captured['type'] == 'animation' and captured['file_id'] == 'anim'
    mention = MessageEntity('text_mention', 0, 1, user=User(1, 'Name', False))
    captured = f.capture_payload(msg(text='x', entities=[mention]))
    assert captured['entities'][0]['user']['id'] == 1


@pytest.mark.asyncio
async def test_throttle_different_chat_does_not_wait_for_group(monkeypatch):
    f._rate_states.clear()
    now = [100.0]
    sleep_started, release = asyncio.Event(), asyncio.Event()
    waits = []

    async def fake_sleep(delay):
        waits.append(delay)
        sleep_started.set()
        await release.wait()
        now[0] += delay

    monkeypatch.setattr(f.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(f.asyncio, 'sleep', fake_sleep)
    await f.api_throttle(1, -1, group=True)
    blocked = asyncio.create_task(f.api_throttle(1, -1, group=True))
    await sleep_started.wait()
    await f.api_throttle(1, 2)
    assert not blocked.done() and waits == pytest.approx([3.1])
    release.set()
    await blocked
    assert f._rate_states[1].chats[2] == pytest.approx(101.05)


@pytest.mark.asyncio
async def test_global_20_per_second_and_private_spacing(monkeypatch):
    f._rate_states.clear()
    now, waits = [100.0], []
    monkeypatch.setattr(f.time, 'monotonic', lambda: now[0])

    async def sleep(delay):
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr(f.asyncio, 'sleep', sleep)
    for chat in range(20):
        await f.api_throttle(2, chat)
    assert not waits
    await f.api_throttle(2, 20)
    assert waits == [1.0]
    await f.api_throttle(2, 20)
    assert waits[-1] == pytest.approx(1.05)


@pytest.mark.asyncio
async def test_cooldown_never_shortens(monkeypatch):
    f._rate_states.clear()
    now = [100.0]
    monkeypatch.setattr(f.time, 'monotonic', lambda: now[0])
    await f.api_cooldown(3, timedelta(seconds=30))
    now[0] += 1
    await f.api_cooldown(3, 1)
    assert f._rate_states[3].cooldown == 130.0
    await f.api_cooldown(3, 40)
    assert f._rate_states[3].cooldown == 141.0

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
