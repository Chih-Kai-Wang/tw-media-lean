"""Download the Meta Ad Library Report (Taiwan) through the page's own "Download report" dialog.

    uv run --with crawl4ai python scripts/meta_report_download.py [range ...]
    range: "Last day" | "Last 7 days" | "Last 30 days" | "Last 90 days" | "All dates" (default: all five)

Headless Chromium (Playwright, installed with crawl4ai), no login, no cookies, the project's user agent.
Saves to data/raw/meta_adlib/report_TW_<end date>_<range>.<ext>. Meta allows three downloads a day, and the end
date must fall within the most recent 7 days, so weekly totals exist only if the report is downloaded each week.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "meta_adlib"
UA = "twmedia-research/0.1 (+https://github.com/Chih-Kai-Wang)"
URL = "https://www.facebook.com/ads/library/report/?source=nav-header&country=TW"
RANGES = ["All dates", "Last 90 days", "Last 30 days", "Last 7 days", "Last day"]


async def one(page, label: str) -> None:
    await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    await page.wait_for_timeout(8000)
    if re.search(r"checkpoint|security check", page.url + (await page.title()), re.I):
        raise SystemExit("stopped: checkpoint")
    sec = page.locator("div", has=page.get_by_text("Customize the report (.csv)", exact=False)).filter(
        has=page.locator("a", has_text="Download report")).last
    await sec.scroll_into_view_if_needed()
    rng = sec.get_by_role("button", name=re.compile(r"^(Last day|Last 7 days|Last 30 days|Last 90 days|All dates)$"))
    if (await rng.inner_text()).strip() != label:
        await rng.click()
        await page.wait_for_timeout(1500)
        await page.get_by_text(label, exact=True).last.click()
        await page.wait_for_timeout(1500)
    end = (await sec.locator("input").first.input_value()).strip()
    async with page.expect_download(timeout=300000) as dl:
        await sec.locator("a", has_text="Download report").click()
    d = await dl.value
    end = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", end)
    ext = Path(d.suggested_filename).suffix or ".bin"
    path = OUT / f"report_TW_{(end.group(1) if end else 'unknown').replace(',', '').replace(' ', '-')}_{label.replace(' ', '_')}{ext}"
    await d.save_as(path)
    print(json.dumps({"range": label, "file": d.suggested_filename, "bytes": path.stat().st_size,
                      "url": d.url[:300], "saved": str(path.relative_to(ROOT))}, ensure_ascii=False), flush=True)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    labels = sys.argv[1:] or RANGES
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context(user_agent=UA, locale="en-US", accept_downloads=True, viewport={"width": 1400, "height": 1600})
        page = await ctx.new_page()
        page.on("request", lambda r: print("request", r.method, r.url[:300], flush=True)
                if "download" in r.url.lower() or "report" in r.url.lower() and r.resource_type in ("xhr", "fetch") else None)
        for i, label in enumerate(labels):
            if i:
                await page.wait_for_timeout(15000)
            try:
                await one(page, label)
            except SystemExit:
                raise
            except Exception as e:
                await page.screenshot(path=str(OUT / f"report_fail_{label.replace(' ', '_')}.png"))
                print(json.dumps({"range": label, "error": str(e)[:400]}, ensure_ascii=False), flush=True)
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
