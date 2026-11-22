"""Async client for the EcoLife cloud REST API.

Mirrors the request format of the official "EcoLife Healthy Breathing" app
(ecoApi.webService in the Cordova bundle):

* every call is an HTTP POST with a JSON body,
* the session token is always sent in the body as ``token`` (no header),
* ``status == 0`` in the response means success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_URL = "https://rest.ecolife.eu.com:58200/EcoLife/"
PATH_LOGIN = "User/login"
PATH_USER_SEARCH = "MeasurePoint/userSearch"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=utf-8",
}
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

STATUS_OK = 0


class EcolifeError(Exception):
    """Base error for the EcoLife API."""


class EcolifeConnectionError(EcolifeError):
    """The EcoLife server could not be reached or replied with garbage."""


class EcolifeAuthError(EcolifeError):
    """The EcoLife server rejected the credentials."""


@dataclass(frozen=True, slots=True)
class Measurement:
    """A single reading from the ``latest`` map of a measure point."""

    measure_type: str
    value: float | None
    unit: str | None
    norm: float | None
    value_percentage: float | None


@dataclass(slots=True)
class MeasurePoint:
    """An EcoLife measure point (one physical sensor)."""

    id: str
    name: str
    uuids: list[str]
    observed: bool
    site: str | None
    origin: str | None
    range: str | None
    latitude: float | None
    longitude: float | None
    last_update: datetime | None
    measurements: dict[str, Measurement] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_last_update(value: Any) -> datetime | None:
    """Parse ``lastUpdate``.

    The server serialises a Java ``LocalDateTime`` (in UTC) as an object with
    ``year``, ``monthValue``, ``dayOfMonth``, ``hour``, ... fields. Plain epoch
    milliseconds and ISO strings are accepted too, just in case.
    """
    try:
        if isinstance(value, dict):
            return datetime(
                int(value["year"]),
                int(value["monthValue"]),
                int(value["dayOfMonth"]),
                int(value.get("hour", 0)),
                int(value.get("minute", 0)),
                int(value.get("second", 0)),
                int(value.get("nano", 0)) // 1000,
                tzinfo=UTC,
            )
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (KeyError, TypeError, ValueError, OverflowError):
        _LOGGER.debug("Unparseable lastUpdate: %s", value)
    return None


def _parse_measure_point(raw: dict[str, Any], observed: bool) -> MeasurePoint | None:
    mp_id = raw.get("id")
    if not mp_id:
        return None
    location = raw.get("location") or {}
    measurements: dict[str, Measurement] = {}
    for key, item in (raw.get("latest") or {}).items():
        if not isinstance(item, dict):
            continue
        measure_type = str(item.get("measureType") or key)
        measurements[measure_type] = Measurement(
            measure_type=measure_type,
            value=_to_float(item.get("value")),
            unit=item.get("unit"),
            norm=_to_float(item.get("norm")),
            value_percentage=_to_float(item.get("valuePercentage")),
        )
    return MeasurePoint(
        id=str(mp_id),
        name=raw.get("name") or str(mp_id),
        uuids=[str(u) for u in raw.get("uuids") or []],
        observed=observed,
        site=raw.get("site"),
        origin=raw.get("origin"),
        range=raw.get("range"),
        latitude=_to_float(location.get("latitude")),
        # sic: the API spells it "longtitude"
        longitude=_to_float(location.get("longtitude", location.get("longitude"))),
        last_update=_parse_last_update(raw.get("lastUpdate")),
        measurements=measurements,
        raw=raw,
    )


class EcolifeApi:
    """Minimal EcoLife cloud client (login + list user's measure points)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        locale: str = "en",
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._email = email
        self._password = password
        self._locale = locale
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        """Return the current user token."""
        return self._token

    async def _post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        # The app always injects the current token into the body, even for login.
        payload = {**params, "token": self._token}
        url = f"{API_URL}{path}"
        try:
            async with self._session.post(
                url, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise EcolifeConnectionError(
                        f"{path} returned HTTP {resp.status}: {text[:200]}"
                    )
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise EcolifeConnectionError(f"{path} request failed: {err}") from err
        if not isinstance(data, dict):
            raise EcolifeConnectionError(f"{path} returned unexpected payload")
        return data

    async def async_login(self) -> str:
        """Log in and store the user token (``User/login``)."""
        self._token = None
        data = await self._post(
            PATH_LOGIN,
            {
                "email": self._email,
                "password": self._password,
                "fcmToken": None,
                "locale": self._locale,
            },
        )
        token = data.get("data")
        if data.get("status") != STATUS_OK or not isinstance(token, str) or not token:
            # The server answers {"status": 1, "data": "emailPasswordError"}
            raise EcolifeAuthError(str(token or "login rejected"))
        self._token = token
        return token

    async def _user_search(self) -> dict[str, Any]:
        return await self._post(PATH_USER_SEARCH, {})

    async def async_get_measure_points(self) -> dict[str, MeasurePoint]:
        """Return the user's own and observed measure points (``userSearch``).

        Like the app, observed measure points are listed alongside the owned
        ones. If the token is no longer accepted, log in again once.
        """
        if self._token is None:
            await self.async_login()
        data = await self._user_search()
        if data.get("status") != STATUS_OK:
            _LOGGER.debug("userSearch rejected token (status %s), re-login", data.get("status"))
            await self.async_login()
            data = await self._user_search()
            if data.get("status") != STATUS_OK:
                raise EcolifeError(f"userSearch failed with status {data.get('status')}")

        result: dict[str, MeasurePoint] = {}
        for raw in data.get("observedMPs") or []:
            if mp := _parse_measure_point(raw, observed=True):
                result[mp.id] = mp
        # Owned measure points take precedence over observed duplicates.
        for raw in data.get("measurePoints") or []:
            if mp := _parse_measure_point(raw, observed=False):
                result[mp.id] = mp
        return result
