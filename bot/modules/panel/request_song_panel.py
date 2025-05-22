# -*- coding: utf-8 -*-
"""
Panel for requesting songs via Navidrome.
"""
import asyncio
from io import BytesIO

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot import bot, LOGGER, config
from bot.func_helper.navidrome import navidrome_api
from bot.func_helper.msg_utils import (
    sendMessage, 
    editMessage, 
    deleteMessage,
    sendPhoto, 
    callAnswer, 
    callListen,
    auto_delete_message
)
from bot.func_helper.filters import user_in_group_on_filter # Assuming similar filter as movie panel
from bot.func_helper.fix_bottons import বাট<y_bin_725> # For button creation, assuming this is the button helper

# --- Constants ---
ITEMS_PER_PAGE = 5 # Number of items (songs/albums) to display per page
SONG_SEARCH_TIMEOUT = 120 # seconds for the search interaction to timeout

# --- State Management ---
# Stores user-specific search state: {user_id: {"query": str, "page": int, "results": dict, "message_id": int, "type": "song"/"album"/"artist"}}
user_song_search_data = {}

# --- Helper Functions ---
async def cleanup_user_search_state(user_id):
    """Clears search state for a user."""
    if user_id in user_song_search_data:
        del user_song_search_data[user_id]
        LOGGER.info(f"Navidrome Panel: Cleaned up search state for user {user_id}")

def format_song_details(song):
    title = song.get('title', 'N/A')
    artist = song.get('artist', 'N/A')
    album = song.get('album', 'N/A')
    duration = song.get('duration', 0)
    minutes = duration // 60
    seconds = duration % 60
    return f"🎵 **{title}**\n   🎤 Artist: {artist}\n   💿 Album: {album}\n   ⏱ Duration: {minutes}:{seconds:02d}"

def format_album_details(album):
    title = album.get('name', album.get('title', 'N/A')) # Navidrome uses 'name' for album in searchResult3, 'title' in getAlbum
    artist = album.get('artist', 'N/A')
    song_count = album.get('songCount', 'N/A')
    year = album.get('year', 'N/A')
    return f"💿 **{title}**\n   🎤 Artist: {artist}\n   🗓 Year: {year}\n   🎶 Songs: {song_count}"

def format_artist_details(artist):
    name = artist.get('name', 'N/A')
    album_count = artist.get('albumCount', 'N/A') # from getArtists
    # SearchResult3 for artist doesn't have albumCount, may need separate getArtist call if detailed info needed here
    return f"🎤 **{name}**"


# --- Main Command Handler ---
@bot.on_message(filters.command(["song", "requestsong"], prefixes=config.COMMAND_PREFIXES) & user_in_group_on_filter)
async def start_song_request_cmd(_, message):
    """
    Handles the /song command to initiate a song search.
    """
    user_id = message.from_user.id

    if not navidrome_api:
        await sendMessage(message, "⚠️ Navidrome service is not configured or available. Please contact an admin.")
        return

    # Cleanup previous search state for the user, if any
    await cleanup_user_search_state(user_id)

    text = "🎶 **Song Search** 🎶\n\nPlease send me the name of the song, album, or artist you're looking for."
    
    # Ask for search query
    q = await callListen(message, text, timeout=SONG_SEARCH_TIMEOUT)
    if q.isTimeout:
        await sendMessage(message, "Song search timed out. Please try again.")
        return
    if not q.text: # User sent cancel or something weird
        await deleteMessage(q) # Delete the prompt message
        return
    
    query_text = q.text.strip()
    await deleteMessage(q) # Delete the prompt message asking for query

    # Store initial search state
    user_song_search_data[user_id] = {
        "query": query_text,
        "page": 1,
        "results": None, # Will be populated by display_search_results
        "message_id": None, # Will be set by display_search_results
        "search_type": "all" # Default search type: "all", "song", "album", "artist"
    }

    # Show "Searching..." message
    searching_msg = await sendMessage(message, f"🔎 Searching Navidrome for: `{query_text}`...")
    
    await display_song_search_results(message, user_id, initial_search_msg_id=searching_msg.id)


# --- Display Search Results ---
async def display_song_search_results(original_message_or_call, user_id, initial_search_msg_id=None):
    """
    Fetches search results from Navidrome and displays them to the user.
    Manages pagination and inline keyboards.
    """
    if user_id not in user_song_search_data:
        errmsg = "Search session expired or not found. Please start a new search."
        if isinstance(original_message_or_call, CallbackQuery):
            await callAnswer(original_message_or_call, errmsg, alert=True)
        else:
            await sendMessage(original_message_or_call, errmsg)
        return

    state = user_song_search_data[user_id]
    query = state["query"]
    page = state["page"]
    search_type = state.get("search_type", "all") # song, album, artist, all

    # Fetch results from Navidrome
    # For simplicity, search3 is used. It returns artists, albums, songs.
    # We can filter display based on search_type state if user chooses later.
    raw_results = await navidrome_api.search3(query=query, song_count=25, album_count=15, artist_count=10)

    if not raw_results or raw_results.get("status") == "failed" or "subsonic-response" not in raw_results:
        error_msg = raw_results.get("error", "Failed to fetch results from Navidrome.")
        LOGGER.error(f"Navidrome search failed for query '{query}': {error_msg}")
        msg_content = f"⚠️ Error searching Navidrome: {error_msg}\nPlease try again later."
        if initial_search_msg_id:
             await editMessage(original_message_or_call.chat.id, initial_search_msg_id, msg_content)
        elif isinstance(original_message_or_call, CallbackQuery):
            await editMessage(original_message_or_call.message, msg_content)
        else: # Should be original message
            await sendMessage(original_message_or_call, msg_content)
        await cleanup_user_search_state(user_id)
        return

    search_result_data = raw_results.get("subsonic-response", {}).get("searchResult3", {})
    state["results"] = search_result_data # Store full results

    songs = search_result_data.get("song", [])
    albums = search_result_data.get("album", [])
    artists = search_result_data.get("artist", [])
    
    # Filter based on search_type
    display_items = []
    current_item_type_name = "Results"

    if search_type == "song":
        display_items = songs
        current_item_type_name = "Songs"
    elif search_type == "album":
        display_items = albums
        current_item_type_name = "Albums"
    elif search_type == "artist":
        display_items = artists
        current_item_type_name = "Artists"
    else: # "all" - for now, let's prioritize songs, then albums. Artists listed separately.
        # This part can be more sophisticated. For now, just pick one for primary display.
        if songs:
            display_items = songs
            current_item_type_name = "Songs"
            state["current_display_type"] = "song" # Track what's being paginated
        elif albums:
            display_items = albums
            current_item_type_name = "Albums"
            state["current_display_type"] = "album"
        elif artists:
            display_items = artists # Less likely to be primary if songs/albums exist
            current_item_type_name = "Artists"
            state["current_display_type"] = "artist"
        else: # No results in any category
            msg_content = f"🤷 No results found for `{query}` on Navidrome."
            if initial_search_msg_id:
                await editMessage(original_message_or_call.chat.id, initial_search_msg_id, msg_content)
            elif isinstance(original_message_or_call, CallbackQuery): # from original_message_or_call.message
                 await editMessage(original_message_or_call.message, msg_content)
            else:
                 await sendMessage(original_message_or_call, msg_content)
            await cleanup_user_search_state(user_id)
            return

    # Pagination for the primary display_items
    total_items = len(display_items)
    start_index = (page - 1) * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    paginated_items = display_items[start_index:end_index]

    # --- Build Message Content ---
    text = f"🎶 **Navidrome Search Results for:** `{query}`\n"
    text += f"Displaying **{current_item_type_name}** (Page {page} of {((total_items -1) // ITEMS_PER_PAGE) + 1})\n\n"

    buttons = []
    if not paginated_items and page == 1: # No items of the current display type
        text += f"No {current_item_type_name.lower()} found for this query.\n"
    
    for i, item in enumerate(paginated_items):
        item_id = item.get('id')
        item_type_short = state.get("current_display_type", "song") # song, album, artist

        if item_type_short == "song":
            text += f"{start_index + i + 1}. {format_song_details(item)}\n\n"
            buttons.append([InlineKeyboardButton(f"▶️ {item.get('title', 'N/A')[:30]}", callback_data=f"song_view_{user_id}_{item_type_short}_{item_id}")])
        elif item_type_short == "album":
            text += f"{start_index + i + 1}. {format_album_details(item)}\n\n"
            buttons.append([InlineKeyboardButton(f"💿 {item.get('name', 'N/A')[:30]}", callback_data=f"song_view_{user_id}_{item_type_short}_{item_id}")])
        elif item_type_short == "artist": # Artists usually don't have direct 'view' with cover art in this simple list
            text += f"{start_index + i + 1}. {format_artist_details(item)}\n\n"
            # No specific action button for artist in this iteration, could list their albums.

    # --- Pagination Buttons ---
    pagination_buttons = []
    if page > 1:
        pagination_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"song_page_prev_{user_id}"))
    if end_index < total_items:
        pagination_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"song_page_next_{user_id}"))
    
    if pagination_buttons:
        buttons.append(pagination_buttons)

    # --- Filter Buttons (if in "all" mode and other results exist) ---
    # This is a simplified filter. A more robust one might change state["search_type"]
    # and re-call display_song_search_results.
    filter_buttons = []
    current_display = state.get("current_display_type")
    if search_type == "all": # Only show filter if initial search was 'all'
        if songs and current_display != "song":
            filter_buttons.append(InlineKeyboardButton("🎵 Show Songs", callback_data=f"song_filter_{user_id}_song"))
        if albums and current_display != "album":
            filter_buttons.append(InlineKeyboardButton("💿 Show Albums", callback_data=f"song_filter_{user_id}_album"))
        if artists and current_display != "artist":
            filter_buttons.append(InlineKeyboardButton("🎤 Show Artists", callback_data=f"song_filter_{user_id}_artist"))
    
    if filter_buttons:
        buttons.append(filter_buttons)


    buttons.append([InlineKeyboardButton("❌ Cancel Search", callback_data=f"song_search_cancel_{user_id}")])
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    # --- Send / Edit Message ---
    # Attempt to send cover art for the first item if it's a song or album
    # This is done only once per display, not on pagination for now to reduce spam
    # and only if it's the first page of that item type.
    cover_art_id_to_fetch = None
    photo_to_send = None

    if page == 1 and paginated_items:
        first_item = paginated_items[0]
        item_type = state.get("current_display_type")
        if item_type in ["song", "album"]:
            cover_art_id_to_fetch = first_item.get('coverArt', first_item.get('id') if item_type == "album" else None) # Songs might use album's cover ID
            if item_type == "song" and not cover_art_id_to_fetch: # If song has no direct coverArt, try its albumId for cover
                cover_art_id_to_fetch = first_item.get('albumId')

    if cover_art_id_to_fetch:
        LOGGER.info(f"Attempting to fetch cover art ID: {cover_art_id_to_fetch} for item type: {item_type}")
        image_bytes = await navidrome_api.get_cover_art(cover_id=cover_art_id_to_fetch, size=300) # size can be adjusted
        if image_bytes:
            photo_to_send = BytesIO(image_bytes)
            photo_to_send.name = f"cover_{cover_art_id_to_fetch}.png"
    
    chat_id = original_message_or_call.chat.id if not isinstance(original_message_or_call, CallbackQuery) else original_message_or_call.message.chat.id

    if initial_search_msg_id: # This is the first display after "Searching..."
        await deleteMessage(chat_id, initial_search_msg_id) # Delete "Searching..."
        if photo_to_send:
            sent_msg = await sendPhoto(
                chat_id=chat_id,
                photo=photo_to_send,
                caption=text,
                reply_markup=reply_markup
            )
        else:
            sent_msg = await sendMessage(original_message_or_call, text, reply_markup=reply_markup)
        user_song_search_data[user_id]["message_id"] = sent_msg.id
    
    elif isinstance(original_message_or_call, CallbackQuery): # Subsequent updates (pagination, filter)
        # Don't resend photo on simple pagination for now, just edit text.
        # If we wanted to change photo based on selected item, logic would be more complex.
        try:
            # If current message is a photo, edit caption, else edit text
            current_msg = original_message_or_call.message
            if current_msg.photo and photo_to_send: # If we want to update photo on filter
                 await deleteMessage(current_msg) # Delete old photo message
                 new_msg = await sendPhoto(chat_id, photo=photo_to_send, caption=text, reply_markup=reply_markup)
                 user_song_search_data[user_id]["message_id"] = new_msg.id
            elif current_msg.photo and not photo_to_send: # Switching from photo to text only
                await deleteMessage(current_msg)
                new_msg = await sendMessage(original_message_or_call.message, text, reply_markup=reply_markup)
                user_song_search_data[user_id]["message_id"] = new_msg.id
            elif not current_msg.photo and photo_to_send: # Switching from text to photo
                 await deleteMessage(current_msg)
                 new_msg = await sendPhoto(chat_id, photo=photo_to_send, caption=text, reply_markup=reply_markup)
                 user_song_search_data[user_id]["message_id"] = new_msg.id
            else: # Text to Text edit
                await editMessage(original_message_or_call.message, text, reply_markup=reply_markup)
        except Exception as e:
            LOGGER.error(f"Error editing message for song search: {e}")
            # If edit fails, try sending a new message (e.g. if original message was deleted)
            # This might happen if the message is too old or bot was restarted.
            if user_id in user_song_search_data and user_song_search_data[user_id].get("message_id"):
                new_msg = await sendMessage(original_message_or_call.message, text, reply_markup=reply_markup)
                user_song_search_data[user_id]["message_id"] = new_msg.id


# --- Callback Query Handlers ---

@bot.on_callback_query(filters.regex("^song_page_(next|prev)_(\d+)"))
async def song_page_callback(_, call):
    action_type = call.matches[0].group(1)
    user_id = int(call.matches[0].group(2))

    if user_id not in user_song_search_data or call.from_user.id != user_id:
        await callAnswer(call, "This is not your search or it has expired.", alert=True)
        return

    state = user_song_search_data[user_id]
    if action_type == "next":
        state["page"] += 1
    elif action_type == "prev":
        state["page"] -= 1
    
    await callAnswer(call, f"Loading page {state['page']}...")
    await display_song_search_results(call, user_id)


@bot.on_callback_query(filters.regex("^song_filter_(\d+)_(song|album|artist)"))
async def song_filter_callback(_, call):
    user_id = int(call.matches[0].group(1))
    filter_type = call.matches[0].group(2)

    if user_id not in user_song_search_data or call.from_user.id != user_id:
        await callAnswer(call, "This is not your search or it has expired.", alert=True)
        return
    
    state = user_song_search_data[user_id]
    state["search_type"] = filter_type # This is what main display will look for
    state["current_display_type"] = filter_type # Explicitly set what is being paginated
    state["page"] = 1 # Reset to first page for new filter type

    await callAnswer(call, f"Filtering for {filter_type}s...")
    await display_song_search_results(call, user_id, initial_search_msg_id=None) # initial_search_msg_id is None as we are editing


@bot.on_callback_query(filters.regex("^song_view_(\d+)_(song|album|artist)_([a-zA-Z0-9\-]+)"))
async def song_view_item_callback(_, call):
    user_id = int(call.matches[0].group(1))
    item_type = call.matches[0].group(2)
    item_id = call.matches[0].group(3)

    if user_id not in user_song_search_data or call.from_user.id != user_id:
        await callAnswer(call, "This is not your search or it has expired.", alert=True)
        return

    state = user_song_search_data[user_id]
    results = state.get("results")
    if not results:
        await callAnswer(call, "Search results not found. Please try a new search.", alert=True)
        return

    item_to_display = None
    # Find the item in the stored results
    source_list = results.get(item_type, []) # 'song', 'album', 'artist'
    for item in source_list:
        if item.get('id') == item_id:
            item_to_display = item
            break
    
    if not item_to_display:
        await callAnswer(call, "Could not find details for the selected item.", alert=True)
        LOGGER.error(f"Item ID {item_id} of type {item_type} not found in user {user_id}'s stored results.")
        return

    text = ""
    cover_art_id = item_to_display.get('coverArt', item_to_display.get('id') if item_type != "song" else None)
    if item_type == "song" and not cover_art_id: # If song has no direct coverArt, try its albumId for cover
        cover_art_id = item_to_display.get('albumId')


    if item_type == "song":
        text = format_song_details(item_to_display)
    elif item_type == "album":
        text = format_album_details(item_to_display)
        # Potentially list songs in album here too, if desired (would need another API call like getAlbum)
    elif item_type == "artist":
        text = format_artist_details(item_to_display)
        # Potentially list albums by artist here (would need getArtist -> getAlbums by artist)

    # For "View Details", we will try to send a new message with cover art and details.
    # The original search list remains as is.
    
    photo_to_send = None
    if cover_art_id:
        image_bytes = await navidrome_api.get_cover_art(cover_id=cover_art_id, size=500)
        if image_bytes:
            photo_to_send = BytesIO(image_bytes)
            photo_to_send.name = f"cover_detail_{cover_art_id}.png"

    detail_message_text = f"✨ **Item Details** ✨\n\n{text}"
    
    # Send as a new message, auto-delete after some time?
    # This keeps the main search results intact.
    if photo_to_send:
        sent_detail_msg = await sendPhoto(
            chat_id=call.message.chat.id,
            photo=photo_to_send,
            caption=detail_message_text,
            # No buttons for this detail view for now, could add "Back to search"
        )
    else:
        sent_detail_msg = await sendMessage(call.message, detail_message_text)
    
    await callAnswer(call, "Displaying details...")
    # Auto-delete this detail message after a while to keep chat clean
    asyncio.create_task(auto_delete_message(sent_detail_msg, delay_seconds=180))


@bot.on_callback_query(filters.regex("^song_search_cancel_(\d+)"))
async def song_search_cancel_callback(_, call):
    user_id = int(call.matches[0].group(1))

    if user_id not in user_song_search_data or call.from_user.id != user_id:
        await callAnswer(call, "This is not your search.", alert=True)
        return

    await callAnswer(call, "Search cancelled.")
    try:
        if user_song_search_data[user_id].get("message_id"):
            await deleteMessage(call.message.chat.id, user_song_search_data[user_id]["message_id"])
    except Exception as e:
        LOGGER.error(f"Error deleting song search message on cancel: {e}")
    await cleanup_user_search_state(user_id)


LOGGER.info("SakuraEmbyManager: Navidrome Song Request Panel loaded.")

# TODO:
# - Consider more sophisticated display for "all" results (e.g., sections for songs, albums, artists in one message).
# - Add "request" functionality if needed (e.g., send to admin, add to playlist - this is not specified in current task).
# - Refine error messages and user feedback.
# - The `user_in_group_on_filter` might need adjustment based on actual bot structure.
# - `fix_bottons.বাটপ্যাড` usage if it's a more complex button layout helper. For now, using InlineKeyboardMarkup directly.
# - Test cover art logic thoroughly, especially for songs (album art fallback).
# - Test message editing logic (photo to text, text to photo, etc.)
# - Ensure `config.COMMAND_PREFIXES` is correctly used or adapt if it's a single prefix.
# - The `auto_delete_message` for detail view is a good UX touch.
# - For artist view, one might want to trigger another search for their albums/songs.
# - If `callListen` doesn't delete its prompt automatically on text received, ensure it's handled. (It seems it is based on `request_movie_panel.py` usually)
# - What to do if `navidrome_api.search3` returns an empty list for song/album/artist but status is ok? Handled by "No results found".
# - The `filters.regex("^song_view_(\d+)_(song|album|artist)_([a-zA-Z0-9\-]+)")` for item_id might need to be more general if IDs can have other characters. Subsonic IDs are usually alphanumeric.
# - The `initial_search_msg_id` handling is to replace "Searching..." correctly.
# - When filtering (e.g. "Show Songs"), the photo display logic might need to re-evaluate if a photo should be shown for the new list's first item. (Added basic logic for this)
# - Consider using `bot.name` or similar for logging context if available.
# - The `user_in_group_on_filter` is assumed to be available. If not, basic `filters.private` or `filters.group` might be used.
# - The `search_type` vs `current_display_type` in state: `search_type` is what user selected (all, song, album, artist). `current_display_type` is what is *actually* being paginated if `search_type` was 'all' and we defaulted to showing songs first.
# - `CallbackQuery` is not defined, it should be `from pyrogram.types import CallbackQuery`
# - `COMMAND_PREFIXES` should be `config.COMMAND_PREFIXES` if it's from config, or define it. Assuming it's from `bot.config`.
# - `auto_delete_message` needs to be imported or defined. Assuming it's from `msg_utils`.
# - `deleteMessage` might need `message.chat.id, message.id` if it's just `message`. (Corrected for `initial_search_msg_id`)
# - `editMessage` takes `message_or_chat_id, message_id, text` or `message_instance, text`. (Corrected for clarity)
# - `sendMessage` takes `chat_id_or_message_instance, text`. (Corrected for clarity)

# Final check on imports and pyrogram types
from pyrogram.types import CallbackQuery # Added this explicitly.

# Assuming config.COMMAND_PREFIXES is a list or string, e.g. ['/', '!'] or '/'
if not hasattr(config, 'COMMAND_PREFIXES'):
    LOGGER.warning("config.COMMAND_PREFIXES not found, using default '/'")
    config.COMMAND_PREFIXES = "/"
