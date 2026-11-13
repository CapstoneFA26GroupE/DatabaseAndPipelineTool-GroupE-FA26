import math
from collections import defaultdict
from typing import Generic, TypeVar

EARTH_RADIUS_M = 6_371_000.0

T = TypeVar("T")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # this returns the great-circle distance between two gps points in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


class LocalProjection:
    # this turns lat/lon into flat x/y meters around a reference point, accurate enough for a city-sized area

    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0 = lat0
        self.lon0 = lon0
        self._m_per_deg_lat = math.pi * EARTH_RADIUS_M / 180.0
        self._m_per_deg_lon = self._m_per_deg_lat * math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self._m_per_deg_lon, (lat - self.lat0) * self._m_per_deg_lat

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        return self.lat0 + y / self._m_per_deg_lat, self.lon0 + x / self._m_per_deg_lon


class GridIndex(Generic[T]):
    # this is a simple spatial index: items are bucketed into square cells so nearby lookups stay fast

    def __init__(self, cell_m: float) -> None:
        self.cell_m = cell_m
        self._cells: dict[tuple[int, int], list[tuple[float, float, T]]] = defaultdict(list)

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return int(math.floor(x / self.cell_m)), int(math.floor(y / self.cell_m))

    def insert(self, x: float, y: float, item: T) -> None:
        self._cells[self._cell(x, y)].append((x, y, item))

    def query_radius(self, x: float, y: float, radius_m: float) -> list[tuple[float, T]]:
        # this returns (distance, item) for every item within radius_m, nearest first
        cx, cy = self._cell(x, y)
        reach = int(math.ceil(radius_m / self.cell_m))
        found: list[tuple[float, T]] = []
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for ix, iy, item in self._cells.get((gx, gy), ()):
                    dist = math.hypot(ix - x, iy - y)
                    if dist <= radius_m:
                        found.append((dist, item))
        found.sort(key=lambda pair: pair[0])
        return found
