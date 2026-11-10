# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Lossless Telegram payloads, presentation helpers and process-local API pacing."""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import timedelta
import html
import ipaddress
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      MessageEntity, ReplyKeyboardMarkup)
from telegram.error import BadRequest, RetryAfter

from .configuration import get_setting

__all__ = [
    'capture_payload', 'send_payload', 'extract_emoji_from_text_html',
    'render_emoji_html', 'parse_inline_buttons', 'build_inline_markup',
    'build_reply_keyboard', 'user_display', 'user_id_link', 'gen_bot_username',
    'api_throttle', 'api_cooldown', 'api_call',
]

_STYLES = {'p': 'primary', 'g': 'success', 'r': 'danger'}
_MEDIA = ('photo', 'video', 'animation', 'document', 'voice', 'audio',
          'sticker', 'video_note')
_CAPTION_MEDIA = {'photo', 'video', 'animation', 'document', 'voice', 'audio'}


def _entity_dict(entity):
    if isinstance(entity, MessageEntity):
        return entity.to_dict()
    if isinstance(entity, dict):
        return dict(entity)
    raise ValueError('Entities must be MessageEntity instances or dictionaries')


def _validated_entities(text, entities):
    if not isinstance(text, str):
        raise ValueError('Payload text must be a string')
    boundaries = {0}
    position = 0
    for char in text:
        if 0xD800 <= ord(char) <= 0xDFFF:
            raise ValueError('Text contains an unpaired UTF-16 surrogate')
        position += 2 if ord(char) > 0xFFFF else 1
        boundaries.add(position)
    result = []
    for raw in entities or ():
        item = _entity_dict(raw)
        offset, length = item.get('offset'), item.get('length')
        if (type(offset) is not int or type(length) is not int or length <= 0
                or offset not in boundaries or offset + length not in boundaries):
            raise ValueError('Entity range must align to UTF-16 character boundaries')
        if item.get('type') not in MessageEntity.ALL_TYPES:
            raise ValueError('Unsupported entity type')
        if item['type'] == 'custom_emoji':
            icon = str(item.get('custom_emoji_id') or '')
            if not icon.isascii() or not icon.isdigit():
                raise ValueError('Custom emoji ID must be a numeric string')
            item['custom_emoji_id'] = icon
        if item['type'] == 'text_link' and not isinstance(item.get('url'), str):
            raise ValueError('text_link requires a URL')
        if item['type'] == 'text_mention' and not isinstance(item.get('user'), dict):
            raise ValueError('text_mention requires a user')
        result.append(item)
    # Nested styles are valid; partial overlaps and code/style overlaps are not.
    for i, left in enumerate(result):
        a, b = left['offset'], left['offset'] + left['length']
        for right in result[i + 1:]:
            c, d = right['offset'], right['offset'] + right['length']
            if max(a, c) >= min(b, d):
                continue
            if not ((a <= c and d <= b) or (c <= a and b <= d)):
                raise ValueError('Entity ranges may nest but must not cross')
            if left['type'] in ('code', 'pre') or right['type'] in ('code', 'pre'):
                raise ValueError('Code/pre entities must not overlap other entities')
            styles = {'bold', 'italic', 'underline', 'strikethrough', 'spoiler'}
            quotes = {'blockquote', 'expandable_blockquote'}
            if left['type'] in quotes and right['type'] in quotes:
                raise ValueError('Blockquote entities must not nest')
            if (left['type'] not in styles | quotes
                    and right['type'] not in styles | quotes):
                raise ValueError('Non-style entities must not contain one another')
    return result


def capture_payload(message) -> dict:
    """Capture JSON-compatible text/entities; captions use the same keys as text."""
    is_text = getattr(message, 'text', None) is not None
    text = (getattr(message, 'text', None) if is_text
            else getattr(message, 'caption', None)) or ''
    entities = (getattr(message, 'entities', ()) if is_text
                else getattr(message, 'caption_entities', ()))
    payload = {'type': 'text', 'text': text, 'file_id': None,
               'entities': _validated_entities(text, entities), 'buttons': [],
               'protect_content': bool(getattr(message, 'has_protected_content', False))}
    for kind in _MEDIA:
        media = getattr(message, kind, None)
        if media:
            if kind == 'photo':
                media = media[-1]
            payload.update(type=kind, file_id=media.file_id)
            break
    else:
        for kind in ('contact', 'location'):
            media = getattr(message, kind, None)
            if media:
                payload.update(type=kind)
                fields = ('phone_number', 'first_name', 'last_name', 'vcard') if kind == 'contact' else (
                    'latitude', 'longitude', 'horizontal_accuracy')
                payload[kind] = {key: getattr(media, key) for key in fields
                                 if getattr(media, key, None) is not None}
                break
        else:
            if not is_text:
                raise ValueError('Unsupported message type')
    markup = getattr(message, 'reply_markup', None)
    if markup and getattr(markup, 'inline_keyboard', None):
        payload['buttons'] = [[button.to_dict() for button in row]
                              for row in markup.inline_keyboard]
    return payload


def extract_emoji_from_text_html(message) -> str:
    """Use PTB's escaped HTML renderer, never reinterpret literal user markup."""
    if message is None:
        return ''
    if getattr(message, 'text', None) is not None:
        text, rendered = message.text, getattr(message, 'text_html', None)
    elif getattr(message, 'caption', None) is not None:
        text, rendered = message.caption, getattr(message, 'caption_html', None)
    else:
        return ''
    return rendered if rendered is not None else html.escape(text)


def render_emoji_html(text) -> str:
    """Render trusted historical HTML with legacy [emoji:ID] placeholders."""
    return re.sub(r'\[emoji:+([0-9]+)\]', r'<tg-emoji emoji-id="\1">⭐</tg-emoji>', text or '')


def _valid_url(url):
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    if '\\' in url:
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ('http', 'https', 'tg') or not parsed.netloc:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if parsed.scheme.lower() in ('http', 'https'):
            host = parsed.hostname
            if not host or parsed.port == 0:
                return False
            if ':' in host:
                ipaddress.IPv6Address(host)
            else:
                ascii_host = host.encode('idna').decode('ascii').rstrip('.')
                if len(ascii_host) > 253 or any(not re.fullmatch(
                        r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                        for label in ascii_host.split('.')):
                    return False
            return True
        return bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', parsed.netloc))
    except (ValueError, UnicodeError):
        return False


def _button_options(button):
    options = {}
    style = button.get('style', button.get('color'))
    if style and style != 'default':
        if style not in ('primary', 'success', 'danger'):
            raise ValueError('Invalid button style')
        options['style'] = style
    icon = button.get('icon_custom_emoji_id', button.get('emoji_id'))
    if icon:
        icon = str(icon)
        if not icon.isascii() or not icon.isdigit():
            raise ValueError('Button emoji ID must be a numeric string')
        options['icon_custom_emoji_id'] = icon
    return options


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

def parse_inline_buttons(text, entities=()) -> list:
    """Parse one row per line, with && separating buttons within each row."""
    if not isinstance(text, str):
        raise ValueError('Button specification must be text')
    validated = _validated_entities(text, entities)
    encoded = text.encode('utf-16-le')
    icons = []
    for entity in validated:
        if entity['type'] == 'custom_emoji':
            start = len(encoded[:entity['offset'] * 2].decode('utf-16-le'))
            end = len(encoded[:(entity['offset'] + entity['length']) * 2].decode('utf-16-le'))
            icons.append((start, end, entity['custom_emoji_id']))
    rows, base, count = [], 0, 0
    for line in text.splitlines(keepends=True):
        row, cursor = [], base
        for part in line.rstrip('\r\n').split('&&'):
            match = re.fullmatch(r'\s*(.*?)\s*(?:\|| - )\s*(\S+)\s*', part)
            if not match:
                if part.strip():
                    raise ValueError('Each button needs text|URL or text - URL')
                cursor += len(part) + 2
                continue
            label, url = match.group(1), match.group(2)
            if not _valid_url(url):
                raise ValueError('Button URL must use http(s) or tg with a valid host')
            start, end = cursor + match.start(1), cursor + match.end(1)
            found = [(a, b, icon) for a, b, icon in icons if start <= a and b <= end]
            if len(found) > 1:
                raise ValueError('A button supports only one custom emoji icon')
            icon = found[0][2] if found else None
            if found:
                a, b, _ = found[0]
                label = label[:a - start] + label[b - start:]
            style_match = re.search(r'#([pgr])(?=\s|$)|^#([pgr])', label)
            style = _STYLES[next(value for value in style_match.groups() if value)] if style_match else None
            label = re.sub(r'#[pgr](?=\s|$)|^#[pgr]', ' ', label).strip()
            if not label or len(label) > 64:
                raise ValueError('Button label must contain 1 to 64 characters')
            button = {'text': label, 'url': url}
            if style:
                button['style'] = style
            if icon:
                button['icon_custom_emoji_id'] = icon
            row.append(button)
            cursor += len(part) + 2
        if row:
            if len(row) > 10:
                raise ValueError('At most 10 buttons per row')
            rows.append(row)
            count += len(row)
        base += len(line)
    if count > 100:
        raise ValueError('At most 100 buttons in a keyboard')
    return rows


def build_inline_markup(rows):
    if not rows:
        return None
    if sum(len(row) for row in rows) > 100 or any(len(row) > 10 for row in rows):
        raise ValueError('Keyboard exceeds Telegram button limits')
    result = []
    for row in rows:
        buttons = []
        for item in row:
            item = item.to_dict() if isinstance(item, InlineKeyboardButton) else dict(item)
            if 'url' in item and not _valid_url(item['url']):
                raise ValueError('Unsafe inline button URL')
            if not item.get('text'):
                raise ValueError('Empty button label')
            # Captured callback/web-app buttons retain their native action.
            options = {key: value for key, value in item.items()
                       if key not in ('text', 'style', 'color', 'emoji_id', 'icon_custom_emoji_id')}
            buttons.append(InlineKeyboardButton(item['text'], **options, **_button_options(item)))
        if buttons:
            result.append(buttons)
    return InlineKeyboardMarkup(result) if result else None


def build_reply_keyboard(bot_id):
    if get_setting(bot_id, 'reply_kb_enabled', '0') != '1':
        return None
    try:
        buttons = json.loads(get_setting(bot_id, 'reply_kb_buttons', '[]'))
        per_row = int(get_setting(bot_id, 'reply_kb_per_row', '2'))
    except (TypeError, ValueError):
        raise ValueError('Invalid reply keyboard configuration') from None
    if not isinstance(buttons, list) or not 1 <= per_row <= 10 or len(buttons) > 100:
        raise ValueError('Invalid reply keyboard limits')
    rows = []
    for offset in range(0, len(buttons), per_row):
        row = []
        for item in buttons[offset:offset + per_row]:
            item = {'text': item} if isinstance(item, str) else item
            if not isinstance(item, dict) or not item.get('text'):
                raise ValueError('Invalid reply button')
            row.append(KeyboardButton(item['text'], **_button_options(item)))
        rows.append(row)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True) if rows else None


def user_display(user) -> str:
    if user is None:
        return ''
    def value(key):
        try:
            return user[key]
        except (TypeError, KeyError, IndexError):
            return getattr(user, key, None)
    name = value('full_name') or ' '.join(str(value(key) or '') for key in ('first_name', 'last_name')).strip()
    name = name or value('username') or str(value('user_id') or value('id') or '')
    return html.escape(str(name))


def user_id_link(user_id) -> str:
    identity = int(user_id)
    return f'<a href="tg://user?id={identity}">{identity}</a>'


def gen_bot_username() -> str:
    return 'relay_' + secrets.token_hex(8) + '_bot'


class _RateState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.sent = deque()
        self.chats = {}
        self.cooldown = 0.0


_rate_states = {}


def _rate_state(bot_id):
    return _rate_states.setdefault(bot_id, _RateState())


async def api_throttle(bot_id, chat_id, group=False):
    """Wait without holding a global reservation while another chat is cooling."""
    state = _rate_state(bot_id)
    interval = 3.1 if group else 1.05
    while True:
        async with state.lock:
            now = time.monotonic()
            while state.sent and state.sent[0] <= now - 1.0:
                state.sent.popleft()
            wait_until = max(state.cooldown, state.chats.get(chat_id, 0.0))
            if len(state.sent) >= 20:
                wait_until = max(wait_until, state.sent[0] + 1.0)
            delay = wait_until - now
            if delay <= 0:
                state.sent.append(now)
                state.chats[chat_id] = now + interval
                return
        await asyncio.sleep(delay)


async def api_cooldown(bot_id, seconds):
    state = _rate_state(bot_id)
    seconds = seconds.total_seconds() if isinstance(seconds, timedelta) else float(seconds)
    async with state.lock:
        state.cooldown = max(state.cooldown, time.monotonic() + max(0.0, seconds))


async def _paced_call(bot, chat_id, method, kwargs, retry_budget, before_send=None):
    identity = bot.id
    call = getattr(bot, method) if isinstance(method, str) else method
    group = isinstance(chat_id, int) and chat_id < 0
    while True:
        await api_throttle(identity, chat_id, group=group)
        if before_send is not None:
            before_send()
        try:
            return await call(chat_id=chat_id, **kwargs)
        except RetryAfter as exc:
            await api_cooldown(identity, exc.retry_after)
            if not retry_budget[0]:
                raise
            retry_budget[0] -= 1


async def api_call(bot, chat_id, method, **kwargs):
    """Pace a UI/API call; retry one explicit RetryAfter, never uncertain errors."""
    return await _paced_call(bot, chat_id, method, kwargs, [1])


def _emoji_permission_error(error):
    text = str(error).lower().replace('_', ' ')
    return any(marker in text for marker in (
        'custom emoji entities are not allowed', 'custom emoji are not allowed',
        'custom emoji is not allowed', 'custom emoji can be used only',
        'not enough rights to send custom emoji', 'not enough rights to use custom emoji',
        'custom emoji not allowed', 'custom emoji entities not allowed',
        'bot must have a purchased username',
        'custom emoji usage is not allowed', 'custom emoji entities are not supported',
        'custom emoji are not supported for this bot',
        'custom emoji can only be used', 'custom emoji requires premium',
        'bot is not allowed to use custom emoji',
    ))


def _strip_icons(markup):
    if markup is None:
        return None, False
    data = markup.to_dict()
    removed = False
    for row in data.get('inline_keyboard', data.get('keyboard', [])):
        for button in row:
            if isinstance(button, dict) and 'icon_custom_emoji_id' in button:
                del button['icon_custom_emoji_id']
                removed = True
    if not removed:
        return markup, False
    cls = InlineKeyboardMarkup if 'inline_keyboard' in data else ReplyKeyboardMarkup
    return cls.de_json(data, None), True


async def send_payload(bot, chat_id, payload, reply_markup=None, *, before_send=None) -> dict:
    kind = payload.get('type', payload.get('content_type', 'text'))
    if kind not in ('text', 'contact', 'location', *_MEDIA):
        raise ValueError('Unsupported payload type')
    text = payload.get('text', payload.get('content_text', '')) or ''
    legacy = payload.get('legacy_html', 'content_text' in payload)
    if isinstance(legacy, str) and legacy:
        text = legacy
    if legacy and payload.get('entities'):
        raise ValueError('Cannot combine legacy HTML with native entities')
    entities = _validated_entities(text, payload.get('entities', ()))
    markup = reply_markup if reply_markup is not None else build_inline_markup(payload.get('buttons', []))
    kwargs = {'protect_content': bool(payload.get('protect_content', False)), 'reply_markup': markup}
    if kind == 'text' or kind in _CAPTION_MEDIA:
        kwargs['parse_mode'] = 'HTML' if legacy else None
        kwargs['text' if kind == 'text' else 'caption'] = render_emoji_html(text) if legacy else text
        if not legacy:
            kwargs['entities' if kind == 'text' else 'caption_entities'] = [
                MessageEntity.de_json(entity, bot) for entity in entities]
    if kind in _MEDIA:
        if not payload.get('file_id'):
            raise ValueError('Media payload requires file_id')
        kwargs[kind] = payload['file_id']
    elif kind in ('contact', 'location'):
        source = payload.get(kind, payload)
        fields = ('phone_number', 'first_name', 'last_name', 'vcard') if kind == 'contact' else (
            'latitude', 'longitude', 'horizontal_accuracy')
        kwargs.update({key: source[key] for key in fields if key in source})
        required = ('phone_number', 'first_name') if kind == 'contact' else ('latitude', 'longitude')
        if any(key not in kwargs for key in required):
            raise ValueError('Missing contact/location fields')
    method = 'send_message' if kind == 'text' else 'send_' + kind
    degraded = False
    retry_budget = [1]
    try:
        message = await _paced_call(bot, chat_id, method, kwargs, retry_budget, before_send=before_send)
    except BadRequest as exc:
        if not _emoji_permission_error(exc):
            raise
        for key in ('entities', 'caption_entities'):
            if key in kwargs:
                original = kwargs[key]
                kwargs[key] = [entity for entity in original if entity.type != 'custom_emoji']
                degraded = degraded or len(original) != len(kwargs[key])
        if legacy and (kind == 'text' or kind in _CAPTION_MEDIA):
            key = 'text' if kind == 'text' else 'caption'
            stripped = re.sub(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', r'\1', kwargs[key], flags=re.S)
            degraded = degraded or stripped != kwargs[key]
            kwargs[key] = stripped
        kwargs['reply_markup'], removed = _strip_icons(kwargs['reply_markup'])
        degraded = degraded or removed
        if not degraded:
            raise
        message = await _paced_call(bot, chat_id, method, kwargs, retry_budget, before_send=before_send)
    return {'message_id': message.message_id, 'degraded': degraded}

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
