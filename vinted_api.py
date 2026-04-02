import aiohttp
import asyncio
import json
import time
from typing import Optional
from urllib.parse import urlencode

VINTED_DOMAINS = {
    "de": "https://www.vinted.de",
    "at": "https://www.vinted.at",
    "fr": "https://www.vinted.fr",
    "nl": "https://www.vinted.nl",
    "be": "https://www.vinted.be",
    "pl": "https://www.vinted.pl",
    "es": "https://www.vinted.es",
    "it": "https://www.vinted.it",
    "cz": "https://www.vinted.cz",
    "uk": "https://www.vinted.co.uk",
    "com": "https://www.vinted.com",
    "lt": "https://www.vinted.lt",
    "lu": "https://www.vinted.lu",
    "se": "https://www.vinted.se",
    "fi": "https://www.vinted.fi",
    "dk": "https://www.vinted.dk",
    "ro": "https://www.vinted.ro",
    "sk": "https://www.vinted.sk",
    "hu": "https://www.vinted.hu",
    "hr": "https://www.vinted.hr",
    "pt": "https://www.vinted.pt",
    "gr": "https://www.vinted.gr",
}

class VintedAPI:
    def __init__(self, domain: str = "de"):
        self.domain = domain
        self.base_url = VINTED_DOMAINS.get(domain, VINTED_DOMAINS["de"])
        self.session: Optional[aiohttp.ClientSession] = None
        self._cookie_cache = None
        self._cookie_expiry = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": f"{self.base_url}/",
                "Origin": self.base_url,
                "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }
            self.session = aiohttp.ClientSession(headers=headers)
        return self.session

    async def _refresh_cookies(self):
        """Fetch fresh cookies from Vinted homepage"""
        now = time.time()
        if self._cookie_cache and now < self._cookie_expiry:
            return
        try:
            session = await self._get_session()
            async with session.get(self.base_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                self._cookie_cache = True
                self._cookie_expiry = now + 600  # 10 min
        except Exception as e:
            print(f"Cookie refresh error: {e}")

    async def search(
        self,
        query: str = "",
        brand_ids: list = None,
        catalog_ids: list = None,
        size_ids: list = None,
        color_ids: list = None,
        status_ids: list = None,
        price_from: float = None,
        price_to: float = None,
        order: str = "newest_first",
        per_page: int = 20,
        page: int = 1,
    ) -> dict:
        """Search Vinted for items"""
        await self._refresh_cookies()
        
        params = {
            "search_text": query,
            "order": order,
            "per_page": per_page,
            "page": page,
            "time": int(time.time()),
        }

        if brand_ids:
            for i, bid in enumerate(brand_ids):
                params[f"brand_ids[]"] = bid
        if catalog_ids:
            for cid in catalog_ids:
                params[f"catalog_ids[]"] = cid
        if size_ids:
            for sid in size_ids:
                params[f"size_ids[]"] = sid
        if color_ids:
            for cid in color_ids:
                params[f"color_ids[]"] = cid
        if status_ids:
            for sid in status_ids:
                params[f"status_ids[]"] = sid
        if price_from is not None:
            params["price_from"] = price_from
        if price_to is not None:
            params["price_to"] = price_to

        url = f"{self.base_url}/web/api/core/catalog/items"
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                elif resp.status == 429:
                    return {"error": "rate_limited", "items": []}
                else:
                    text = await resp.text()
                    return {"error": f"HTTP {resp.status}", "items": []}
        except asyncio.TimeoutError:
            return {"error": "timeout", "items": []}
        except Exception as e:
            return {"error": str(e), "items": []}

    async def get_item(self, item_id: int) -> dict:
        """Get details of a specific item"""
        await self._refresh_cookies()
        url = f"{self.base_url}/web/api/core/items/{item_id}"
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {}
        except Exception:
            return {}

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def build_item_url(base_url: str, item: dict) -> str:
    item_id = item.get("id", "")
    title = item.get("title", "item").lower().replace(" ", "-")
    # Remove special chars
    import re
    title = re.sub(r"[^a-z0-9\-]", "", title)[:50]
    return f"{base_url}/items/{item_id}-{title}"
