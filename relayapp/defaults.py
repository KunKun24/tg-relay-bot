# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创

"""Default interface text, button metadata and subscription plans."""

DEFAULT_TEXTS = {
    "welcome": "你好！\n欢迎使用双向机器人制，点击下方的添加机器人 添加机器人吧！",
    "verifying_token": "🔍 正在验证Token可行性...",
    "token_success": "✅ Token验证通过！",
    "token_failed": "❌ Token验证失败：{error}",
    "creating_bot": "⏳ 正在配置中，请稍等，请不要重复发送token",
    "created_bot": "✅ 配置成功\n\n机器人 @{username} 已完成配置\n现在可以发送 /start 开始使用",
    "admin_panel": "⚙️ 管理员后台\n\n选择要修改的内容：",
    "add_bot_page": "请选择添加机器人方式：\n\n1. 发送 Token 创建\n在 @BotFather 创建机器人后，把 Bot Token 发给我。\n\n2. 一键创建双向机器人\nTelegram 会打开创建窗口，创建完成后系统会自动完成配置，无需再发送 /start。", 
    "add_token_page": (
        "📋 <b>机器人添加流程：</b>\n"
        "1️⃣ 打开 @BotFather\n"
        "2️⃣ 发送 /newbot\n"
        "3️⃣ 设置机器人名字，可中文\n"
        "4️⃣ 设置机器人username，英文+数字，需要以bot结尾\n"
        "5️⃣ 复制生成的Token，直接发给我\n\n"
        "<b>Token格式示例：</b>\n"
        "<code>&lt;BOT_ID&gt;:&lt;BOT_TOKEN&gt;</code>\n\n"
        "‼️ <b>注意：</b>同一个 Token 不要在其他程序或服务器同时轮询，否则可能发生冲突。\n"
        "接入前请确认原有程序已停止使用此 Token 接收消息。"
),
    "mybots_title": "🤖 你的机器人",
    "mybots_desc": "点击@账号直达，点设置查看更多信息。",
    "mybots_empty": "📭 你还没有克隆机器人\n\n点击下方按钮添加",
    "confirm_delete": "⚠️ 确认删除该机器人？操作不可恢复",
    "bot_settings_title": "⚙️ 机器人设置",
    "bot_settings_info": (
        "机器人： @{username}\n"
        "当前版本：{version}\n"
        "机器人状态：{status}\n"
        "到期时间：{expire}\n\n"
        "💡 <b>温馨提示：</b>\n"
        "需要更换机器人上岗时，请先断开机器人，否则会触发封禁。\n"
        "机器人出现问题时，可以点重启机器人，类似电脑重启。\n"
        "转移所属权时，需要将对方添加为机器人管理员。"
    ),
    "bot_disconnect_confirm": "⚠️ 确认断开该机器人？断开后将停止接收消息。",
    "bot_disconnected": "✅ 机器人已断开连接",
    "bot_reconnected": "✅ 机器人已恢复连接",
    "bot_restarting": "🔄 正在重启机器人...",
    "bot_restarted": "✅ 机器人已重启",
    "bot_reset_token_prompt": "📝 请输入新的 Bot Token（格式如：123456:AAABBB...），请在 2 分钟内输入：",
    "bot_reset_token_success": "✅ 新 Token 设置成功，机器人已自动恢复运行。",
    "bot_reset_token_failed": "❌ Token 验证失败：{error}",
    "bot_transfer_select": "🔄 请选择要转移所有权的机器人：",
    "bot_transfer_input_id": "📝 请输入要转移给的 Telegram 用户ID（纯数字，如 123456789）：",
"bot_transfer_success": "✅ 所属权已成功转移，对方可立即管理该机器人",
    "bot_timezone_prompt": "🌐 请输入新的时区（如 Asia/Shanghai、UTC、America/New_York）：",
    "bot_timezone_success": "✅ 时区已更新为 {timezone}",
    "vip_title": "💎 会员开通/续费",
    "vip_plans": "1个月：5U\n3个月：10U\n永久：30U",
    "vip_prompt": "请点击下方套餐，创建您的订单并进行支付，付款后点\"我已支付\"。",
    "vip_creating": "⏳ 正在创建支付订单...",
    "vip_pay_info": "💎 订单已创建\n\n套餐：{plan_name}\n金额：{amount} USDT\n订单号：{order_id}\n\n请点击下方按钮前往支付，支付完成后点\"我已支付\"。",
    "vip_paid_checking": "⏳ 正在查询支付状态...",
    "vip_paid_success": "✅ 支付成功！{plan_name} 已开通/续费，到期时间：{expire}",
    "vip_paid_pending": "⏳ 订单尚未支付，请完成支付后再查询。",
    "vip_paid_failed": "❌ 订单查询失败，请稍后重试或联系客服。",
    "free_tip_text": "欢迎咨询，请留言。\n\n本消息由 @sxjiqirebot 试用版发送",
    "clone_admin_panel": "⚙️ 管理面板\n\n{version}\n👥 总用户：{total_users}   ·   {pending}\n\n选择下方功能开始操作",
    "clone_stats_panel": (
        "📊 <b>数据统计</b>\n\n"
        "{version}\n\n"
        "👤 <b>用户</b>\n"
        "  · 总用户数：{total_users}\n"
        "  · 今日新增：{today_new}\n"
"  · 已拉黑：{blocked}（{blocked_pct}%）\n\n"
        "💬 <b>客服</b>\n"
        "  · 待回复：{pending} 人（近30分钟）\n"
        "  · 今日活跃客户：{active_today} 人\n"
        "  · 今日消息数：{messages_today} 条\n\n"
        "<i>数据时间：{update_time}</i>"
    ),
    # 克隆机器人-用户消息通知管理员
    "clone_new_user_notify": "🆕 用户：{name} 激活了机器人\n🆔 ID：{id}",
    "clone_op_title": "👤 客户 {name} (ID:{id}) 操作：",
    "clone_switched": "✅ 已切换至客户 {name} (<code>{id}</code>)\n现在直接发消息即可与该客户聊天。",
    "clone_mute_success": "🔇 已禁言客户 {name}，时长：{duration}",
    "clone_unmute_success": "🔊 已解除禁言客户 {name}",
    # 克隆机器人-欢迎语
    "clone_welcome_title_empty": "📝 欢迎语",
    "clone_welcome_title_list": "📝 欢迎语管理",
    "clone_welcome_empty": "还没有添加任何欢迎语",
    "clone_welcome_trigger": "欢迎语会在以下场景触发：\n  · 客户首次给机器人发消息\n  · 客户发送 /start 命令\n  · 距上次欢迎语超过 24 小时再次咨询",
    "clone_welcome_add_hint": "点击下方按钮添加你的第一条欢迎语",
    "clone_welcome_count": "已配置 <b>{count}</b> 条欢迎语",
    "clone_welcome_random": "多条欢迎语会按添加顺序依次展示",
    "clone_welcome_action_hint": "点击查看/删除",
"clone_welcome_add_prompt": "请发送欢迎语文字，图片/视频/文件，或回复一条要保存的帖子：",
    "clone_welcome_add_prompt_free": "请发送欢迎语文字或图片（普通版不支持视频/文件）：",
    "clone_welcome_added": "✅ 欢迎语已添加",
    "clone_welcome_detail_title": "📝 欢迎语内容：",
    "clone_trial_notice": "本消息由 @sxjiqirebot 试用版发送",
    # 克隆机器人-自动回复
    "clone_ar_title_empty": "🤖 自动回复",
    "clone_ar_title_list": "🤖 自动回复管理",
    "clone_ar_empty": "还没有添加任何自动回复",
    "clone_ar_hint": "用户发送包含关键词的消息时，机器人会自动回复。\n点击下方按钮添加第一条自动回复",
    "clone_ar_count": "已配置 <b>{count}</b> 条自动回复",
    "clone_ar_add_keyword": "请输入关键词：\n\n支持三种匹配模式：\n  · 包含匹配：消息中有关键词就触发\n  · 精确匹配：消息完全等于关键词才触发\n  · 正则匹配：用正则表达式匹配",
    "clone_ar_add_content": "关键词：<code>{keyword}</code>\n匹配模式：{mode}\n\n请发送回复内容（文字/图片/视频/文件），会员图标和HTML格式自动解析：",
    "clone_ar_add_inline": "回复内容已保存。\n\n是否添加内联按钮？（消息下方的按钮，可跳转链接）\n点击下方按钮选择：",
    "clone_ar_added": "✅ 自动回复已添加",
    "clone_ar_detail_title": "🤖 自动回复详情：",
    "clone_ar_mode_contains": "包含匹配",
    "clone_ar_mode_exact": "精确匹配",
    "clone_ar_mode_regex": "正则匹配",
"clone_ar_inline_prompt": "请输入内联按钮配置，每行一个按钮，格式：文字|链接\n例如：\n点击跳转|https://google.com\n联系客服|https://t.me/xxx\n\n不添加请发送 无",
}


# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创


DEFAULT_BUTTONS = {
    "btn_add":      {"text": "➕ 添加机器人", "type": "fixed", "action": "add_bot", "color": "success", "emoji_id": ""},
    "btn_manage":   {"text": "📋 管理我的机器人", "type": "fixed", "action": "my_bots", "color": "", "emoji_id": ""},
    "btn_contact":  {"text": "💬 联系客服", "type": "url", "url": "", "color": "", "emoji_id": ""},
    "btn_billing":  {"text": "💰 记账机器人", "type": "url", "url": "", "color": "", "emoji_id": ""},
    "btn_channel":  {"text": "📢 加入频道", "type": "url", "url": "", "color": "", "emoji_id": ""},
    "btn_ad":       {"text": "📢 广告中心", "type": "url", "url": "", "color": "", "emoji_id": ""},
    "btn_help":     {"text": "❓ 帮助教程", "type": "url", "url": "", "color": "", "emoji_id": ""},
    "btn_add_token": {"text": "📝 发送Token创建", "type": "fixed", "action": "add_token", "color": "", "emoji_id": ""},
"btn_add_oneclick": {"text": "🚀 一键创建双向机器人", "type": "fixed", "action": "add_oneclick", "color": "success", "emoji_id": ""},
    "btn_cancel":   {"text": "❌ 取消", "type": "fixed", "action": "back_start", "color": "danger", "emoji_id": ""},
    "btn_token_cancel": {"text": "❌ 取消", "type": "fixed", "action": "back_start", "color": "danger", "emoji_id": ""},
    "btn_bot_settings": {"text": "⚙️ 设置", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "btn_bot_delete": {"text": "🗑️ 删除", "type": "fixed", "action": "", "color": "danger", "emoji_id": ""},
    "btn_confirm_delete": {"text": "✅ 确认删除", "type": "fixed", "action": "", "color": "danger", "emoji_id": ""},
    "btn_cancel_delete": {"text": "❌ 取消", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "btn_enter_bot": {"text": "🤖 进入机器人", "type": "url", "url": "", "color": "success", "emoji_id": ""},
    "btn_upgrade": {"text": "💎 续费高级版", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "btn_reset_token": {"text": "🔑 重置令牌", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
"btn_contact_cs": {"text": "💬 联系客服", "type": "url", "url": "", "color": "", "emoji_id": ""},
    "btn_restart_bot": {"text": "🔄 重启机器人", "type": "fixed", "action": "", "color": "success", "emoji_id": ""},
    "btn_disconnect": {"text": "⛔ 断开机器人", "type": "fixed", "action": "", "color": "danger", "emoji_id": ""},
    "btn_reconnect": {"text": "✅ 恢复机器人", "type": "fixed", "action": "", "color": "success", "emoji_id": ""},
    "btn_transfer_owner": {"text": "🔄 转移所属权", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "btn_transfer_time": {"text": "🌐 转移专业版时间", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "btn_back_mybots": {"text": "🔙 BACK", "type": "fixed", "action": "my_bots", "color": "", "emoji_id": ""},
    "btn_back_settings": {"text": "🔙 返回机器人设置", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "btn_plan_1m": {"text": "1个月 5U", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "btn_plan_3m": {"text": "3个月 10U", "type": "fixed", "action": "", "color": "success", "emoji_id": ""},
"btn_plan_forever": {"text": "永久 30U", "type": "fixed", "action": "", "color": "danger", "emoji_id": ""},
    "btn_go_pay": {"text": "💳 前往支付", "type": "url", "url": "", "color": "success", "emoji_id": ""},
    "btn_i_paid": {"text": "✅ 我已支付", "type": "fixed", "action": "", "color": "success", "emoji_id": ""},
    # 克隆机器人管理面板按钮
    "cad_clients": {"text": "👥 我的客户", "type": "fixed", "action": "cad_clients", "color": "", "emoji_id": ""},
    "cad_stats": {"text": "📊 数据统计", "type": "fixed", "action": "cad_stats", "color": "", "emoji_id": ""},
    "cad_welcome": {"text": "👋 欢迎语", "type": "fixed", "action": "cad_welcome", "color": "", "emoji_id": ""},
    "cad_autoreply": {"text": "🤖 自动回复", "type": "fixed", "action": "cad_autoreply", "color": "", "emoji_id": ""},
    "cad_replykb": {"text": "⌨️ 底部键盘", "type": "fixed", "action": "cad_replykb", "color": "", "emoji_id": ""},
    "cad_blacklist": {"text": "🚫 黑名单", "type": "fixed", "action": "cad_blacklist", "color": "danger", "emoji_id": ""},
"cad_filter": {"text": "🛡️ 过滤词/验证", "type": "fixed", "action": "cad_filter", "color": "", "emoji_id": ""},
    "cad_groups": {"text": "📢 我的群组/频道", "type": "fixed", "action": "cad_groups", "color": "", "emoji_id": ""},
    "cad_join_welcome": {"text": "🎉 进群欢迎", "type": "fixed", "action": "cad_join_welcome", "color": "", "emoji_id": ""},
    "cad_broadcast": {"text": "📣 全员广播", "type": "fixed", "action": "cad_broadcast", "color": "success", "emoji_id": ""},
    "cad_visitor": {"text": "⏰ 访客唤醒设置", "type": "fixed", "action": "cad_visitor", "color": "", "emoji_id": ""},
    "cad_admins": {"text": "👤 管理员", "type": "fixed", "action": "cad_admins", "color": "", "emoji_id": ""},
    "cad_commands": {"text": "⌨️ 指令管理", "type": "fixed", "action": "cad_commands", "color": "", "emoji_id": ""},
    "cad_vip": {"text": "💎 专业版充值", "type": "fixed", "action": "cad_vip", "color": "success", "emoji_id": ""},
    # 数据统计页面按钮
    "cad_stats_refresh": {"text": "🔄 刷新", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
"cad_stats_clients": {"text": "👥 我的客户", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "cad_stats_home": {"text": "🏠 主菜单", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    # 克隆机器人-操作按钮
    "clone_btn_switch": {"text": "🔀 切换至{name}", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_mute_1d": {"text": "⏰ 一天", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_mute_1w": {"text": "📅 一周", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_mute_1m": {"text": "🗓️ 一月", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_mute_forever": {"text": "♾️ 永久", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_user_list": {"text": "📋 我的客户列表", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    # 克隆机器人-欢迎语按钮
    "clone_btn_welcome_add": {"text": "➕ 添加欢迎语", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_welcome_home": {"text": "🏠 主菜单", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
"clone_btn_welcome_delete": {"text": "🗑️ 删除", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_welcome_back": {"text": "🔙 返回", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    # 克隆机器人-自动回复按钮
    "clone_btn_ar_add": {"text": "➕ 添加自动回复", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_home": {"text": "🏠 主菜单", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_delete": {"text": "🗑️ 删除", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_edit": {"text": "✏️ 编辑", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_back": {"text": "🔙 返回", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_skip_inline": {"text": "⏭️ 跳过内联按钮", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_add_inline": {"text": "➕ 添加内联按钮", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_mode_contains": {"text": "包含匹配", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
"clone_btn_ar_mode_exact": {"text": "精确匹配", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
    "clone_btn_ar_mode_regex": {"text": "正则匹配", "type": "fixed", "action": "", "color": "", "emoji_id": ""},
}


BUTTON_LAYOUT = [
    ["btn_add"],
    ["btn_manage", "btn_contact"],
    ["btn_billing", "btn_channel"],
    ["btn_ad", "btn_help"],
]


OKPAY_API_URL = "https://api.okaypay.me/shop/"


VIP_PLANS = {
    "1m": {"name": "1个月", "amount": 5.0, "days": 30},
    "3m": {"name": "3个月", "amount": 10.0, "days": 90},
    "forever": {"name": "永久", "amount": 30.0, "days": 0},
}


DEFAULT_VIP_FEATURES = {
    "unlimited_bots": "无限创建机器人",
    "broadcast": "广播消息",
    "user_stats": "用户统计",
    "custom_welcome": "自定义欢迎语",
    "auto_reply": "关键词自动回复",
}

# 困困双向机器人
# 由 TG 困困开源 @sad1881 困困承接各种业务 欢迎咨询
# 本源码由 DeepSeek V4.1 / V4 Pro 开发 转载请尊重原创
