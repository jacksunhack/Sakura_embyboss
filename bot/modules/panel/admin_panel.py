"""
 admin 面板
 功能暂定 开关注册，生成注册码，查看注册码情况，邀请注册排名情况
"""
import asyncio

from pyrogram import filters

from bot import bot, _open, save_config, bot_photo, LOGGER, bot_name, admins, owner
from bot.func_helper.filters import admins_on_filter
from bot.schemas import ExDate
from bot.sql_helper.sql_code import sql_count_code, sql_count_p_code, sql_delete_all_unused, sql_delete_unused_by_days
from bot.sql_helper.sql_emby import sql_count_emby
# Updated imports to use gm_ikb_content directly and new invitation_settings_ikb
from bot.func_helper.fix_bottons import (
    gm_ikb_content, open_menu_ikb, gog_rester_ikb, back_open_menu_ikb,
    back_free_ikb, re_cr_link_ikb, close_it_ikb, ch_link_ikb, date_ikb,
    cr_paginate, cr_renew_ikb, invite_lv_ikb, back_manage_ikb, # Assuming back_manage_ikb is the standard back button
    invitation_settings_ikb as fb_invitation_settings_ikb # Import with alias to avoid conflict if any local one was planned
)
from bot.func_helper.msg_utils import callAnswer, editMessage, sendPhoto, callListen, deleteMessage, sendMessage
from bot.func_helper.utils import open_check, cr_link_one,rn_link_one


@bot.on_callback_query(filters.regex('manage') & admins_on_filter)
async def gm_ikb(_, call):
    await callAnswer(call, '✔️ manage面板')
    stat, all_user, tem, timing = await open_check()
    stat_str = "✅ 开启" if stat else "❎ 关闭"
    timing_str = '❎ 关闭' if timing == 0 else f'✅ {timing} 分钟'
    tg, emby, white = sql_count_emby()

    # Invitation system settings
    inv_enabled_str = "✅ 开启" if _open.get("invitation_system_enabled", False) else "❎ 关闭"
    inviter_points = _open.get("invitation_inviter_points", 0)
    invited_points = _open.get("invitation_invited_user_points", 0)

    gm_text = f'⚙️ **{bot_name} 管理面板** ⚙️\n\n' \
              f'管理员: {call.from_user.first_name}\n\n' \
              f'💠 **注册设置**:\n' \
              f'  · 自由注册: **{stat_str}**\n' \
              f'  · 定时注册: **{timing_str}**\n' \
              f'  · 总注册限制: **{all_user}**\n' \
              f'  · 已注册 (Emby/白名单): **{emby} / {white}**\n' \
              f'  · Bot 用户总数: **{tg}**\n\n' \
              f'✉️ **邀请系统设置**:\n' \
              f'  · 邀请功能: **{inv_enabled_str}**\n' \
              f'  · 邀请者获得积分: **{inviter_points}**\n' \
              f'  · 被邀请者获得积分: **{invited_points}**'
    
    # Now directly use the imported gm_ikb_content from fix_bottons.py
    # It should already contain the "Invitation Settings" button and a close button if defined there.
    await editMessage(call, gm_text, buttons=gm_ikb_content)

# --- Invitation Settings ---

# Local definition of invitation_settings_ikb is removed.
# fb_invitation_settings_ikb (imported from fix_bottons) will be used.

@bot.on_callback_query(filters.regex('invite_settings_menu') & admins_on_filter)
async def invite_settings_menu_cb(_, call):
    await callAnswer(call, '✉️ 邀请系统设置')
    
    is_enabled = _open.get("invitation_system_enabled", False)
    inviter_points = _open.get("invitation_inviter_points", 0)
    invited_user_points = _open.get("invitation_invited_user_points", 0)
    
    text = f"✉️ **邀请系统设置**\n\n" \
           f"当前状态: {'✅ 已开启' if is_enabled else '❎ 已关闭'}\n" \
           f"邀请者获得积分: **{inviter_points}**\n" \
           f"被邀请者获得积分: **{invited_user_points}**\n\n" \
           f"请选择要修改的选项:"
           
    # Use the imported keyboard function from fix_bottons
    await editMessage(call, text, buttons=fb_invitation_settings_ikb(is_enabled, inviter_points, invited_user_points))

@bot.on_callback_query(filters.regex('toggle_invitation_system') & admins_on_filter)
async def toggle_invitation_system_cb(_, call):
    current_status = _open.get("invitation_system_enabled", False)
    _open["invitation_system_enabled"] = not current_status
    save_config()
    
    new_status_text = "✅ 已开启" if not current_status else "❎ 已关闭"
    await callAnswer(call, f"邀请系统已 {new_status_text.split(' ')[1]}", show_alert=True)
    await invite_settings_menu_cb(_, call) # Refresh the menu

async def set_points_value(call, point_type_key, friendly_name):
    prompt_message = await editMessage(call, 
                                       f"请输入新的 **{friendly_name}** 数值。\n\n"
                                       f"当前值为: {_open.get(point_type_key, 0)}\n"
                                       f"发送 `/cancel` 取消操作。", 
                                       buttons=InlineKeyboardMarkup([[back_manage_ikb.inline_keyboard[0][0]]])) # Use back_manage_ikb

    user_input = await callListen(call, timeout=120)

    if not user_input or not user_input.text:
        await deleteMessage(prompt_message)
        await callAnswer(call, "操作超时或无输入。", show_alert=True)
        return await invite_settings_menu_cb(_, call) # Back to inv menu

    await deleteMessage(user_input) # Delete user's points message
    
    if user_input.text.lower() == '/cancel':
        await deleteMessage(prompt_message)
        await callAnswer(call, "操作已取消。")
        return await invite_settings_menu_cb(_, call)

    try:
        points = int(user_input.text)
        if points < 0:
            await deleteMessage(prompt_message)
            await callAnswer(call, "积分数值不能为负数。", show_alert=True)
            return await invite_settings_menu_cb(_, call)
            
        _open[point_type_key] = points
        save_config()
        await deleteMessage(prompt_message) # Delete the prompt "请输入新的..."
        await callAnswer(call, f"{friendly_name} 已更新为: {points}", show_alert=True)
    except ValueError:
        await deleteMessage(prompt_message)
        await callAnswer(call, "无效的数值。请输入一个整数。", show_alert=True)
    
    await invite_settings_menu_cb(_, call) # Refresh menu

@bot.on_callback_query(filters.regex('set_inviter_points') & admins_on_filter)
async def set_inviter_points_cb(_, call):
    await callAnswer(call, '设置邀请者积分...')
    await set_points_value(call, "invitation_inviter_points", "邀请者积分")

@bot.on_callback_query(filters.regex('set_invited_user_points') & admins_on_filter)
async def set_invited_user_points_cb(_, call):
    await callAnswer(call, '设置被邀请者积分...')
    await set_points_value(call, "invitation_invited_user_points", "被邀请者积分")

# --- End Invitation Settings ---


# 开关注册
@bot.on_callback_query(filters.regex('open-menu') & admins_on_filter)
async def open_menu(_, call):
    await callAnswer(call, '®️ register面板')
    # [开关，注册总数，定时注册] 此间只对emby表中tg用户进行统计
    stat, all_user, tem, timing = await open_check()
    tg, emby, white = sql_count_emby()
    openstats = '✅' if stat else '❎'  # 三元运算
    timingstats = '❎' if timing == 0 else '✅'
    text = f'⚙ **注册状态设置**：\n\n- 自由注册即定量方式，定时注册既定时又定量，将自动转发消息至群组，再次点击按钮可提前结束并报告。\n' \
           f'- **注册总人数限制 {all_user}**'
    await editMessage(call, text, buttons=open_menu_ikb(openstats, timingstats))
    if tem != emby:
        _open.tem = emby
        save_config()


@bot.on_callback_query(filters.regex('open_stat') & admins_on_filter)
async def open_stats(_, call):
    stat, all_user, tem, timing = await open_check()
    if timing != 0:
        return await callAnswer(call, "🔴 目前正在运行定时注册。\n无法调用，请再次点击，【定时注册】关闭状态", True)

    tg, emby, white = sql_count_emby()
    if stat:
        _open.stat = False
        save_config()
        await callAnswer(call, "🟢【自由注册】\n\n已结束", True)
        sur = all_user - tem
        text = f'🫧 管理员 {call.from_user.first_name} 已关闭 **自由注册**\n\n' \
               f'🎫 总注册限制 | {all_user}\n🎟️ 已注册人数 | {tem}\n' \
               f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}'
        await asyncio.gather(sendPhoto(call, photo=bot_photo, caption=text, send=True),
                             editMessage(call, text, buttons=back_free_ikb))
        # await open_menu(_, call)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 关闭了自由注册")
    elif not stat:
        _open.stat = True
        save_config()
        await callAnswer(call, "🟡【自由注册】\n\n已开启", True)
        sur = all_user - tem  # for i in group可以多个群组用，但是现在不做
        text = f'🫧 管理员 {call.from_user.first_name} 已开启 **自由注册**\n\n' \
               f'🎫 总注册限制 | {all_user}\n🎟️ 已注册人数 | {tem}\n' \
               f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}'
        await asyncio.gather(sendPhoto(call, photo=bot_photo, caption=text, buttons=gog_rester_ikb(), send=True),
                             editMessage(call, text=text, buttons=back_free_ikb))
        # await open_menu(_, call)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 开启了自由注册，总人数限制 {all_user}")


change_for_timing_task = None


@bot.on_callback_query(filters.regex('open_timing') & admins_on_filter)
async def open_timing(_, call):
    global change_for_timing_task
    if _open.timing == 0:
        await callAnswer(call, '⭕ 定时设置')
        await editMessage(call,
                          "🦄【定时注册】 \n\n- 请在 120s 内发送 [定时时长] [总人数]\n"
                          "- 形如：`30 50` 即30min，总人数限制50\n"
                          "- 如需要关闭定时注册，再次点击【定时注册】\n"
                          "- 设置好之后将发送置顶消息注意权限\n- 退出 /cancel")

        txt = await callListen(call, 120, buttons=back_open_menu_ikb)
        if txt is False:
            return

        await txt.delete()
        if txt.text == '/cancel':
            return await open_menu(_, call)

        try:
            new_timing, new_all_user = txt.text.split()
            _open.timing = int(new_timing)
            _open.all_user = int(new_all_user)
            _open.stat = True
            save_config()
        except ValueError:
            await editMessage(call, "🚫 请检查数字填写是否正确。\n`[时长min] [总人数]`", buttons=back_open_menu_ikb)
        else:
            tg, emby, white = sql_count_emby()
            sur = _open.all_user - emby
            await asyncio.gather(sendPhoto(call, photo=bot_photo,
                                           caption=f'🫧 管理员 {call.from_user.first_name} 已开启 **定时注册**\n\n'
                                                   f'⏳ 可持续时间 | **{_open.timing}** min\n'
                                                   f'🎫 总注册限制 | {_open.all_user}\n🎟️ 已注册人数 | {emby}\n'
                                                   f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}',
                                           buttons=gog_rester_ikb(), send=True),
                                 editMessage(call,
                                             f"®️ 好，已设置**定时注册 {_open.timing} min 总限额 {_open.all_user}**",
                                             buttons=back_free_ikb))
            LOGGER.info(
                f"【admin】-定时注册：管理员 {call.from_user.first_name} 开启了定时注册 {_open.timing} min，人数限制 {sur}")
            # 创建一个异步任务并保存为变量，并给它一个名字
            change_for_timing_task = asyncio.create_task(
                change_for_timing(_open.timing, call.from_user.id, call), name='change_for_timing')

    else:
        try:
            # 遍历所有的异步任务，找到'change_for_timing'，取消
            for task in asyncio.all_tasks():
                if task.get_name() == 'change_for_timing':
                    change_for_timing_task = task
                    break
            change_for_timing_task.cancel()
        except AttributeError:
            pass
        else:
            await callAnswer(call, "Ⓜ️【定时任务运行终止】\n\n**已为您停止**", True)
            await open_menu(_, call)


async def change_for_timing(timing, tgid, call):
    a = _open.tem
    timing = timing * 60
    try:
        await asyncio.sleep(timing)
    except asyncio.CancelledError:
        pass
    finally:
        _open.timing = 0
        _open.stat = False
        save_config()
        b = _open.tem - a
        s = _open.all_user - _open.tem
        text = f'⏳** 注册结束**：\n\n🍉 目前席位：{_open.tem}\n🥝 新增席位：{b}\n🍋 剩余席位：{s}'
        send = await sendPhoto(call, photo=bot_photo, caption=text, timer=300, send=True)
        send1 = await send.forward(tgid)
        LOGGER.info(f'【admin】-定时注册：运行结束，本次注册 目前席位：{_open.tem}  新增席位:{b}  剩余席位：{s}')
        await deleteMessage(send1, 30)


@bot.on_callback_query(filters.regex('all_user_limit') & admins_on_filter)
async def open_all_user_l(_, call):
    await callAnswer(call, '⭕ 限制人数')
    send = await call.message.edit(
        "🦄 请在 120s 内发送开注总人数，本次修改不会对注册状态改动，如需要开注册请点击打开自由注册\n**注**：总人数满自动关闭注册 取消 /cancel")
    if send is False:
        return

    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    elif txt.text == "/cancel":
        await txt.delete()
        return await open_menu(_, call)

    try:
        await txt.delete()
        a = int(txt.text)
    except ValueError:
        await editMessage(call, f"❌ 八嘎，请输入一个数字给我。", buttons=back_free_ikb)
    else:
        _open.all_user = a
        save_config()
        await editMessage(call, f"✔️ 成功，您已设置 **注册总人数 {a}**", buttons=back_free_ikb)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 调整了总人数限制：{a}")
@bot.on_callback_query(filters.regex('open_us') & admins_on_filter)
async def open_us(_, call):
    await callAnswer(call, '🤖开放账号天数')
    send = await call.message.edit(
        "🦄 请在 120s 内发送开放注册时账号的有效天数，本次修改不会对注册状态改动，如需要开注册请点击打开自由注册\n**注**：总人数满自动关闭注册 取消 /cancel")
    if send is False:
        return

    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    elif txt.text == "/cancel":
        await txt.delete()
        return await open_menu(_, call)

    try:
        await txt.delete()
        a = int(txt.text)
    except ValueError:
        await editMessage(call, f"❌ 八嘎，请输入一个数字给我。", buttons=back_free_ikb)
    else:
        _open.open_us = a
        save_config()
        await editMessage(call, f"✔️ 成功，您已设置 **开放注册时账号的有效天数 {a}**", buttons=back_free_ikb)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 调整了开放注册时账号的有效天数：{a}")

# 生成注册链接
@bot.on_callback_query(filters.regex('cr_link') & admins_on_filter)
async def cr_link(_, call):
    await callAnswer(call, '✔️ 创建注册/续期码')
    send = await editMessage(call,
                             f'🎟️ 请回复创建 [天数] [数量] [模式] [续期]\n\n'
                             f'**天数**：月30，季90，半年180，年365\n'
                             f'**模式**： link -深链接 | code -码\n'
                             f'**续期**： F - 注册码，T - 续期码\n'
                             f'**示例**：`30 1 link T` 记作 30天一条续期深链接\n'
                             f'__取消本次操作，请 /cancel__')
    if send is False:
        return

    content = await callListen(call, 120, buttons=re_cr_link_ikb)
    if content is False:
        return
    elif content.text == '/cancel':
        await content.delete()
        return await editMessage(call, '⭕ 您已经取消操作了。', buttons=re_cr_link_ikb)
    try:
        await content.delete()
        times, count, method, renew = content.text.split()
        count = int(count)
        days = int(times)
        if method != 'code' and method != 'link':
            return editMessage(call, '⭕ 输入的method参数有误', buttons=re_cr_link_ikb)
    except (ValueError, IndexError):
        return await editMessage(call, '⚠️ 检查输入，有误。', buttons=re_cr_link_ikb)
    else:
        if renew == 'F':
            links = await cr_link_one(call.from_user.id, times, count, days, method)
            if links is None:
                return await editMessage(call, '⚠️ 数据库插入失败，请检查数据库。', buttons=re_cr_link_ikb)
            links = f"🎯 {bot_name}已为您生成了 **{days}天** 注册码 {count} 个\n\n" + links
            chunks = [links[i:i + 4096] for i in range(0, len(links), 4096)]
            for chunk in chunks:
                await sendMessage(content, chunk, buttons=close_it_ikb)
            await editMessage(call, f'📂 {bot_name}已为 您 生成了 {count} 个 {days} 天注册码', buttons=re_cr_link_ikb)
            LOGGER.info(f"【admin】：{bot_name}已为 {content.from_user.id} 生成了 {count} 个 {days} 天注册码")

        else:
            links = await rn_link_one(call.from_user.id, times, count, days, method)
            if links is None:
                return await editMessage(call, '⚠️ 数据库插入失败，请检查数据库。', buttons=re_cr_link_ikb)
            links = f"🎯 {bot_name}已为您生成了 **{days}天** 续期码 {count} 个\n\n" + links
            chunks = [links[i:i + 4096] for i in range(0, len(links), 4096)]
            for chunk in chunks:
                await sendMessage(content, chunk, buttons=close_it_ikb)
            await editMessage(call, f'📂 {bot_name}已为 您 生成了 {count} 个 {days} 天续期码', buttons=re_cr_link_ikb)
            LOGGER.info(f"【admin】：{bot_name}已为 {content.from_user.id} 生成了 {count} 个 {days} 天续期码")


# 检索
@bot.on_callback_query(filters.regex('ch_link') & admins_on_filter)
async def ch_link(_, call):
    await callAnswer(call, '🔍 查看管理们注册码...时长会久一点', True)
    a, b, c, d, f, e = sql_count_code()
    text = f'**🎫 常用code数据：\n• 已使用 - {a}  | • 未使用 - {e}\n• 月码 - {b}   | • 季码 - {c} \n• 半年码 - {d}  | • 年码 - {f}**'
    ls = []
    admins.append(owner)
    for i in admins:
        name = await bot.get_chat(i)
        a, b, c, d, f ,e= sql_count_code(i)
        text += f'\n👮🏻`{name.first_name}`: 月/{b}，季/{c}，半年/{d}，年/{f}，已用/{a}，未用/{e}'
        f = [f"🔎 {name.first_name}", f"ch_admin_link-{i}"]
        ls.append(f)
    ls.append(["🚮 删除未使用码", f"delete_codes"])
    admins.remove(owner)
    keyboard = ch_link_ikb(ls)
    text += '\n详情查询 👇'

    await editMessage(call, text, buttons=keyboard)

# 删除未使用码
@bot.on_callback_query(filters.regex('delete_codes') & admins_on_filter)
async def delete_unused_codes(_, call):
    await callAnswer(call, '⚠️ 请确认要删除码的类别')
    if call.from_user.id != owner:
        return await callAnswer(call, '🚫 不可以哦！ 你又不是owner', True)
    
    await editMessage(call, 
        "请回复要删除的未使用码天数类别，多个天数用空格分隔\n"
        "例如: `5 30 180` 将删除属于5天、30天和180天类别的未使用码\n"
        "输入 `all` 删除所有未使用码\n"
        "取消请输入 /cancel")
    
    content = await callListen(call, 120)
    if content is False:
        return
    elif content.text == '/cancel':
        await content.delete()
        return await gm_ikb(_, call)
        
    try:
        if content.text.lower() == 'all':
            count = sql_delete_all_unused()
            text = f"已删除所有未使用码，共 {count} 个"
        else:
            days = [int(x) for x in content.text.split()]
            count = sql_delete_unused_by_days(days)
            text = f"已删除指定天数的未使用码，共 {count} 个"
        await content.delete()
    except ValueError:
        text = "❌ 输入格式错误"
    
    ls=[]
    ls.append(["🔄 继续删除", f"delete_codes"])
    keyboard = ch_link_ikb(ls)
    await editMessage(call, text, buttons=keyboard)


@bot.on_callback_query(filters.regex('ch_admin_link'))
async def ch_admin_link(client, call):
    i = int(call.data.split('-')[1])
    if call.from_user.id != owner and call.from_user.id != i:
        return await callAnswer(call, '🚫 你怎么偷窥别人呀! 你又不是owner', True)
    await callAnswer(call, f'💫 管理员 {i} 的注册码')
    a, b, c, d, f, e= sql_count_code(i)
    name = await client.get_chat(i)
    text = f'**🎫 [{name.first_name}-{i}](tg://user?id={i})：\n• 已使用 - {a}  | • 未使用 - {e}\n• 月码 - {b}    | • 季码 - {c} \n• 半年码 - {d}  | • 年码 - {f}**'
    await editMessage(call, text, date_ikb(i))


@bot.on_callback_query(
    filters.regex('register_mon') | filters.regex('register_sea')
    | filters.regex('register_half') | filters.regex('register_year') | filters.regex('register_used') | filters.regex('register_unused'))
async def buy_mon(_, call):
    await call.answer('✅ 显示注册码')
    cd, times, u = call.data.split('_')
    n = getattr(ExDate(), times)
    a, i = sql_count_p_code(u, n)
    if a is None:
        x = '**空**'
    else:
        x = a[0]
    first = await bot.get_chat(u)
    keyboard = await cr_paginate(i, 1, n)
    await sendMessage(call, f'🔎当前 {first.first_name} - **{n}**天，检索出以下 **{i}**页：\n\n{x}', keyboard)


# 检索翻页
@bot.on_callback_query(filters.regex('pagination_keyboard'))
async def paginate_keyboard(_, call):
    j, mode = map(int, call.data.split(":")[1].split('_'))
    await callAnswer(call, f'好的，将为您翻到第 {j} 页')
    a, b = sql_count_p_code(call.from_user.id, mode)
    keyboard = await cr_paginate(b, j, mode)
    text = a[j-1]
    await editMessage(call, f'🔎当前模式- **{mode}**天，检索出以下 **{b}**页链接：\n\n{text}', keyboard)


@bot.on_callback_query(filters.regex('set_renew'))
async def set_renew(_, call):
    await callAnswer(call, '🚀 进入续期设置')
    try:
        method = call.data.split('-')[1]
            # Make sure _open is a dict-like object that supports .get and item assignment
            current_value = _open.get(method, False) # Assuming boolean toggle for these specific old methods
            _open[method] = not current_value
        save_config()
        except (IndexError, AttributeError, KeyError) as e: # Added AttributeError for _open.get if not dict-like, KeyError
            LOGGER.error(f"Error in set_renew callback: {e}. Method: {method}")
            pass # Keep original behavior of silently passing
    finally:
            # This message might need to be re-evaluated if `method` isn't what `cr_renew_ikb` expects
        await editMessage(call, text='⭕ **关于用户组的续期功能**\n\n选择点击下方按钮开关任意兑换功能',
                              buttons=cr_renew_ikb()) # cr_renew_ikb might need _open passed to it or to fetch config itself

@bot.on_callback_query(filters.regex('set_invite_lv'))
async def invite_lv_set(_, call):
    try:
        method = call.data
        current_invite_lv = _open.get('invite_lv', 'a') # Default to 'a' if not set

        if method.startswith('set_invite_lv-'):
            level = method.split('-')[1]
            if level in ['a', 'b', 'c', 'd']:
                _open['invite_lv'] = level
                save_config()
                await callAnswer(call, f'✅ 已设置邀请等级为 {level.upper()}', show_alert=True)
                current_invite_lv = level # Update for immediate display
        
        await callAnswer(call, '🚀 进入邀请等级设置')
        await editMessage(call, 
            "请选择邀请等级:\n\n"
            f"当前等级: **{current_invite_lv.upper()}**\n\n"
            "🅰️ - 白名单可使用\n"
            "🅱️ - 注册用户可使用\n" 
            "🇨 - 已禁用用户可使用\n" # Typo: ©️ vs 🇨
            "🇩 - 无账号用户可使用", # Typo: 🅳️ vs 🇩
            buttons=invite_lv_ikb(current_invite_lv)) # Pass current_invite_lv to highlight correctly
        return
    except (IndexError, AttributeError, KeyError) as e: # Added AttributeError for _open.get, KeyError
        LOGGER.error(f"Error in invite_lv_set callback: {e}")
        pass
