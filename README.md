# 困困双向机器人 · 模块化版 2.0.0

Telegram 主平台和克隆客服工作台。保留既有 SQLite 数据，使用官方 Bot API，在单个受管进程内运行主机器人与各克隆；无需 Web 服务。

## 文档

- [主机器人使用说明](docs/主机器人使用说明.md)：创建、托管、所有权、Token、付费和平台管理。
- [克隆使用说明](docs/克隆使用说明.md)：客户分流、多客服、欢迎语、自动回复、键盘、过滤、群组与广播。
- [功能与修复说明](docs/功能与修复说明.md)：模块结构和本次行为变化。
- [部署与维护](docs/部署与维护.md)：环境、服务、健康检查、备份、迁移及回滚边界。
- [升级验收报告](docs/升级验收报告.md)：数据保留、232 项回归、实际 Telegram 回执与未实测范围。

## 运行

Python 3.12 和项目独立虚拟环境。安装 `requirements.txt`，参考 `.env.example` 创建私有 `.env`，由服务账号读取。

```bash
.venv/bin/python -m relayapp.runtime
```

兼容入口 `relay_bot.py` 仅调用上述模块，导入时不会启动机器人。正式部署使用 `tg-relay.service`；不要另外手动启动第二个轮询进程。

```bash
systemctl status tg-relay.service
runuser -u www -- .venv/bin/python scripts/health.py
runuser -u www -- .venv/bin/python scripts/backup.py
```

## 测试

```bash
runuser -u www -- env PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 \
  MAIN_BOT_TOKEN=OFFLINE_TEST MAIN_ADMIN_ID=123456789 \
  RELAY_DB_PATH=/tmp/relay-tests-unused.sqlite3 \
  .venv/bin/python -m pytest -p no:cacheprovider -q
```

测试使用临时 SQLite 和假网络，不读生产 Token，不向客户发送消息。管理员实际私聊诊断另见部署文档，必须显式指定并确认目标。

## 交付边界

源码交付不含 `.env`、机器人 Token、客户数据库、旧代码备份、虚拟环境、日志或私聊验收回执。实际升级保留的历史数据和私人备份仅留在服务器。Telegram 判定 Token 无效的克隆必须由所有者提供同一机器人的有效 Token；软件升级无法替换失效凭据。
