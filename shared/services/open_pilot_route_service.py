import os
import time
from typing import Any

import httpx

from schemas.openpilot_route_metadata import OpenPilotRouteMetadata
from utilities.open_pilot_utilities import get_open_pilot_device_name_from_route_str, is_valid_route_str


class OpenPilotRouteService:
    def __init__(self) -> None:
        self.jwt_token = os.environ["COMMA_JWT"]
        self.auth_headers = {"Authorization": f"JWT {self.jwt_token}"}

    async def get_route_metadata(
        self,
        route_name: str,
    ) -> OpenPilotRouteMetadata | None:
        if not is_valid_route_str(route_name):
            raise ValueError(
                "Invalid route string. Expected format similar to "
                "db478799b6f9f210|00000044--2b2126c478"
            )

        dongle_id = get_open_pilot_device_name_from_route_str(route_name)
        timeout = httpx.Timeout(10.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                url=f"https://api.commadotai.com/v1/devices/{dongle_id}/routes_segments",
                headers=self.auth_headers,
                params={
                    "start": 0,
                    "end": int(time.time() * 1000),  # epoch time in ms
                },
            )
            resp.raise_for_status()
            response_json: list[Any] = resp.json()

        for raw_route in response_json:
            route_metadata = OpenPilotRouteMetadata.model_validate(raw_route)
            if route_metadata.fullname == route_name:
                return route_metadata

        return None