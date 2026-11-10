# Relay V2 upgrade contract

Confirmed scope: retain every existing bot/user/message/order/setting; modularize, repair all reviewed defects, complete the menus. Original relay_bot.py remains the live entry until the final cutover. Never import it or start polling its tokens in a test. Do not print tokens or customer message bodies.

## Ownership
- Parent: relayapp/config.py, defaults.py, common.py, store.py, formatting.py, payments.py, lifecycle.py, runtime.py, broadcast.py, migration/schema, deployment and integration.
- Relay agent: relayapp/relay.py plus relayapp/clone_*.py, tests/test_relay*.py and docs/克隆使用说明.md. Own clone handlers/config/features/group reception.
- Main agent: relayapp/main_ui.py plus relayapp/main_*.py and relayapp/managed.py, tests/test_main*.py and docs/主机器人使用说明.md. Own platform UI/managed creation/token/transfer/payment confirmation/config/broadcast UI.
- Do not change parent-owned files. Send precise API/schema requests. Read the original full relevant class and this contract. Changes must be actual implementation, not placeholder UI or exec/AST loading of legacy code.

## Shared imports
Existing helper names are re-exported by `from .common import *` for incremental compatibility. common exports normal standard library/telegram symbols used in legacy, all config/default/store/formatting/payment helpers. New modules should use explicit imports where practical. `get_db()` returns the process SQLite connection (close is compatibility no-op). All SQL is synchronous, never await within a transaction. `transaction()` is parent-provided BEGIN IMMEDIATE context manager. `init_db(path=None)` is idempotent and supports an isolated temporary DB. `configure_database(path)` closes/reset connection for tests. Local legacy timestamps keep Asia/Shanghai semantics; new deadline columns use unix REAL seconds.

## Existing helper compatibility and additions
- get_bot/add_bot/get_bot_by_token/get_bots_by_owner, get_setting/set_setting, all welcome/autoreply/keyboard/main UI helpers retained.
- get_conversation(bot_id, admin_id=None): MUST pass admin_id in new relay flow; set_conversation(bot_id,admin_id,user_id) isolated composite key.
- find_user_by_admin_message(bot_id,message_id,admin_chat_id=None): new relay MUST pass admin_chat_id. Unknown historical rows must not guess cross-chat.
- save_message(...,admin_chat_id=0,delivery_status='SUCCESS') -> message row id; returned IDs saved only for actual success.
- block_user(bot_id,user_id,reason='',duration_seconds=None), is_blocked auto expires, unblock_user.
- is_bot_admin/get_bot_admins dynamic; platform admin has platform authority, not implicit customer message access in each clone. Owner cannot be removed. Owner-only modifications must revalidate at submit.
- add_auto_reply defaults disabled draft; update_auto_reply supports enabled,sort_order,payload; get_auto_replies(bot_id,enabled_only=False); match_auto_reply only enabled and regex timeout.
- welcome_messages columns payload TEXT JSON, enabled INTEGER default1; auto_replies same plus enabled INTEGER default1,sort_order INTEGER default0. Existing records migrate enabled only if content is nonempty. Legacy content_text remains HTML-compatible.
- `capture_payload(message)->dict`, `send_payload(bot,chat_id,payload,reply_markup=None)->dict` returns message_id/degraded; supports text/photo/video/animation/document/voice/audio/sticker/video_note/contact/location. Preserve entities (UTF16) and never blindly retry unknown network results. `extract_emoji_from_text_html` uses PTB text_html/caption_html safely. `render_emoji_html` supports historical [emoji:ID]. `parse_inline_buttons(text, entities=())->list[list[dict]]` supports text|URL or text - URL, &&, #p/#g/#r and real custom emoji entity. `build_inline_markup(rows)`, `build_reply_keyboard(bot_id)` with string emoji IDs.
- `has_capability(bot_id,feature)->bool`, `require_capability(bot_id,feature)` raises ValueError. Enabled vip_features means VIP-required; disabled means free. Existing configured resources remain usable/readable, but new additions or edits enforce capability. free_bot_limit default5 (only new creates, never revoke existing), free_welcome_limit3, free_auto_reply_limit10; configurable in main settings.
- `settle_order(order_no,actor_id,evidence=None)->dict` idempotent same SQLite transaction marking paid + entitlement_grants(order_no UNIQUE); already-paid old orders are NOT re-granted. `activate_vip` manual grants retains permanent and uses precise expiry. `verify_paid_evidence(order,evidence)` validates returned status/order identity/amount/currency when provided; mismatches reject. Keep original OkPay endpoint/signing without leaking payloads.
- `request_transfer(bot_id,actor_id,target_id)->str` nonce; `accept_transfer(nonce,target_id)->dict`: 15min, owner CAS, old owner admin removed, all existing additional admins removed (new owner may re-add), sessions/current chats cleared; audit. System ownership only, not BotFather ownership. Target must start main bot to confirm.

## Runtime and lifecycle
MainBotHandlers uses LifecycleMixin. _start_clone_bot/_stop_clone_bot/start_all_clones preserved; `_restart_clone_bot`, `_delete_clone_bot`, `_disconnect_clone_bot`, `_rotate_clone_token(bot_id,actor_id,token)`. Each lifecycle operation locks per bot. Start validates desired_state and tombstone. Bot fields desired_state RUNNING/STOPPED/DISCONNECTED/DELETED, actual_state STOPPED/STARTING/RUNNING/STOPPING/ERROR, last_error, generation, telegram_bot_id, expires_at REAL. Keep status backward-compatible. Delete is soft tombstone (retains audit/history) and cancels managed jobs; get_bots_by_owner hides deleted. Runtime uses signal event and gracefully stops all polling before restart. Relay uses one dynamic private-message dispatcher, not static owner filters. Expose relay.handle_private_message, callback_handler, cmd_start/admin/users/clear, handle_group_message, handle_new_members. Clone allowed updates include message/callback_query/my_chat_member/chat_member. Group replies must verify registered bound staff group and replying sender is current bot admin.

## Broadcast service
`from .broadcast import broadcasts` singleton with `create(bot_id,actor_id,payload,progress_chat_id,progress_message_id=None)->int`, `action(job_id,actor_id,action)->None`, `stats(job_id,actor_id)->dict`, async `tick(bot_lookup)` and `recover()`. bot_id0 main_users; clone only own users. Owner or bot admin can clone broadcast subject capability; platform main only MAIN_ADMIN_ID. Creates require UI preview + nonce confirmation; do not send directly in callback without confirmation. Job/recipient rows persistent, UNIQUE(job_id,user_id), rate limits per bot+chat shared across modules. SENDING crash -> UNKNOWN requiring explicit retry/skip with duplicate risk warning. No blind resend on timeout, no platform broadcasting through unconsenting clones. Progress after each batch. Parent runtime ticks; UI can retrieve job detail.
`async api_throttle(bot_id,chat_id,group=False)` and `async api_cooldown(bot_id,seconds)` in formatting module, used send_payload and direct UI sends where practical.

## New data tables
- client_cases(bot_id,user_id PK composite, assigned_admin_id INTEGER NULL,state TEXT default OPEN,last_inbound_at REAL,last_outbound_at REAL,reminder_count INTEGER default0,last_reminded_at REAL,notes TEXT default''). Claim CAS, staff can transfer/close; current chat is separate per admin.
- relay_routes(bot_id,admin_chat_id,admin_message_id PK composite,user_id,original_message_id,created_at REAL). Use actual Telegram returned copy/forward IDs. Never infer from unscoped message IDs.
- ui_sessions(bot_id,user_id PK composite,state,data TEXT JSON,nonce,expires_at REAL). Draft expiry15min, consume transaction. New config writes only on confirm, no active draft.
- group_bindings(bot_id,chat_id PK composite,title,kind,enabled INTEGER default1,staff_group INTEGER default0,welcome_payload TEXT JSON default'{}',welcome_enabled INTEGER default0). Bind/activate verify bot and acting user's admin rights via API. Do not leave groups on unbind. Group customer messages are NOT broadcast to private clients.
- filter_rules(id PK,bot_id,pattern,mode contains/exact/regex,action block/warn/mute,duration_seconds,enabled default1).
- commands(bot_id,command PK composite,description,payload TEXT JSON,enabled default1).
- audit_logs(id,bot_id,actor_id,action,detail TEXT JSON,created_at REAL), owner_transfers(nonce PK,bot_id,from_user_id,to_user_id,expires_at REAL,state).
- broadcast_jobs/recipients owned by parent.

Test only isolated temp SQLite with fake bot. Real smoke only explicit MAIN_ADMIN_ID, no clone/customer messages or group mutation without explicit designated test target. Leave original live DB untouched until final stop + backup + migration + start. Ask parent about API changes immediately.
