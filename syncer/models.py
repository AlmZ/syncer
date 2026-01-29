from dataclasses import dataclass
from typing import Optional


@dataclass
class Track:
    title: str
    artist: str
    album: Optional[str] = None
    duration_sec: Optional[int] = None  # Duration in seconds

    def search_query(self) -> str:
        return f"{self.artist} {self.title}"

    @property
    def duration_str(self) -> str:
        """Format duration as M:SS."""
        if self.duration_sec is None:
            return "?"
        mins = self.duration_sec // 60
        secs = self.duration_sec % 60
        return f"{mins}:{secs:02d}"


@dataclass
class Playlist:
    id: str
    name: str
    tracks: list[Track]
    track_count: Optional[int] = None

    def __str__(self) -> str:
        count = self.track_count if self.track_count is not None else len(self.tracks)
        return f"{self.name} ({count} tracks)"


@dataclass
class MatchStats:
    exact: int = 0
    fuzzy_good: int = 0
    fuzzy_medium: int = 0
    fuzzy_bad: int = 0

    @property
    def total_fuzzy(self) -> int:
        return self.fuzzy_good + self.fuzzy_medium + self.fuzzy_bad


@dataclass
class SyncResult:
    playlist_name: str
    total_tracks: int
    found_tracks: int
    not_found_tracks: list[Track]
    skipped_tracks: int = 0
    is_delta: bool = False
    match_stats: Optional[MatchStats] = None
    liked_tracks: int = 0  # Tracks liked in Tidal (for favorites sync)
    removed_tracks: int = 0  # Tracks removed from Tidal (deleted in Yandex)

    @property
    def synced_tracks(self) -> int:
        return self.skipped_tracks + self.found_tracks

    @property
    def success_rate(self) -> float:
        if self.total_tracks == 0:
            return 0.0
        return (self.synced_tracks / self.total_tracks) * 100
