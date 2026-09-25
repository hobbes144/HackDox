"""The between-day HackDollar$ shop's rules — what's for sale, what it costs,
and what buying it does (#22, #23, #25; Endless economy #7).

Lifted out of BetweenDayScreen so the rules are testable without the TUI and
so the campaign and Endless share one shop that differs only where the
config says it should:

  • Endless puts a per-run random set of upgrades under MAINTENANCE.
  • Endless escalates the ⏱-capacity price with every purchase.
  • Endless sells a Site Patch (repair Site Health), also escalating.
  • Endless has more HackDox Credit slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .. import config
from .models import GameState

ItemKind = Literal["header", "credit", "capacity", "site_patch", "upgrade"]
Status = Literal["owned", "full", "maintenance", "afford", "poor"]


@dataclass(frozen=True)
class ShopItem:
    kind: ItemKind
    iid: str
    label: str
    desc: str = ""


def credit_cap(state: GameState) -> int:
    return (config.ENDLESS_HACKDOX_CREDIT_MAX if state.is_endless
            else config.HACKDOX_CREDIT_MAX)


def capacity_price(state: GameState) -> int:
    bought = state.shop_purchases.get("capacity", 0)
    step = config.SHOP_CAPACITY_PRICE_STEP if state.is_endless else 0
    return config.SHOP_PRICE_CAPACITY + step * bought


def site_patch_price(state: GameState) -> int:
    bought = state.shop_purchases.get("site_patch", 0)
    return config.SHOP_PRICE_SITE_PATCH + config.SHOP_SITE_PATCH_PRICE_STEP * bought


_UPGRADE_PRICE = {uid: price for uid, _l, price, _d in config.UPGRADE_CATALOG}


def price_of(state: GameState, item: ShopItem) -> int:
    if item.kind == "credit":
        return config.SHOP_PRICE_CREDIT
    if item.kind == "capacity":
        return capacity_price(state)
    if item.kind == "site_patch":
        return site_patch_price(state)
    if item.kind == "upgrade":
        return _UPGRADE_PRICE[item.iid]
    return 0


def items_for(state: GameState) -> list[ShopItem]:
    """The shop's rows, in display order, including non-buyable headers."""
    items: list[ShopItem] = [
        ShopItem("header", "", "General"),
        ShopItem("credit", "hackdox_credit", "HackDox Credit +1",
                 f"ground-truth reveal charge (max {credit_cap(state)} slots)"),
        ShopItem("capacity", "compute_capacity",
                 f"Compute Capacity +{config.COMPUTE_CAPACITY_STEP} ⏱",
                 "permanently raise the per-shift computing-hours budget"
                 + (" — costs more each time" if state.is_endless else "")),
    ]
    if state.is_endless:
        items.append(ShopItem(
            "site_patch", "site_patch",
            f"Site Patch +{config.SITE_PATCH_HEALTH:.0f}% ⛨",
            "repair Site Health overnight — costs more each time"))
    by_cat: dict[str, list[ShopItem]] = {c: [] for c in config.UPGRADE_CATEGORY_ORDER}
    for uid, label, _price, desc in config.UPGRADE_CATALOG:
        by_cat[config.UPGRADE_CATEGORY[uid]].append(
            ShopItem("upgrade", uid, label, desc))
    for cat in config.UPGRADE_CATEGORY_ORDER:
        if by_cat[cat]:
            items.append(ShopItem("header", "", cat))
            items.extend(by_cat[cat])
    return items


def status_of(state: GameState, item: ShopItem) -> Status:
    if item.kind == "upgrade":
        if item.iid in state.upgrades:
            return "owned"
        if item.iid in state.maintenance_upgrades:
            return "maintenance"
    if item.kind == "credit" and state.hackdox_credits >= credit_cap(state):
        return "full"
    if item.kind == "site_patch" and state.site_health >= config.SITE_HEALTH_MAX:
        return "full"
    return "afford" if state.hackdollars >= price_of(state, item) else "poor"


def buy(state: GameState, item: ShopItem) -> tuple[bool, str]:
    """Attempt a purchase. Mutates `state` only on success. Returns
    (succeeded, player-facing message)."""
    if item.kind == "header":
        return False, ""
    status = status_of(state, item)
    if status == "owned":
        return False, f"{item.label} already owned"
    if status == "maintenance":
        return False, f"{item.label} is under maintenance for this run"
    if status == "full":
        return False, ("credit slots full" if item.kind == "credit"
                       else "Site Health is already at full")
    price = price_of(state, item)
    if status == "poor":
        return False, (f"insufficient HackDollar$ — need {price}, "
                       f"have {state.hackdollars}")
    state.hackdollars -= price
    if item.kind == "upgrade":
        state.upgrades.add(item.iid)
    elif item.kind == "credit":
        state.hackdox_credits += 1
    elif item.kind == "capacity":
        state.compute_capacity += config.COMPUTE_CAPACITY_STEP
    elif item.kind == "site_patch":
        state.site_health = min(config.SITE_HEALTH_MAX,
                                state.site_health + config.SITE_PATCH_HEALTH)
    if item.kind in ("capacity", "site_patch"):
        state.shop_purchases[item.kind] = state.shop_purchases.get(item.kind, 0) + 1
    return True, f"purchased {item.label}  (−{price} HD$)"
