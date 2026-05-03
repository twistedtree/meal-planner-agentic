"""Smoke test: log in, fetch a known recipe, list a page of managed collections.

Run: .venv/Scripts/python.exe scripts/cookidoo_smoke.py
"""
import asyncio
import os
from dotenv import load_dotenv

import aiohttp
from cookidoo_api import Cookidoo, get_localization_options
from cookidoo_api.types import CookidooConfig


async def main() -> None:
    load_dotenv()
    email = os.environ["cookidoo_user"]
    password = os.environ["cookiday_pass"]

    async with aiohttp.ClientSession() as session:
        loc = (await get_localization_options(country="au", language="en-AU"))[0]
        print(f"Locale: {loc}")
        cookidoo = Cookidoo(
            session,
            cfg=CookidooConfig(email=email, password=password, localization=loc),
        )
        auth = await cookidoo.login()
        print(f"Login ok: user_id={getattr(auth, 'user_id', '?')}")

        sub = await cookidoo.get_active_subscription()
        print(f"Subscription: {sub!r}")

        cols = await cookidoo.get_managed_collections(page=0)
        print(f"Managed collections page 0: {len(cols)} items")
        for c in cols[:3]:
            print(f"  - {c!r}")

        # Probe one recipe's detail shape
        details = await cookidoo.get_recipe_details("r471786")
        print("--- recipe details ---")
        print(f"type={type(details).__name__}")
        if hasattr(details, "__dict__"):
            for k, v in vars(details).items():
                s = repr(v)
                if len(s) > 300:
                    s = s[:300] + "...(truncated)"
                print(f"  {k}: {s}")


if __name__ == "__main__":
    asyncio.run(main())
