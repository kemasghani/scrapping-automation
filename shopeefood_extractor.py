"""ShopeeFood mobile-API menu extractor.

Workflow:
  1. Capture a `get_delivery_dishes` (or equivalent) response from the
     ShopeeFood Android app via mitmproxy with SSL pinning bypassed
     (Frida + frida-multiple-unpinning).
  2. Save the JSON body to a file, then run:
         python shopeefood_extractor.py path/to/capture.json
     or import `extract_menu` and pass the parsed dict directly.

The shape below matches the `reply` envelope used by the
`gappapi.deliverynow.vn` / `foody` mobile endpoints. Field names drift
between regions (VN vs ID) and app versions — adjust `FIELD_MAP` as
needed.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Iterable


FIELD_MAP = {
    "menu_root":       ("reply", "menu_infos"),
    "dishes":          "dishes",
    "category_name":   "dish_type_name",
    "dish_id":         "id",
    "dish_name":       "name",
    "description":     "description",
    "photo":           "photos",
    "price_value":     ("price", "value"),
    "price_display":   ("price_display",),
    "discount_price":  ("discount_price", "value"),
    "is_available":    "is_active",
    "options":         "options",
    "option_name":     "option_name",
    "min_select":      "min_select",
    "max_select":      "max_select",
    "option_items":    "option_items",
}


@dataclass
class ModifierItem:
    name: str
    price: float = 0.0


@dataclass
class ModifierGroup:
    name: str
    min_select: int = 0
    max_select: int = 1
    items: list[ModifierItem] = field(default_factory=list)


@dataclass
class Dish:
    id: int | str
    category: str
    name: str
    description: str
    price: float
    discount_price: float | None
    available: bool
    photo: str | None
    modifiers: list[ModifierGroup] = field(default_factory=list)


def _dig(obj: Any, path: str | tuple[str, ...], default=None):
    if isinstance(path, str):
        path = (path,)
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _photo_url(photos: Any) -> str | None:
    if isinstance(photos, list) and photos:
        first = photos[0]
        if isinstance(first, dict):
            return first.get("value") or first.get("url")
    return None


def _parse_modifiers(raw_options: Iterable[dict]) -> list[ModifierGroup]:
    groups: list[ModifierGroup] = []
    for opt in raw_options or []:
        items = [
            ModifierItem(
                name=it.get("name", ""),
                price=float(_dig(it, ("price", "value"), 0) or 0),
            )
            for it in opt.get(FIELD_MAP["option_items"], []) or []
        ]
        groups.append(ModifierGroup(
            name=opt.get(FIELD_MAP["option_name"], ""),
            min_select=int(opt.get(FIELD_MAP["min_select"], 0) or 0),
            max_select=int(opt.get(FIELD_MAP["max_select"], 1) or 1),
            items=items,
        ))
    return groups


def extract_menu(payload: dict) -> list[Dish]:
    menu_infos = _dig(payload, FIELD_MAP["menu_root"], []) or []
    dishes: list[Dish] = []
    for category in menu_infos:
        cat_name = category.get(FIELD_MAP["category_name"], "")
        for raw in category.get(FIELD_MAP["dishes"], []) or []:
            dishes.append(Dish(
                id=raw.get(FIELD_MAP["dish_id"]),
                category=cat_name,
                name=raw.get(FIELD_MAP["dish_name"], ""),
                description=raw.get(FIELD_MAP["description"], "") or "",
                price=float(_dig(raw, FIELD_MAP["price_value"], 0) or 0),
                discount_price=(
                    float(_dig(raw, FIELD_MAP["discount_price"], 0))
                    if _dig(raw, FIELD_MAP["discount_price"]) is not None
                    else None
                ),
                available=bool(raw.get(FIELD_MAP["is_available"], True)),
                photo=_photo_url(raw.get(FIELD_MAP["photo"])),
                modifiers=_parse_modifiers(raw.get(FIELD_MAP["options"], [])),
            ))
    return dishes


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: shopeefood_extractor.py <captured.json>", file=sys.stderr)
        return 2
    payload = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    dishes = extract_menu(payload)
    print(json.dumps([asdict(d) for d in dishes], ensure_ascii=False, indent=2))
    print(f"\n# {len(dishes)} dishes parsed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
