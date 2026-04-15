from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd


def _first(d: Any, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _money(n: Any) -> float | None:
    if n in (None, 0, "0"):
        return None
    try:
        return float(n) / 100
    except (TypeError, ValueError):
        return None


def _seconds_to_iso(s: Any) -> str | None:
    try:
        s = int(s)
    except (TypeError, ValueError):
        return None
    if s <= 0 or s > 4_102_444_800:
        return None
    return pd.Timestamp(s, unit="s", tz="Asia/Jakarta").strftime("%Y-%m-%d %H:%M:%S %Z")


def _strip_html(s: Any) -> str:
    if not s:
        return ""
    return re.sub(r"<[^>]+>", "", str(s)).strip()


def build_merchant_sheet(payload: dict) -> pd.DataFrame:
    m = payload.get("merchant", {}) or {}
    latlng = m.get("latlng") or {}
    cur = m.get("currency") or {}
    hours = m.get("openingHours") or {}
    sof = (m.get("sofConfiguration") or {}).get("fixFeeForDisplay") or {}

    rows = [
        ("Merchant ID", m.get("ID")),
        ("Name", m.get("name")),
        ("Branch", m.get("branchName")),
        ("Chain", m.get("chainName")),
        ("Cuisine", m.get("cuisine")),
        ("Business Type", m.get("businessType")),
        ("Status", m.get("status")),
        ("Rating", m.get("rating")),
        ("Vote Count", m.get("voteCount")),
        ("ETA (min)", m.get("ETA")),
        ("Distance (km)", m.get("distanceInKm")),
        ("Delivery Radius (m)", m.get("radius")),
        ("Delivered By", m.get("deliverBy")),
        ("Latitude", latlng.get("latitude")),
        ("Longitude", latlng.get("longitude")),
        ("Time Zone", m.get("timeZone")),
        ("Currency", f"{cur.get('symbol','')} ({cur.get('code','')})"),
        ("Service Fee (display)", sof.get("amountDisplay")),
        ("Hero Photo", m.get("photoHref")),
        ("Small Photo", m.get("smallPhotoHref")),
        ("Share Link", (m.get("merchantShareLink") or {}).get("shareLink")),
        ("Merchant Group ID", m.get("merchantGroupID")),
        ("Displayed Hours Today", hours.get("displayedHours")),
        ("Hours — Mon", hours.get("mon")),
        ("Hours — Tue", hours.get("tue")),
        ("Hours — Wed", hours.get("wed")),
        ("Hours — Thu", hours.get("thu")),
        ("Hours — Fri", hours.get("fri")),
        ("Hours — Sat", hours.get("sat")),
        ("Hours — Sun", hours.get("sun")),
    ]
    return pd.DataFrame(rows, columns=["Field", "Value"])


def build_menu_sheet(payload: dict) -> pd.DataFrame:
    m = payload.get("merchant", {}) or {}
    merchant_name = m.get("name") or ""
    menu = m.get("menu") or {}
    cats = menu.get("categories") or []

    rows: list[dict[str, Any]] = []
    for ci, cat in enumerate(cats):
        cat_name = _first(cat, "name", default="")
        cat_available = _first(cat, "available", default=True)
        items = _first(cat, "items", default=[]) or []
        for ii, it in enumerate(items):
            price_before = _money(_first(it, "priceInMinorUnit", "PriceInMin"))
            price_after = _money(_first(it, "discountedPriceInMin"))
            takeaway = _money(_first(it, "takeawayPriceInMin"))
            takeaway_disc = _money(_first(it, "discountedTakeawayPriceInMin"))
            promo_amount = None
            promo_pct = _first(it, "discountPercentage")
            if price_before and price_after and price_after < price_before:
                promo_amount = round(price_before - price_after, 2)
                if not promo_pct:
                    promo_pct = round(promo_amount / price_before * 100, 2)

            meta_raw = it.get("metadata") or "{}"
            campaign_end = campaign_start = None
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                dmetas = ((meta.get("discounts") or {}).get("discount_metas") or [])
                if dmetas:
                    cond = dmetas[0].get("conditions") or {}
                    campaign_start = _seconds_to_iso((cond.get("start_time") or {}).get("seconds"))
                    campaign_end = _seconds_to_iso((cond.get("end_time") or {}).get("seconds"))
            except Exception:
                pass

            images = it.get("images") or []
            img_url = it.get("imgHref") or (images[0] if images else "") or ""
            modifier_groups = it.get("modifierGroups") or []
            modifier_count = sum(len(g.get("modifiers") or []) for g in modifier_groups)

            rows.append(
                {
                    "outlet": merchant_name,
                    "category_order": ci + 1,
                    "category": cat_name,
                    "category_available": bool(cat_available),
                    "item_order": ii + 1,
                    "menu": _first(it, "name", default="").strip(),
                    "description": _strip_html(it.get("description")),
                    "price_before_promo": price_before,
                    "price_after_promo": price_after if price_after else price_before,
                    "promo_amount": promo_amount,
                    "promo_percentage": promo_pct if promo_pct else None,
                    "takeaway_price": takeaway,
                    "takeaway_discounted": takeaway_disc,
                    "campaign_name": it.get("campaignName") or "",
                    "campaign_id": it.get("campaignID") or "",
                    "campaign_start": campaign_start,
                    "campaign_end": campaign_end,
                    "available": bool(_first(it, "available", default=True)),
                    "modifier_group_count": len(modifier_groups),
                    "modifier_total_options": modifier_count,
                    "image_url": img_url,
                    "image_fallback": it.get("imgHrefFallback") or "",
                    "item_id": it.get("ID"),
                    "merchant_id": it.get("merchantID"),
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for col in ("price_before_promo", "price_after_promo", "promo_amount",
                "promo_percentage", "takeaway_price", "takeaway_discounted"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["is_duplicate_appearance"] = df.duplicated(subset=["item_id"], keep="first")
    df["menu"] = df["menu"].str.strip()
    return df


def build_modifiers_sheet(payload: dict) -> pd.DataFrame:
    cats = (((payload.get("merchant") or {}).get("menu") or {}).get("categories") or [])
    rows: list[dict[str, Any]] = []
    for cat in cats:
        for it in cat.get("items") or []:
            item_name = it.get("name") or ""
            item_id = it.get("ID")
            for g in it.get("modifierGroups") or []:
                group_name = g.get("name") or ""
                for mod in g.get("modifiers") or []:
                    rows.append(
                        {
                            "item": item_name,
                            "item_id": item_id,
                            "group": group_name,
                            "group_selection_min": g.get("selectionRangeMin"),
                            "group_selection_max": g.get("selectionRangeMax"),
                            "group_available": bool(g.get("available", True)),
                            "modifier": mod.get("name") or "",
                            "modifier_id": mod.get("ID"),
                            "price": _money(mod.get("priceInMinorUnit")) or 0.0,
                            "available": bool(mod.get("available", True)),
                            "sort_order": mod.get("sortOrder"),
                        }
                    )
    return pd.DataFrame(rows)


def build_promotions_sheet(payload: dict) -> pd.DataFrame:
    m = payload.get("merchant") or {}
    camps = ((m.get("menu") or {}).get("campaigns") or [])
    rows = []
    for c in camps:
        rows.append(
            {
                "campaign_id": c.get("ID"),
                "name": c.get("name"),
                "level": c.get("campaignLevel"),
                "status": c.get("status"),
                "priority": c.get("priority"),
                "label": c.get("label"),
                "start": _seconds_to_iso((c.get("startTime") or {}).get("seconds")),
                "end": _seconds_to_iso((c.get("endTime") or {}).get("seconds")),
                "terms": " | ".join(c.get("tcDetails") or []),
                "decision_id": c.get("decisionID"),
            }
        )
    offers = ((m.get("offerCarousel") or {}).get("offerHighlights") or [])
    for o in offers:
        hl = o.get("highlight") or {}
        rows.append(
            {
                "campaign_id": f"offer:{o.get('type','')}",
                "name": hl.get("title"),
                "level": "offer_highlight",
                "status": "visible",
                "priority": None,
                "label": o.get("type"),
                "start": None,
                "end": None,
                "terms": hl.get("subtitle"),
                "decision_id": "",
            }
        )
    return pd.DataFrame(rows)


def build_dietary_sheet(payload: dict) -> pd.DataFrame:
    opts = (((payload.get("merchant") or {}).get("menu") or {}).get("dietaryOptions") or [])
    rows = []
    for o in opts:
        rows.append(
            {
                "id": o.get("id"),
                "name": o.get("name"),
                "description": _strip_html(o.get("description")),
                "show_disclaimer": bool(o.get("showDisclaimer", False)),
                "icon": o.get("icon"),
            }
        )
    return pd.DataFrame(rows)


def build_summary_sheet(payload: dict, menu_df: pd.DataFrame, mods_df: pd.DataFrame, promos_df: pd.DataFrame, source_url: str) -> pd.DataFrame:
    m = payload.get("merchant") or {}
    unique_items = menu_df["item_id"].nunique() if not menu_df.empty else 0
    available_items = int((menu_df["available"] & ~menu_df["is_duplicate_appearance"]).sum()) if not menu_df.empty else 0
    promo_items = int((menu_df["promo_amount"].notna() & ~menu_df["is_duplicate_appearance"]).sum()) if not menu_df.empty else 0
    avg_price = round(
        menu_df.loc[~menu_df["is_duplicate_appearance"], "price_after_promo"].mean(), 2
    ) if not menu_df.empty else 0
    min_price = menu_df.loc[~menu_df["is_duplicate_appearance"], "price_after_promo"].min() if not menu_df.empty else 0
    max_price = menu_df.loc[~menu_df["is_duplicate_appearance"], "price_after_promo"].max() if not menu_df.empty else 0
    avg_discount = round(
        menu_df.loc[menu_df["promo_amount"].notna() & ~menu_df["is_duplicate_appearance"], "promo_percentage"].mean(), 2
    ) if not menu_df.empty else 0

    rows = [
        ("Outlet", m.get("name")),
        ("Source URL", source_url),
        ("Scraped At", pd.Timestamp.now(tz="Asia/Jakarta").strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("Extraction Method", "Playwright stealth + API interception (portal.grab.com/foodweb/guest/v2/merchants)"),
        ("Rating", f"{m.get('rating')} ⭐ ({m.get('voteCount')} votes)"),
        ("Cuisine", m.get("cuisine")),
        ("ETA", f"{m.get('ETA')} min"),
        ("Status", m.get("status")),
        ("", ""),
        ("— Menu Stats —", ""),
        ("Unique menu items", unique_items),
        ("Total menu rows (incl. duplicates across categories)", len(menu_df)),
        ("Available items", available_items),
        ("Out-of-stock items", unique_items - available_items),
        ("Items on promo", promo_items),
        ("Avg discount %", f"{avg_discount}%" if avg_discount else "-"),
        ("Min price (IDR)", min_price),
        ("Max price (IDR)", max_price),
        ("Avg price (IDR)", avg_price),
        ("Categories", menu_df["category"].nunique() if not menu_df.empty else 0),
        ("Modifier options", len(mods_df)),
        ("Active promotions / campaigns", len(promos_df)),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def build_field_guide() -> pd.DataFrame:
    rows = [
        ("Menu", "outlet", "Nama restoran (merchant.name)."),
        ("Menu", "category_order", "Urutan kategori pada menu Grab (1 = kategori pertama)."),
        ("Menu", "category", "Nama kategori (menu.categories[].name)."),
        ("Menu", "category_available", "Apakah kategori sedang buka."),
        ("Menu", "item_order", "Urutan item dalam kategori."),
        ("Menu", "menu", "Nama item (items[].name) — sudah di-trim."),
        ("Menu", "description", "Deskripsi item (HTML dibersihkan)."),
        ("Menu", "price_before_promo", "Harga normal IDR (priceInMinorUnit ÷ 100)."),
        ("Menu", "price_after_promo", "Harga setelah diskon (discountedPriceInMin ÷ 100). Jatuh kembali ke harga normal jika tidak ada promo."),
        ("Menu", "promo_amount", "Nominal potongan = price_before − price_after (kosong bila tanpa promo)."),
        ("Menu", "promo_percentage", "Persentase diskon."),
        ("Menu", "takeaway_price", "Harga untuk takeaway."),
        ("Menu", "takeaway_discounted", "Harga takeaway setelah diskon."),
        ("Menu", "campaign_name", "Nama campaign promo yang menempel ke item."),
        ("Menu", "campaign_id", "ID campaign promo."),
        ("Menu", "campaign_start", "Waktu mulai campaign (Asia/Jakarta)."),
        ("Menu", "campaign_end", "Waktu berakhir campaign (Asia/Jakarta)."),
        ("Menu", "available", "True = tersedia, False = habis."),
        ("Menu", "modifier_group_count", "Jumlah grup add-on."),
        ("Menu", "modifier_total_options", "Total semua opsi add-on di seluruh grup."),
        ("Menu", "image_url", "URL gambar utama."),
        ("Menu", "image_fallback", "URL gambar fallback."),
        ("Menu", "item_id", "ID internal Grab untuk item menu."),
        ("Menu", "merchant_id", "ID internal Grab untuk merchant."),
        ("Menu", "is_duplicate_appearance", "True jika item yang sama muncul di kategori lain."),
        ("Modifiers", "item / item_id", "Item pemilik modifier."),
        ("Modifiers", "group", "Nama grup modifier."),
        ("Modifiers", "group_selection_min/max", "Min & max pilihan yang bisa dipilih customer."),
        ("Modifiers", "group_available", "Status aktif grup modifier."),
        ("Modifiers", "modifier / modifier_id", "Nama & ID opsi."),
        ("Modifiers", "price", "Harga tambahan IDR."),
        ("Modifiers", "available", "Opsi tersedia atau tidak."),
        ("Modifiers", "sort_order", "Urutan tampilan."),
        ("Promotions", "campaign_id / name", "ID dan nama campaign."),
        ("Promotions", "level", "item / merchant / offer_highlight."),
        ("Promotions", "status", "ongoing, visible, dll."),
        ("Promotions", "priority", "low/medium/high."),
        ("Promotions", "start / end", "Periode berlaku (Asia/Jakarta)."),
        ("Promotions", "terms", "Syarat & ketentuan."),
        ("Promotions", "decision_id", "ID attribution untuk tracking."),
        ("Merchant", "Rating / Vote Count", "Rating toko & jumlah pemberi rating."),
        ("Merchant", "ETA", "Estimasi waktu pengantaran (menit)."),
        ("Merchant", "Distance / Radius", "Jarak (km) dari lat/long request dan radius delivery (m)."),
        ("Merchant", "Opening Hours", "Jam buka per hari."),
        ("Merchant", "Hero/Small Photo", "Aset visual toko dari CDN Grab."),
        ("Merchant", "Share Link", "Link share publik."),
        ("Dietary", "id / name", "Kategori diet."),
        ("Dietary", "description", "Penjelasan kategori."),
        ("Dietary", "show_disclaimer", "Apakah Grab menampilkan disclaimer."),
    ]
    return pd.DataFrame(rows, columns=["Sheet", "Column", "Explanation"])
