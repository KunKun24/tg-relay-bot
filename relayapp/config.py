# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询

from __future__ import annotations

import logging
import os
from pathlib import Path
import re

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN', '')
MAIN_BOT_USERNAME = os.getenv('MAIN_BOT_USERNAME', '')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '0'))
DB_PATH = os.getenv('RELAY_DB_PATH', str(ROOT / 'relay_bot.db'))
# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询



class SecretFilter(logging.Filter):
    def filter(self, record):
        text = record.getMessage()
        record.msg = re.sub(r'\b\d{6,12}:[A-Za-z0-9_-]{25,}\b', '[REDACTED_TOKEN]', text)
        record.args = ()
        return True


def configure_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretFilter())
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
