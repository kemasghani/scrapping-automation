from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import Response, TimeoutError as PWTimeout, sync_playwright

from extractor import (
    build_dietary_sheet,
    build_field_guide,
    build_menu_sheet,
    build_merchant_sheet,
    build_modifiers_sheet,
    build_promotions_sheet,
    build_summary_sheet,
)
from xlsx_writer import write_workbook

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

DEFAULT_URL = (
    "https://food.grab.com/id/id/restaurant/"
    "ayam-katsu-katsunami-lokarasa-citraland-delivery/6-C7EYGBJDME3JRN"
)

JAKARTA_COORDS = [
    (-6.1767352, 106.826504),
    (-6.2088, 106.8456),
    (-6.1944, 106.8229),
    (-6.2297, 106.8175),
]

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]


@dataclass
class Capture:
    payloads: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def is_merchant_payload(obj: Any) -> bool:
        if not isinstance(obj, dict):
            return False
        m = obj.get("merchant")
        if not isinstance(m, dict):
            return False
        menu = m.get("menu")
        if not isinstance(menu, dict):
            return False
        cats = menu.get("categories")
        return isinstance(cats, list) and len(cats) > 0

    def on_response(self, response: Response) -> None:
        url = response.url
        if "grab" not in url:
            return
        if any(s in url for s in ("/locales/", ".png", ".jpg", ".svg", ".css", ".woff", "/static/")):
            return
        ctype = response.headers.get("content-type", "")
        if "json" not in ctype:
            return
        try:
            data = response.json()
        except Exception:
            return
        if self.is_merchant_payload(data):
            print(f"[capture] MATCH {url}", flush=True)
            self.payloads.append({"url": url, "data": data})


def _human_scroll(page, duration_s: float = 6.0) -> None:
    end = time.time() + duration_s
    y = 0
    while time.time() < end:
        y += random.randint(250, 700)
        try:
            page.mouse.move(random.randint(100, 1200), random.randint(100, 700))
            page.mouse.wheel(0, random.randint(200, 500))
            page.evaluate(f"window.scrollTo(0, {y})")
        except Exception:
            pass
        time.sleep(random.uniform(0.4, 1.1))


def fetch_payload(url: str, *, headless: bool = True, timeout_s: int = 45, max_attempts: int = 3) -> dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        lat, lng = random.choice(JAKARTA_COORDS)
        ua = random.choice(USER_AGENTS)
        print(f"[scraper] attempt {attempt}/{max_attempts} · lat={lat} lng={lng}", flush=True)
        capture = Capture()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                ctx = browser.new_context(
                    user_agent=ua,
                    locale="id-ID",
                    timezone_id="Asia/Jakarta",
                    viewport={"width": 1366, "height": 860},
                    geolocation={"latitude": lat, "longitude": lng},
                    permissions=["geolocation"],
                    extra_http_headers={"Accept-Language": "id-ID,id;q=0.9,en;q=0.8"},
                )
                ctx.add_init_script(
                    """
                    Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
                    Object.defineProperty(navigator,'languages',{get:()=>['id-ID','id','en']});
                    Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
                    window.chrome = { runtime: {} };
                    """
                )
                page = ctx.new_page()
                page.on("response", capture.on_response)

                print(f"[scraper] navigating → {url}", flush=True)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
                except PWTimeout:
                    print("[scraper] goto timeout", flush=True)

                deadline = time.time() + timeout_s
                _human_scroll(page, duration_s=5.0)
                while time.time() < deadline and not capture.payloads:
                    _human_scroll(page, duration_s=2.0)

                if capture.payloads:
                    time.sleep(random.uniform(1.0, 2.0))
                browser.close()

            if capture.payloads:
                capture.payloads.sort(key=lambda p: len(json.dumps(p["data"])), reverse=True)
                best = capture.payloads[0]
                ts = int(time.time())
                snap = OUT_DIR / f"raw_{ts}.json"
                snap.write_text(json.dumps(best["data"], ensure_ascii=False, indent=2))
                print(f"[scraper] captured from {best['url']}")
                print(f"[scraper] raw snapshot → {snap}")
                return best["data"]
        except Exception as e:
            last_err = e
            print(f"[scraper] attempt {attempt} error: {e}", flush=True)
        time.sleep(random.uniform(2.0, 5.0))

    raise RuntimeError(f"Failed to capture merchant payload after {max_attempts} attempts. Last: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default=DEFAULT_URL)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--from-raw")
    args = ap.parse_args()

    if args.from_raw:
        payload = json.loads(Path(args.from_raw).read_text())
        print(f"[scraper] loaded {args.from_raw}")
    else:
        payload = fetch_payload(args.url, headless=not args.headful)

    menu_df = build_menu_sheet(payload)
    mods_df = build_modifiers_sheet(payload)
    promo_df = build_promotions_sheet(payload)
    merchant_df = build_merchant_sheet(payload)
    dietary_df = build_dietary_sheet(payload)
    summary_df = build_summary_sheet(payload, menu_df, mods_df, promo_df, args.url)
    guide_df = build_field_guide()

    if menu_df.empty:
        print("[scraper] WARNING: menu DataFrame is empty.", file=sys.stderr)
        return 2

    merchant_name = menu_df["outlet"].iloc[0]
    slug = re.sub(r"[^a-z0-9]+", "_", merchant_name.lower()).strip("_")
    xlsx_path = OUT_DIR / f"{slug}_menu.xlsx"

    write_workbook(
        xlsx_path,
        summary=summary_df,
        merchant=merchant_df,
        menu=menu_df,
        modifiers=mods_df,
        promotions=promo_df,
        dietary=dietary_df,
        field_guide=guide_df,
    )

    unique_items = menu_df["item_id"].nunique()
    print(f"[scraper] {unique_items} items · {len(menu_df)} rows · {len(mods_df)} modifiers · {len(promo_df)} promotions")
    print(f"[scraper] workbook → {xlsx_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
