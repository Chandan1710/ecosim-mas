"""
world.py — the town: places, what each place is for, its map footprint and roads.

The same map data is served to the frontend (GET /town/map) so the backend and
the 2D scene agree on where everything is. Coordinates are tile units on a
TOWN_W x TOWN_H grid; each building has a rectangle and a door tile that sits
on a road, and agents walk road tiles between doors.

Nothing here makes decisions. Agents decide where to go; this module only says
what exists and what can be done there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

TOWN_W = 64
TOWN_H = 40

PHASES = ("morning", "afternoon", "evening")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Roads: horizontal rows and vertical columns that are road tiles end to end.
ROAD_ROWS = (4, 14, 25, 35)
ROAD_COLS = (3, 18, 33, 47, 60)

# Spending categories. Essentials are what a household must buy to get by.
ESSENTIAL = ("groceries", "medicine", "fuel")
DISCRETIONARY = ("eating_out", "shopping", "entertainment")


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    kind: str                      # home | shop | work | bank | public
    rect: Tuple[int, int, int, int]  # x, y, w, h in tiles
    door: Tuple[int, int]            # road tile in front of the entrance
    sells: Tuple[str, ...] = ()      # spending categories available here
    price_index: float = 1.0         # relative to the town average for what it sells
    closed_days: Tuple[str, ...] = ()
    activities: Tuple[str, ...] = ()
    description: str = ""

    def is_open(self, weekday: str) -> bool:
        return weekday not in self.closed_days

    def to_dict(self) -> dict:
        x, y, w, h = self.rect
        return {
            "id": self.id, "name": self.name, "kind": self.kind,
            "rect": {"x": x, "y": y, "w": w, "h": h},
            "door": {"x": self.door[0], "y": self.door[1]},
            "sells": list(self.sells), "activities": list(self.activities),
            "closed_days": list(self.closed_days), "description": self.description,
        }


def _p(id, name, kind, rect, door, **kw) -> Place:
    return Place(id=id, name=name, kind=kind, rect=rect, door=door, **kw)


# Block layout (between roads):
#   rows: 5-13, 15-24, 26-34      cols: 4-17, 19-32, 34-46, 48-59
PLACES: Dict[str, Place] = {p.id: p for p in [
    # ── homes ────────────────────────────────────────────────────────────────
    _p("shanti_apts", "Shanti Nagar Apartments", "home", (5, 6, 11, 7), (10, 4),
       activities=("rest", "socialise"), description="Mid-rise flats for salaried families."),
    _p("old_town", "Old Town Houses", "home", (5, 16, 11, 8), (10, 14),
       activities=("rest", "socialise"), description="Older family homes, many owner-occupied."),
    _p("labour_colony", "Labour Colony", "home", (49, 27, 10, 7), (53, 35),
       activities=("rest", "socialise"), description="One-room rentals for daily-wage and migrant workers."),
    _p("lake_view", "Lake View Residency", "home", (49, 16, 10, 8), (53, 14),
       activities=("rest", "socialise"), description="Newer apartments with home-loan buyers."),

    # ── shops ────────────────────────────────────────────────────────────────
    _p("kirana", "Ravi Kirana Store", "shop", (20, 6, 5, 4), (22, 4), sells=("groceries",),
       price_index=1.0, activities=("shop",),
       description="Neighbourhood grocery. Lets regulars buy on credit (khata)."),
    _p("supermarket", "FreshMart Supermarket", "shop", (26, 6, 6, 6), (29, 4), sells=("groceries",),
       price_index=0.95, activities=("shop",), description="Cheaper per kilo, better for bulk buying."),
    _p("market", "Sabzi Market", "shop", (20, 27, 12, 6), (26, 25), sells=("groceries",),
       price_index=0.88, closed_days=("Sunday",), activities=("shop", "socialise"),
       description="Open-air vegetable and grain market; cheapest, busy, chatty."),
    _p("pharmacy", "City Pharmacy", "shop", (35, 6, 5, 4), (37, 4), sells=("medicine",),
       activities=("shop",), description="Medicines and basic health supplies."),
    _p("fuel_station", "Highway Fuel Station", "shop", (41, 6, 5, 6), (43, 4), sells=("fuel",),
       activities=("shop",), description="Petrol and diesel."),
    _p("cafe", "Corner Café", "shop", (35, 16, 5, 4), (37, 14), sells=("eating_out",),
       activities=("eat_out", "socialise"), description="Tea, snacks and meals."),
    _p("restaurant", "Spice Garden Restaurant", "shop", (41, 16, 5, 5), (43, 14), sells=("eating_out",),
       price_index=1.6, activities=("eat_out", "socialise"), description="Sit-down family dinners."),
    _p("mall", "Town Mall & Cinema", "shop", (35, 27, 11, 7), (40, 25), sells=("shopping", "entertainment"),
       activities=("shop", "leisure", "socialise"), description="Clothes, electronics and a cinema."),

    # ── work ─────────────────────────────────────────────────────────────────
    _p("tech_park", "TechPark Offices", "work", (49, 5, 10, 8), (53, 4), activities=("work",),
       closed_days=("Saturday", "Sunday"), description="IT and back-office jobs."),
    _p("factory", "Garment Factory", "work", (5, 27, 11, 7), (10, 25), activities=("work",),
       closed_days=("Sunday",), description="Shift work, paid daily; shifts depend on orders."),
    _p("construction", "Metro Construction Site", "work", (5, 36, 11, 3), (10, 35), activities=("work",),
       closed_days=("Sunday",), description="Daily-wage work when there is work."),
    _p("school", "Government School & College", "work", (20, 16, 6, 8), (22, 14), activities=("work", "study"),
       closed_days=("Sunday",), description="Teachers work here; students attend."),
    _p("clinic", "Community Clinic", "work", (27, 16, 5, 5), (29, 14), sells=("medicine",), price_index=1.1,
       activities=("work", "shop"), description="Doctor visits and nursing staff."),
    _p("auto_stand", "Auto & Delivery Stand", "work", (35, 36, 11, 3), (40, 35), activities=("work", "socialise"),
       description="Auto drivers and delivery riders start and end shifts here."),

    # ── money and public space ───────────────────────────────────────────────
    _p("bank", "Town Cooperative Bank", "bank", (27, 36, 5, 3), (29, 35), activities=("bank",),
       closed_days=("Sunday",), description="Savings, loans and EMIs."),
    _p("park", "Lake Park", "public", (20, 36, 6, 3), (22, 35), activities=("leisure", "socialise"),
       description="Free to visit; people walk and talk here."),
]}

HOME_IDS = [p.id for p in PLACES.values() if p.kind == "home"]


def place(pid: str) -> Optional[Place]:
    return PLACES.get(pid)


def places_selling(category: str) -> List[Place]:
    return [p for p in PLACES.values() if category in p.sells]


def weekday_of(day: int, start_weekday: int = 0) -> str:
    """Day 1 of the run is WEEKDAYS[start_weekday]."""
    return WEEKDAYS[(start_weekday + day - 1) % 7]


def road_tiles() -> List[Tuple[int, int]]:
    tiles = set()
    for r in ROAD_ROWS:
        for x in range(ROAD_COLS[0], ROAD_COLS[-1] + 1):
            tiles.add((x, r))
    for c in ROAD_COLS:
        for y in range(ROAD_ROWS[0], ROAD_ROWS[-1] + 1):
            tiles.add((c, y))
    return sorted(tiles)


def map_json() -> dict:
    """Everything the frontend needs to draw the town."""
    return {
        "width": TOWN_W, "height": TOWN_H,
        "roads": [{"x": x, "y": y} for x, y in road_tiles()],
        "road_rows": list(ROAD_ROWS), "road_cols": list(ROAD_COLS),
        "places": [p.to_dict() for p in PLACES.values()],
        "phases": list(PHASES),
    }


def validate_map() -> List[str]:
    """Sanity checks used by tests: doors on roads, rects inside the grid, no overlaps."""
    problems = []
    roads = set(road_tiles())
    cells: Dict[Tuple[int, int], str] = {}
    doors: Dict[Tuple[int, int], str] = {}
    for p in PLACES.values():
        if p.door in doors:
            problems.append(f"{p.id} shares a door tile with {doors[p.door]}")
        doors[p.door] = p.id
        x, y, w, h = p.rect
        if x < 0 or y < 0 or x + w > TOWN_W or y + h > TOWN_H:
            problems.append(f"{p.id} outside the grid")
        if p.door not in roads:
            problems.append(f"{p.id} door {p.door} is not on a road")
        for cx in range(x, x + w):
            for cy in range(y, y + h):
                if (cx, cy) in roads:
                    problems.append(f"{p.id} covers road tile {(cx, cy)}")
                    break
                if (cx, cy) in cells:
                    problems.append(f"{p.id} overlaps {cells[(cx, cy)]}")
                    break
                cells[(cx, cy)] = p.id
    return sorted(set(problems))
