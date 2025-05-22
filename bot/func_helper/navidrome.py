# -*- coding: utf-8 -*-
"""
Navidrome API (Subsonic API) Client
"""
import asyncio
import hashlib
import random
import string
from functools import wraps

import aiohttp
from aiohttp_retry import RetryClient, ExponentialRetry

from bot import LOGGER,config

# --- Configuration ---
NAVIDROME_URL = config.navidrome.get('navidrome_url')
NAVIDROME_USERNAME = config.navidrome.get('navidrome_username')
NAVIDROME_PASSWORD = config.navidrome.get('navidrome_password')
NAVIDROME_APP_NAME = config.navidrome.get('navidrome_app_name', 'SakuraEmbyBossBot')
SUBSONIC_API_VERSION = "1.16.1"  # Common Subsonic API version
RESPONSE_FORMAT = "json"

# --- Helper Functions ---
def generate_salt(length=6):
    """Generates a random alphanumeric salt."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def generate_token(password, salt):
    """Generates the Subsonic API token (md5(password + salt))."""
    if not password:
        return None
    salted_password = password + salt
    return hashlib.md5(salted_password.encode('utf-8')).hexdigest()

# --- AIOHTTP Retry Decorator ---
def aiohttp_retry_for_navidrome(func):
    """
    Decorator to add retry logic to aiohttp requests for Navidrome.
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        # self here is the NavidromeAPI instance
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
            LOGGER.info("NavidromeAPI: New aiohttp.ClientSession created.")

        retry_options = ExponentialRetry(attempts=3, excepciones_ignorar=(aiohttp.ClientResponseError,))
        retry_client = RetryClient(client_session=self.session, retry_options=retry_options)
        
        # Pass the retry_client to the decorated function if it expects it,
        # or use it directly here if the function is part of the class.
        # For this structure, we'll assume the method uses self.session which is now retry-enabled via context
        async with retry_client: # Use the retry_client for the session context
            return await func(self, *args, **kwargs)

    return wrapper


# --- Navidrome API Client Class ---
class NavidromeAPI:
    """
    Asynchronous client for interacting with the Navidrome API (Subsonic).
    """
    def __init__(self, base_url, username, password, app_name="NavidromeBot", api_version="1.16.1", response_format="json"):
        if not base_url or not username: # Password can be empty for some public servers initially
            LOGGER.error("NavidromeAPI: URL and Username are required.")
            raise ValueError("Navidrome URL and Username are required.")
        
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password # Store password to generate token per request with new salt
        self.app_name = app_name
        self.api_version = api_version
        self.response_format = response_format
        self.session = None # Initialized in methods or when first needed
        LOGGER.info(f"NavidromeAPI initialized for URL: {self.base_url}, User: {self.username}")

    async def _get_session(self):
        """Gets or creates an aiohttp ClientSession."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            LOGGER.info("NavidromeAPI: New aiohttp.ClientSession created for instance.")
        return self.session

    def _get_auth_params(self):
        """Generates authentication parameters (salt and token) for a request."""
        salt = generate_salt()
        token = generate_token(self.password, salt)
        if not token: # If password is not set, don't send token/salt
            return {}
        return {"s": salt, "t": token}

    @aiohttp_retry_for_navidrome
    async def _make_request(self, endpoint, params=None, is_json_response=True):
        """
        Makes an asynchronous GET request to a Navidrome endpoint.

        :param endpoint: The API endpoint (e.g., "/rest/ping.view").
        :param params: A dictionary of query parameters for the request.
        :param is_json_response: Whether to expect a JSON response.
        :return: Parsed JSON response as a dictionary, or raw content if not JSON.
        """
        session = await self._get_session()
        
        url = f"{self.base_url}{endpoint}"
        
        base_params = {
            "u": self.username,
            "v": self.api_version,
            "c": self.app_name,
            "f": self.response_format,
        }
        # Add auth params (token and salt) if password is provided
        if self.password:
            base_params.update(self._get_auth_params())

        if params:
            base_params.update(params)

        try:
            LOGGER.debug(f"NavidromeAPI Request: GET {url} with params: {base_params}")
            async with session.get(url, params=base_params) as response:
                response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                if is_json_response:
                    # Check content type before parsing
                    if "application/json" in response.headers.get("Content-Type", "").lower():
                        data = await response.json()
                        LOGGER.debug(f"NavidromeAPI JSON Response: {data}")
                        if "subsonic-response" in data and data["subsonic-response"].get("status") == "failed":
                            error_msg = data["subsonic-response"].get("error", {}).get("message", "Unknown Navidrome API error")
                            LOGGER.error(f"Navidrome API Error: {error_msg} for endpoint {endpoint}")
                            return {"error": error_msg, "status": "failed"} # Propagate error structure
                        return data
                    else:
                        text_data = await response.text()
                        LOGGER.error(f"NavidromeAPI Error: Expected JSON but received Content-Type: {response.headers.get('Content-Type')}. Response text: {text_data[:200]}...")
                        return {"error": "Invalid content type, expected JSON", "status": "failed"}
                else:
                    content = await response.read() # For binary data like images
                    LOGGER.debug(f"NavidromeAPI Binary Response: {len(content)} bytes from {endpoint}")
                    return content
        except aiohttp.ClientResponseError as e: # Handles 4xx/5xx from raise_for_status
            LOGGER.error(f"NavidromeAPI HTTP Error: {e.status} {e.message} for {url}. Response: {await response.text() if response else 'No response text'}")
            return {"error": f"HTTP {e.status}: {e.message}", "status": "failed"}
        except aiohttp.ClientError as e: # Handles other client errors (connection, timeout, etc.)
            LOGGER.error(f"NavidromeAPI Client Error: {e} for {url}")
            return {"error": str(e), "status": "failed"}
        except asyncio.TimeoutError:
            LOGGER.error(f"NavidromeAPI Timeout Error for {url}")
            return {"error": "Request timed out", "status": "failed"}

    async def ping(self):
        """
        Pings the Navidrome server to check connectivity.
        Endpoint: /rest/ping.view
        """
        LOGGER.info("Pinging Navidrome server...")
        response = await self._make_request("/rest/ping.view")
        if response and response.get("subsonic-response", {}).get("status") == "ok":
            LOGGER.info("Navidrome ping successful.")
            return response
        else:
            LOGGER.error(f"Navidrome ping failed. Response: {response}")
            return response # Return the error structure

    async def search3(self, query, artist_count=5, album_count=5, song_count=10):
        """
        Searches for artists, albums, and songs.
        Endpoint: /rest/search3.view
        """
        if not query:
            LOGGER.error("NavidromeAPI search3: Query cannot be empty.")
            return {"error": "Query cannot be empty", "status": "failed"}

        params = {
            "query": query,
            "artistCount": artist_count,
            "albumCount": album_count,
            "songCount": song_count,
            # Subsonic API also has musicFolderId, if needed in future
        }
        LOGGER.info(f"Searching Navidrome for '{query}'...")
        return await self._make_request("/rest/search3.view", params=params)

    async def get_cover_art(self, cover_id, size=None):
        """
        Retrieves cover art for a given ID.
        Endpoint: /rest/getCoverArt.view
        Returns raw image data (bytes).
        """
        if not cover_id:
            LOGGER.error("NavidromeAPI get_cover_art: Cover ID cannot be empty.")
            return None # Or raise error, or return specific error marker

        params = {"id": cover_id}
        if size:
            params["size"] = size
        
        LOGGER.info(f"Fetching Navidrome cover art for ID: {cover_id} (size: {size or 'original'})")
        image_bytes = await self._make_request("/rest/getCoverArt.view", params=params, is_json_response=False)
        
        # Check if the response is bytes (success) or dict (error from _make_request)
        if isinstance(image_bytes, dict) and "error" in image_bytes:
            LOGGER.error(f"Failed to fetch cover art {cover_id}: {image_bytes['error']}")
            return None
        elif not isinstance(image_bytes, bytes):
            LOGGER.error(f"Failed to fetch cover art {cover_id}: Unexpected response type {type(image_bytes)}")
            return None
            
        return image_bytes

    async def close_session(self):
        """Closes the aiohttp ClientSession."""
        if self.session and not self.session.closed:
            await self.session.close()
            LOGGER.info("NavidromeAPI: aiohttp.ClientSession closed.")

# --- Global Navidrome API Client Instance ---
navidrome_api = None
if NAVIDROME_URL and NAVIDROME_USERNAME: # Password can be optional for some setups or if only public info is accessed
    try:
        navidrome_api = NavidromeAPI(
            base_url=NAVIDROME_URL,
            username=NAVIDROME_USERNAME,
            password=NAVIDROME_PASSWORD, # Will be None if not set in config
            app_name=NAVIDROME_APP_NAME,
            api_version=SUBSONIC_API_VERSION,
            response_format=RESPONSE_FORMAT
        )
        LOGGER.info("Global Navidrome API client initialized.")
    except ValueError as e: # From NavidromeAPI __init__
        LOGGER.error(f"Failed to initialize global Navidrome API client: {e}")
    except Exception as e:
        LOGGER.error(f"An unexpected error occurred during global Navidrome API client initialization: {e}", exc_info=True)
else:
    if not config.navidrome.get('navidrome_url'): # Only log if it looks like user intended to set it up
        LOGGER.info("Navidrome URL not configured. Global Navidrome API client not initialized.")
    elif not config.navidrome.get('navidrome_username'):
        LOGGER.info("Navidrome Username not configured. Global Navidrome API client not initialized.")


# --- Example Usage (for testing, can be removed or commented out) ---
async def main_test():
    if not navidrome_api:
        LOGGER.error("Navidrome API client not available for testing.")
        return

    LOGGER.info("--- Testing Navidrome API ---")
    
    # Test Ping
    ping_response = await navidrome_api.ping()
    LOGGER.info(f"Ping Response: {ping_response}")

    if ping_response and ping_response.get("subsonic-response", {}).get("status") == "ok":
        # Test Search (only if ping is ok)
        search_query = "Michael Jackson" # Replace with a relevant query for your library
        search_results = await navidrome_api.search3(query=search_query)
        LOGGER.info(f"Search Results for '{search_query}': {search_results}")

        if search_results and search_results.get("subsonic-response", {}).get("status") == "ok":
            results = search_results["subsonic-response"].get("searchResult3")
            if results:
                if results.get("album"):
                    first_album_id = results["album"][0].get("coverArt") if results["album"][0].get("coverArt") else results["album"][0].get("id")
                    if first_album_id: # Navidrome often uses 'id' for coverArt if coverArt field is missing
                        LOGGER.info(f"Attempting to fetch cover art for ID: {first_album_id}")
                        cover_image = await navidrome_api.get_cover_art(cover_id=first_album_id, size=200)
                        if cover_image:
                            LOGGER.info(f"Cover art fetched successfully: {len(cover_image)} bytes.")
                            # with open(f"cover_{first_album_id.replace('-','')}.png", "wb") as f:
                            #     f.write(cover_image)
                            # LOGGER.info(f"Saved cover art as cover_{first_album_id.replace('-','')}.png")
                        else:
                            LOGGER.error("Failed to fetch cover art.")
                    else:
                        LOGGER.info("No cover art ID found for the first album.")
                else:
                    LOGGER.info("No albums found in search results to test getCoverArt.")
            else:
                LOGGER.info("No 'searchResult3' field in search response.")
    else:
        LOGGER.error("Skipping further tests as Ping failed.")

    await navidrome_api.close_session()
    LOGGER.info("--- Navidrome API Test Finished ---")

if __name__ == "__main__":
    # This is for direct script execution testing.
    # You'd need to ensure bot.py or equivalent has loaded config.
    # For simplicity, we'll assume config is loaded if run this way.
    # A more robust way would be to load config here if __main__.
    
    # Configure logging for standalone testing
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # Assuming config is loaded by bot.py or a similar entry point.
    # If running this file directly, you might need to mock or manually load `bot.config`.
    # For example, by creating a dummy config object:
    # class DummyConfig:
    #     class NavidromeConfig:
    #         navidrome_url = "YOUR_NAVIDROME_URL"
    #         navidrome_username = "YOUR_NAVIDROME_USERNAME"
    #         navidrome_password = "YOUR_NAVIDROME_PASSWORD"
    #         navidrome_app_name = "TestApp"
    #     navidrome = NavidromeConfig()
    # config = DummyConfig()
    #
    # # Then re-initialize the client for testing
    # if config.navidrome.navidrome_url and config.navidrome.navidrome_username:
    #     navidrome_api = NavidromeAPI(
    #         base_url=config.navidrome.navidrome_url,
    #         username=config.navidrome.navidrome_username,
    #         password=config.navidrome.navidrome_password,
    #         app_name=config.navidrome.navidrome_app_name
    #     )
    #     asyncio.run(main_test())
    # else:
    #     print("Please configure dummy Navidrome settings in the script for __main__ test.")
    
    # Current assumption: this script is part of a larger bot and `config` is already populated.
    # The `if __name__ == "__main__":` block is primarily for illustrative testing.
    # To run it: python -m bot.func_helper.navidrome
    # (This might require adjustments to PYTHONPATH or how `bot.config` is accessed)
    
    LOGGER.info("To test this module directly, ensure bot.config is populated and uncomment asyncio.run(main_test()) call with appropriate setup.")
    # Example:
    # asyncio.run(main_test()) # Make sure config is loaded before this.
    pass
