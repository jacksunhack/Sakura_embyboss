"""
启动面板start命令 返回面ban

+ myinfo 个人数据
+ count  服务器媒体数
"""
import asyncio
from pyrogram import filters

from bot.func_helper.emby import Embyservice
from bot.func_helper.utils import judge_admins, members_info, open_check
from bot.modules.commands.exchange import rgs_code
from bot.sql_helper.sql_emby import sql_add_emby as sync_sql_add_emby, sql_update_emby as sync_sql_update_emby, Emby # Import Emby model
from bot.sql_helper.sql_invitations import sql_get_invitation_by_code, sql_mark_invitation_completed # Async versions
from bot.func_helper.filters import user_in_group_filter, user_in_group_on_filter
from bot.func_helper.msg_utils import deleteMessage, sendMessage, sendPhoto, callAnswer, editMessage
from bot.func_helper.fix_bottons import group_f, judge_start_ikb, judge_group_ikb, cr_kk_ikb
from bot.modules.extra import user_cha_ip
from bot import bot, prefixes, group, bot_photo, ranks, sakura_b, _open, LOGGER # Import _open and LOGGER

# Async wrapper for synchronous DB calls (if not already globally available)
async def run_sync_db_call(func_to_run, *args, **kwargs):
    try:
        return await asyncio.to_thread(func_to_run, *args, **kwargs)
    except AttributeError:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func_to_run(*args, **kwargs))

# Asynchronous versions of sql_emby functions needed
async def sql_add_emby_async(tg: int):
    return await run_sync_db_call(sync_sql_add_emby, tg)

async def sql_update_emby_async(condition, **kwargs):
    return await run_sync_db_call(sync_sql_update_emby, condition, **kwargs)

# --- Invitation Processing Flow ---
async def process_invitation_flow(actual_code: str, new_user_id: int, new_user_first_name: str, message_context):
    """
    Handles the logic for processing an invitation code.
    Returns True if invitation processed (even if points not awarded), False if code invalid/used or self-invite.
    """
    await message_context.delete() # Delete the /start invite_xxxx message

    invitation = await sql_get_invitation_by_code(actual_code)

    if not invitation or invitation.status != 'pending':
        LOGGER.info(f"Invitation code '{actual_code}' invalid or not pending for user {new_user_id}.")
        await sql_add_emby_async(new_user_id) # Ensure basic registration
        await sendPhoto(message_context, bot_photo,
                        f"**✨ 欢迎, {new_user_first_name}!**\n\n"
                        f"您使用的邀请码无效或已被使用。\n"
                        f"已为您完成基本账户设置。\n"
                        f"请点击 /start 重新召唤面板。", timer=60)
        return False

    if invitation.inviter_user_id == new_user_id:
        LOGGER.info(f"User {new_user_id} attempted self-invite with code '{actual_code}'.")
        await sql_add_emby_async(new_user_id) # Ensure basic registration
        await sendPhoto(message_context, bot_photo,
                        f"**✨ 欢迎, {new_user_first_name}!**\n\n"
                        f"您不能使用自己的邀请码进行注册。\n"
                        f"已为您完成基本账户设置。\n"
                        f"请点击 /start 重新召唤面板。", timer=60)
        return False

    # Ensure user record exists in Emby table before trying to update points
    # sql_add_emby_async is idempotent, so calling it is safe.
    await sql_add_emby_async(new_user_id)
    
    money_name = _open.get('money', '积分')
    inviter_points_awarded = 0
    invited_user_points_awarded = 0

    if _open.get("invitation_system_enabled", False):
        # Award Inviter Points
        inviter_points_config = _open.get("invitation_inviter_points", 0)
        if inviter_points_config > 0:
            update_success = await sql_update_emby_async(Emby.tg == invitation.inviter_user_id, iv=Emby.iv + inviter_points_config)
            if update_success:
                inviter_points_awarded = inviter_points_config
                LOGGER.info(f"Awarded {inviter_points_awarded} {money_name} to inviter {invitation.inviter_user_id} for invite code {actual_code}.")
            else:
                LOGGER.error(f"Failed to update points for inviter {invitation.inviter_user_id} for invite code {actual_code}.")
        
        # Award Invited User Points
        invited_user_points_config = _open.get("invitation_invited_user_points", 0)
        if invited_user_points_config > 0:
            update_success = await sql_update_emby_async(Emby.tg == new_user_id, iv=Emby.iv + invited_user_points_config)
            if update_success:
                invited_user_points_awarded = invited_user_points_config
                LOGGER.info(f"Awarded {invited_user_points_awarded} {money_name} to new user {new_user_id} via code {actual_code}.")
            else:
                 LOGGER.error(f"Failed to update points for invited user {new_user_id} for invite code {actual_code}.")
    else:
        LOGGER.info(f"Invitation system disabled. Points not awarded for code {actual_code}.")


    # Mark Invitation Completed
    await sql_mark_invitation_completed(actual_code, new_user_id)
    LOGGER.info(f"Invitation code '{actual_code}' marked as completed by user {new_user_id}.")

    # Send Notifications
    inviter_chat = None
    try:
        inviter_chat = await bot.get_chat(invitation.inviter_user_id)
        if inviter_chat: # Ensure inviter_chat is not None
             await bot.send_message(
                invitation.inviter_user_id,
                f"🎉 恭喜！{new_user_first_name} (ID: `{new_user_id}`) 已通过您的邀请成功注册！\n"
                f"您获得了 **{inviter_points_awarded}** {money_name}."
            )
    except Exception as e:
        LOGGER.error(f"Failed to send notification to inviter {invitation.inviter_user_id}: {e}")

    inviter_display_name = inviter_chat.first_name if inviter_chat and inviter_chat.first_name else f"用户ID {invitation.inviter_user_id}"
    
    welcome_message_to_invited = (
        f"**✨ 欢迎, {new_user_first_name}! ✨**\n\n"
        f"您已通过 **{inviter_display_name}** 的邀请成功注册！\n"
    )
    if invited_user_points_awarded > 0:
        welcome_message_to_invited += f"您获得了 **{invited_user_points_awarded}** {money_name} 作为奖励。\n"
    
    welcome_message_to_invited += "\n已为您完成账户设置。\n请点击 /start 重新召唤或查看您的用户面板。"

    await sendPhoto(message_context, bot_photo, caption=welcome_message_to_invited, timer=120)
    return True
# --- End Invitation Processing Flow ---


# 反命令提示
@bot.on_message((filters.command('start', prefixes) | filters.command('count', prefixes)) & filters.chat(group))
async def ui_g_command(_, msg):
    await asyncio.gather(deleteMessage(msg),
                         sendMessage(msg,
                                     f"🤖 亲爱的 [{msg.from_user.first_name}](tg://user?id={msg.from_user.id}) 这是一条私聊命令",
                                     buttons=group_f, timer=60))


# 查看自己的信息
@bot.on_message(filters.command('myinfo', prefixes) & user_in_group_on_filter)
async def my_info(_, msg):
    await msg.delete()
    if msg.sender_chat:
        return
    text, keyboard = await cr_kk_ikb(uid=msg.from_user.id, first=msg.from_user.first_name)
    await sendMessage(msg, text, timer=60)


@bot.on_message(filters.command('count', prefixes) & user_in_group_on_filter & filters.private)
async def count_info(_, msg):
    await deleteMessage(msg)
    text = Embyservice.get_medias_count()
    await sendMessage(msg, text, timer=60)


# 私聊开启面板
@bot.on_message(filters.command('start', prefixes) & filters.private)
async def p_start(_, msg):
    if not await user_in_group_filter(_, msg):
        return await asyncio.gather(deleteMessage(msg),
                                    sendMessage(msg,
                                                '💢 拜托啦！请先点击下面加入我们的群组和频道，然后再 /start 一下好吗？\n\n'
                                                '⁉️ ps：如果您已在群组中且收到此消息，请联系管理员解除您的权限限制，因为被限制用户无法使用本bot。',
                                                buttons=judge_group_ikb))
    try:
        # Check for invitation code first
        if len(msg.command) > 1 and msg.command[1].startswith("invite_"):
            actual_code = msg.command[1].split("_", 1)[1]
            # process_invitation_flow will handle msg.delete() and further user interaction
            invitation_processed = await process_invitation_flow(actual_code, msg.from_user.id, msg.from_user.first_name, msg)
            if invitation_processed: # If True, invitation flow handled everything including welcome.
                return # Stop further processing in p_start
            # If False, it means code was invalid/used/self-invite, and a message was already sent.
            # The user might need to see the standard panel, so we can fall through or explicitly call it.
            # For now, if it returns False, it means an error/specific message was sent.
            # The user can /start again to get the normal panel.
            return 
            
        # Existing logic for other start parameters
        u = msg.command[1].split('-')[0]
        if u == 'userip':
            name = msg.command[1].split('-')[1]
            if judge_admins(msg.from_user.id):
                return await user_cha_ip(_, msg, name) # This function should handle msg.delete()
            else:
                await msg.delete()
                return await sendMessage(msg, '💢 你不是管理员，无法使用此命令')
        if u in f'{ranks.logo}' or u == str(msg.from_user.id):
            # rgs_code should handle msg.delete()
            await rgs_code(_, msg, register_code=msg.command[1])
            return # Ensure no fall-through
        else:
            # This path implies an unknown /start parameter not matching invite_, userip, or ranks.logo/user_id
            await msg.delete()
            await sendMessage(msg, '🤺 你也想和bot击剑吗 ? (无效的启动参数)')
            return

    except (IndexError, TypeError): # This means /start was called without any parameters
        await msg.delete() # Delete the original /start command
        data = await members_info(tg=msg.from_user.id) # members_info uses sql_get_emby which is sync
        is_admin = judge_admins(msg.from_user.id)
        
        if not data: # User is completely new
            await sql_add_emby_async(msg.from_user.id) # Use async version
            await sendPhoto(msg, bot_photo,
                            f"**✨ 只有你想见我的时候我们的相遇才有意义**\n\n"
                            f"🍉__你好鸭 [{msg.from_user.first_name}](tg://user?id={msg.from_user.id}) \n\n"
                            f"初次使用，录入数据库完成。\n"
                            f"请点击 /start 重新召唤面板", timer=60)
            return

        # User exists, show standard panel
        name, lv, ex, us, embyid, pwd2 = data
        stat, all_user, tem, timing = await open_check()
        # This text is for users who are already registered or have an Emby account
        # If they came via an invite link but were already in DB, the invite flow above would have handled it.
        # This is for /start without params by existing users.
        text = f"▎__欢迎进入用户面板！{msg.from_user.first_name}__\n\n" \
               f"**· 🆔 用户のID** | `{msg.from_user.id}`\n" \
               f"**· 📊 当前状态** | {lv}\n" \
               f"**· 🍒 {money_name}** | {us}\n" \
               f"**· ®️ 注册状态** | {'✅ 开启' if stat else '❎ 关闭'}\n" \
               f"**· 🎫 总注册限制** | {all_user}\n" \
               f"**· 🎟️ 可注册席位** | {all_user - tem if all_user is not None and tem is not None else 'N/A'}\n" # Added None check

        account_exists = bool(embyid) # If embyid exists, they have an Emby account linked.
                                      # If only in 'emby' table via sql_add_emby but no embyid, account_exists is False.
        
        await sendPhoto(msg, bot_photo, caption=text, buttons=judge_start_ikb(is_admin, account_exists), timer=120)


# 返回面板
@bot.on_callback_query(filters.regex('back_start'))
async def b_start(_, call):
    if await user_in_group_filter(_, call):
        is_admin = judge_admins(call.from_user.id)
        await asyncio.gather(callAnswer(call, "⭐ 返回start"),
                             editMessage(call,
                                         text=f"**✨ 只有你想见我的时候我们的相遇才有意义**\n\n🍉__你好鸭 [{call.from_user.first_name}](tg://user?id={call.from_user.id}) 请选择功能__👇",
                                         buttons=judge_start_ikb(is_admin, account=True)))
    elif not await user_in_group_filter(_, call):
        await asyncio.gather(callAnswer(call, "⭐ 返回start"),
                             editMessage(call, text='💢 拜托啦！请先点击下面加入我们的群组和频道，然后再 /start 一下好吗？\n\n'
                                                    '⁉️ ps：如果您已在群组中且收到此消息，请联系管理员解除您的权限限制，因为被限制用户无法使用本bot。',
                                         buttons=judge_group_ikb))


@bot.on_callback_query(filters.regex('store_all'))
async def store_alls(_, call):
    if not await user_in_group_filter(_, call):
        await asyncio.gather(callAnswer(call, "⭐ 返回start"),
                             deleteMessage(call), sendPhoto(call, bot_photo,
                                                            '💢 拜托啦！请先点击下面加入我们的群组和频道，然后再 /start 一下好吗？',
                                                            judge_group_ikb))
    elif await user_in_group_filter(_, call):
        await callAnswer(call, '⭕ 正在编辑', True)
