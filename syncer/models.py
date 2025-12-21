from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Track:
    """Normalized track representation used across providers."""

    name: str
    artists: tuple[str, ...]
    provider_id: str

    @property
    def signature(self) -> str:
        """Stable signature used to compare tracks across services."""

        artist_part = ",".join(artist.lower().strip() for artist in self.artists)
        return f"{self.name.lower().strip()}::{artist_part}"

    @classmethod
    def deduplicate(cls, tracks: Iterable["Track"]) -> list["Track"]:
        seen: set[str] = set()
        unique: list[Track] = []
        for track in tracks:
            if track.signature in seen:
                continue
            seen.add(track.signature)
            unique.append(track)
        return unique
