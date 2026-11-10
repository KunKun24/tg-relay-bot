# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Compatibility imports for handlers, without loading the legacy entry point."""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import string
import time
from datetime import datetime, timedelta
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

from zoneinfo import ZoneInfo
import aiohttp
from telegram import (Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (Application, CommandHandler, MessageHandler, CallbackQueryHandler,
                          ContextTypes, filters)
from telegram.error import (TelegramError, BadRequest, Forbidden, NetworkError,
                            TimedOut, RetryAfter, InvalidToken)
from .config import *
from .defaults import *
from .store import *
from .formatting import *

logger = logging.getLogger('relayapp')

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
