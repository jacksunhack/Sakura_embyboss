# -*- coding: utf-8 -*-
"""
Handles /getinvite and /myinvites commands for user invitations.
"""
import secrets
import asyncio

from pyrogram import filters

from bot import bot, LOGGER, _open, bot_name, config # Assuming config.COMMAND_PREFIXES
from bot.sql_helper.sql_invitations import sql_add_invitation, sql_invitation_code_exists, sql_get_successful_invites_count # Import new function
from bot.sql_helper.sql_emby import sql_get_emby # To fetch user's Emby level
from bot.func_helper.filters import user_in_group_on_filter # Or any other relevant filter

COMMAND_PREFIXES = config.COMMAND_PREFIXES if hasattr(config, 'COMMAND_PREFIXES') else "/"


@bot.on_message(filters.command("getinvite", prefixes=COMMAND_PREFIXES) & user_in_group_on_filter)
async def get_invite_link_command(client, message):
    """
    Handles the /getinvite command.
    Generates a unique invitation link for the user if they meet the criteria.
    """
    user_id = message.from_user.id

    if not _open.get("invitation_system_enabled", False):
        await message.reply("⚠️ The invitation system is currently disabled. Please try again later or contact an admin.")
        return

    # Permission Check based on _open.invite_lv
    required_invite_level_setting = _open.get("invite_lv", "b").lower()  # Default to 'b' (registered users) if not set
    
    emby_user = await asyncio.to_thread(sql_get_emby, user_id) # sql_get_emby is sync
    
    user_actual_level_char = 'd' # Default for non-registered/non-emby users
    if emby_user and hasattr(emby_user, 'lv') and emby_user.lv:
        user_actual_level_char = emby_user.lv.lower()
        if user_actual_level_char == '**已禁用**': # Specific string for banned users
             user_actual_level_char = 'c' # Map to 'c' for permission check
    elif emby_user: # User exists in emby table but might not have 'lv' or it's None/empty
        # This case might imply a regular registered user, map to 'b'
        # Or if 'lv' is crucial, treat as 'd'. For now, assume 'b' if emby_user record exists.
        user_actual_level_char = 'b' 

    # Permission mapping: Who can invite whom?
    # 'a': Only 'a' (whitelist) can invite.
    # 'b': 'a' and 'b' (registered users) can invite.
    # 'c': 'a', 'b', 'c' (even banned users, though this might be rare for inviting) can invite.
    # 'd': Anyone, including users not in Emby DB, can invite.
    
    allowed_to_invite = False
    if required_invite_level_setting == 'a': # Only whitelisted can invite
        if user_actual_level_char == 'a':
            allowed_to_invite = True
    elif required_invite_level_setting == 'b': # Whitelisted and Registered users can invite
        if user_actual_level_char in ['a', 'b']:
            allowed_to_invite = True
    elif required_invite_level_setting == 'c': # Whitelisted, Registered, and even "Banned" users can invite
        if user_actual_level_char in ['a', 'b', 'c']:
            allowed_to_invite = True
    elif required_invite_level_setting == 'd': # Anyone can invite
        allowed_to_invite = True
    else: # Default restrictive behavior if invite_lv is misconfigured
        LOGGER.warning(f"Unknown 'invite_lv' setting: {required_invite_level_setting}. Defaulting to restrictive.")
        allowed_to_invite = False

    if not allowed_to_invite:
        permission_denied_message = "🚫 You do not have the required permission level to generate invitation links.\n"
        if required_invite_level_setting == 'a':
            permission_denied_message += "Only whitelisted users (Level A) can generate invites."
        elif required_invite_level_setting == 'b':
            permission_denied_message += "Only registered users (Level A or B) can generate invites."
        elif required_invite_level_setting == 'c':
             permission_denied_message += "Invitation generation is restricted. Please contact an admin." # Generic for 'c'
        else: # Should not happen if logic is correct, but as a fallback
             permission_denied_message += "Please contact an admin about invitation permissions."
        await message.reply(permission_denied_message)
        return

    # Generate Unique Code
    invitation_code = ""
    for _ in range(10): # Try up to 10 times to find a unique code
        temp_code = secrets.token_hex(6)  # 12-character hex string
        if not await sql_invitation_code_exists(temp_code): # Uses the async version
            invitation_code = temp_code
            break
    
    if not invitation_code:
        LOGGER.error(f"Failed to generate a unique invitation code after 10 attempts for user {user_id}.")
        await message.reply("🚫 Could not generate a unique invitation code at this time. Please try again in a moment.")
        return

    # Store Invitation
    success = await sql_add_invitation(invitation_code, user_id) # Uses the async version
    if not success:
        LOGGER.error(f"Database error: Failed to store invitation code '{invitation_code}' for user {user_id}.")
        await message.reply("🚫 An error occurred while saving your invitation code. Please try again.")
        return

    # Send Link to User
    invite_link = f"https.t.me/{bot_name}?start=invite_{invitation_code}"
    reply_text = (
        f"🎉 Your unique invitation link has been generated!\n\n"
        f"🔗 **Link:** {invite_link}\n\n"
        f"Share this link with someone you want to invite. "
        f"When they register using this link:\n"
        f"- You will receive **{_open.get('invitation_inviter_points', 0)}** points.\n"
        f"- They will receive **{_open.get('invitation_invited_user_points', 0)}** points upon successful registration.\n\n"
        f"*(Note: Invitation codes are for one-time use.)*"
    )
    
    try:
        await message.reply(reply_text, disable_web_page_preview=True)
        LOGGER.info(f"User {user_id} generated invitation code: {invitation_code}")
    except Exception as e:
        LOGGER.error(f"Failed to send invitation link to user {user_id}: {e}")
        await message.reply("🚫 Could not send your invitation link. Please try generating it again.")


@bot.on_message(filters.command("myinvites", prefixes=COMMAND_PREFIXES) & user_in_group_on_filter)
async def my_invites_command(client, message):
    """
    Handles the /myinvites command.
    Shows the user their invitation statistics.
    """
    user_id = message.from_user.id

    if not _open.get("invitation_system_enabled", False):
        await message.reply("⚠️ The invitation system is currently disabled.")
        return

    successful_invites_count = await sql_get_successful_invites_count(user_id)
    
    inviter_points_config = _open.get("invitation_inviter_points", 0)
    money_name = _open.get('money', '积分')
    
    reply_text = f"📊 **您的邀请统计** 📊\n\n"
    reply_text += f"您已成功邀请了 **{successful_invites_count}** 位用户。\n"
    
    if inviter_points_config > 0:
        total_earned_points = successful_invites_count * inviter_points_config
        reply_text += f"通过邀请，您总共获得了 **{total_earned_points}** {money_name}。\n"
    
    reply_text += "\n您可以使用 `/getinvite` 命令来获取新的邀请链接。"
    
    await message.reply(reply_text)


# Ensure sql_get_emby is also wrapped if it's synchronous and called often,
# or ensure it's efficient enough not to block significantly.
# For now, asyncio.to_thread is used for its call.

LOGGER.info("SakuraEmbyManager: Invitation Command Module loaded (/getinvite, /myinvites).")
