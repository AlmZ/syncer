#!/usr/bin/env python3
"""CLI for syncing playlists from Yandex Music to Tidal."""

import argparse
import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from simple_term_menu import TerminalMenu

from syncer.clients import TidalClient, YandexMusicClient
from syncer.config import Config
from syncer.constants import (
    TRACK_DISPLAY_MAX_LEN,
    TRACK_DISPLAY_TRUNCATE_LEN,
    DEFAULT_SEARCH_WORKERS,
    setup_logging,
    get_logger,
)
from syncer.models import Track
from syncer.service import FuzzyMatch, MatchQuality, SyncService

console = Console()
logger = get_logger("cli")


def truncate_text(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) > max_len:
        return text[:max_len - 1] + "…"
    return text


def multi_select_menu(
    items: list[str],
    title: str,
    hint: str,
    preselected: Optional[list[int]] = None,
) -> list[int]:
    """
    Show a multi-select menu and return selected indices.

    Args:
        items: List of menu items to display
        title: Title to show above the menu
        hint: Hint text for controls
        preselected: Indices to pre-select (default: none)

    Returns:
        List of selected indices
    """
    # Clear any progress line
    print("\r" + " " * 80 + "\r", end="")

    console.print(f"\n[bold yellow]{title}[/]")
    console.print(f"[dim]{hint}[/]\n")

    menu = TerminalMenu(
        items,
        multi_select=True,
        show_multi_select_hint=True,
        multi_select_select_on_accept=False,
        multi_select_empty_ok=True,
        preselected_entries=preselected or [],
    )

    selected_indices = menu.show()

    if selected_indices is None:
        return []

    if isinstance(selected_indices, int):
        selected_indices = (selected_indices,)

    return list(selected_indices)


def select_fuzzy_matches(matches: list[FuzzyMatch]) -> list[int]:
    """Show fuzzy matches and let user select which to include using Space."""
    if not matches:
        return []

    # Sort by quality: GOOD first, then MEDIUM, then BAD
    quality_order = {MatchQuality.GOOD: 0, MatchQuality.MEDIUM: 1, MatchQuality.BAD: 2}
    sorted_matches = sorted(matches, key=lambda m: quality_order[m.quality])

    # Count by quality
    good_count = sum(1 for m in sorted_matches if m.quality == MatchQuality.GOOD)
    medium_count = sum(1 for m in sorted_matches if m.quality == MatchQuality.MEDIUM)
    bad_count = sum(1 for m in sorted_matches if m.quality == MatchQuality.BAD)

    # Build menu items with quality indicator
    menu_items = []
    for i, match in enumerate(sorted_matches):
        original = f"{match.original.artist} - {match.original.title}"
        found = f"{match.found_artist} - {match.found_title}"

        # Truncate to fit in terminal
        original = truncate_text(original, TRACK_DISPLAY_MAX_LEN)
        found = truncate_text(found, TRACK_DISPLAY_MAX_LEN)

        # Quality indicator
        if match.quality == MatchQuality.GOOD:
            indicator = "✓"
        elif match.quality == MatchQuality.MEDIUM:
            indicator = "?"
        else:
            indicator = "✗"

        # Duration info
        duration_info = ""
        if match.original.duration_sec and match.found_duration_sec:
            orig_dur = match.original.duration_str
            found_mins = match.found_duration_sec // 60
            found_secs = match.found_duration_sec % 60
            found_dur = f"{found_mins}:{found_secs:02d}"
            if match.duration_warning:
                duration_info = f" ⚠{orig_dur}→{found_dur}"
            else:
                duration_info = f" {orig_dur}≈{found_dur}"

        menu_items.append(f"{indicator} {original} → {found}{duration_info}")

    # Show statistics
    title = f"Fuzzy-совпадения: {len(sorted_matches)}"
    stats_line = f"[green]✓ Надёжные: {good_count}[/]  [yellow]? Возможные: {medium_count}[/]  [red]✗ Сомнительные: {bad_count}[/]"
    console.print(f"\n[bold yellow]{title}[/]")
    console.print(stats_line)
    hint = "↑↓ навигация • Space выбор • Enter подтвердить • a все • n ничего"
    console.print(f"[dim]{hint}[/]\n")

    menu = TerminalMenu(
        menu_items,
        multi_select=True,
        show_multi_select_hint=True,
        multi_select_select_on_accept=False,
        multi_select_empty_ok=True,
    )

    selected_indices = menu.show()

    if selected_indices is None:
        return []

    if isinstance(selected_indices, int):
        selected_indices = (selected_indices,)

    return [sorted_matches[i].index for i in selected_indices]


def select_playlist(playlists) -> int:
    """Playlist selection with terminal menu."""
    console.print()
    console.print("[bold]Ваши плейлисты Yandex[/]")
    console.print("[dim]↑↓ навигация • Enter выбор[/]\n")

    menu_items = []
    for pl in playlists:
        track_count = pl.track_count if hasattr(pl, 'track_count') and pl.track_count else "?"
        menu_items.append(f"{pl.name} ({track_count} треков)")

    menu = TerminalMenu(menu_items)
    selected = menu.show()

    return selected if selected is not None else -1


def select_tracks_to_remove(tracks: list[tuple[str, str]]) -> list[int]:
    """Show tracks to remove and let user select which to delete using Space."""
    if not tracks:
        return []

    menu_items = []
    for artist, title in tracks:
        item = f"{artist} - {title}"
        item = truncate_text(item, TRACK_DISPLAY_TRUNCATE_LEN)
        menu_items.append(f"🗑 {item}")

    # Pre-select all for removal
    preselected = list(range(len(tracks)))

    title = f"Найдено {len(tracks)} треков для удаления"
    hint = "↑↓ навигация • Space выбор • Enter подтвердить • a все • n ничего"

    # Show header
    console.print(f"\n[bold red]{title}[/]")
    console.print("[dim]Этих треков нет в Yandex Music плейлисте[/]")
    console.print(f"[dim]{hint}[/]\n")

    menu = TerminalMenu(
        menu_items,
        multi_select=True,
        show_multi_select_hint=True,
        multi_select_select_on_accept=False,
        multi_select_empty_ok=True,
        preselected_entries=preselected,
    )

    selected_indices = menu.show()

    if selected_indices is None:
        return []

    if isinstance(selected_indices, int):
        selected_indices = (selected_indices,)

    return list(selected_indices)


def progress_callback(current: int, total: int, track: Track) -> None:
    """Show sync progress."""
    percent = (current / total * 100) if total > 0 else 0
    track_info = truncate_text(f"{track.artist} - {track.title}", 35)
    print(f"\r[{current}/{total}] {percent:.0f}% - {track_info:<35}", end="", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Синхронизация плейлистов из Yandex Music в Tidal"
    )
    parser.add_argument(
        "--yandex-token",
        help="Токен Yandex Music (сохраняется после первого использования)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Авто режим: только точные совпадения, без подтверждений",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_SEARCH_WORKERS,
        help=f"Количество параллельных потоков поиска (по умолчанию: {DEFAULT_SEARCH_WORKERS})",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Удалить треки из Tidal, которых нет в Yandex",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Подробный вывод для отладки",
    )
    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)
    logger.info("Запуск синхронизации")

    console.print(Panel.fit(
        "[bold blue]Yandex Music → Tidal Sync[/]",
        border_style="blue"
    ))

    # Load or save config
    config = Config.load()

    if args.yandex_token:
        config.yandex_token = args.yandex_token
        config.save()
        console.print("[green]Токен Yandex сохранён в конфиг[/]")
    elif not config.yandex_token:
        console.print("[red]Ошибка: укажите --yandex-token (нужен только один раз)[/]")
        sys.exit(1)

    console.print("Подключаемся к Yandex Music...", style="dim")
    try:
        yandex = YandexMusicClient(config.yandex_token)
        logger.info("Подключение к Yandex Music успешно")
    except Exception as e:
        logger.error(f"Ошибка подключения к Yandex Music: {e}")
        console.print(f"[red]Ошибка подключения к Yandex Music: {e}[/]")
        console.print("[yellow]Возможно токен устарел. Укажите новый через --yandex-token[/]")
        sys.exit(1)

    console.print("Загружаем плейлисты...", style="dim")
    playlists = yandex.get_playlists()

    if not playlists:
        console.print("[yellow]Плейлисты не найдены.[/]")
        sys.exit(0)

    selected_idx = select_playlist(playlists)
    if selected_idx < 0:
        console.print("[red]Неверный выбор.[/]")
        sys.exit(1)

    selected = playlists[selected_idx]
    logger.info(f"Выбран плейлист: {selected.name}")

    console.print("\nПодключаемся к Tidal...", style="dim")
    tidal = TidalClient()
    if not tidal.login():
        console.print("[red]Ошибка авторизации в Tidal.[/]")
        sys.exit(1)

    # Ask for Tidal playlist name
    tidal_name = Prompt.ask(
        f"\n[bold]Название плейлиста в Tidal[/]",
        default=selected.name,
    )

    # Check if playlist exists
    existing_playlist = tidal.find_playlist_by_name(tidal_name)
    if existing_playlist:
        console.print(f"[yellow]Плейлист '{tidal_name}' существует — добавим только новые треки[/]")
    else:
        console.print(f"[green]Плейлист '{tidal_name}' будет создан[/]")

    console.print(f"\nЗагружаем плейлист: [cyan]{selected.name}[/]...", style="dim")
    playlist = yandex.get_playlist_with_tracks(selected.id)
    console.print(f"Найдено [bold]{len(playlist.tracks)}[/] треков.")

    if args.auto:
        console.print("[dim]Режим: только точные совпадения[/]\n")
    else:
        console.print("[dim]Режим: fuzzy поиск с выбором[/]\n")

    # Sync favorites = also like tracks in Tidal
    is_favorites = selected.id == "favorites"
    if is_favorites:
        console.print("[dim]Треки также будут лайкнуты в Tidal[/]")
    if args.cleanup:
        console.print("[dim]Удалённые треки будут удалены из Tidal[/]")
    console.print()

    service = SyncService(yandex, tidal)
    result = service.sync_playlist(
        playlist,
        tidal_playlist_name=tidal_name,
        progress_callback=progress_callback,
        fuzzy_selector=None if args.auto else select_fuzzy_matches,
        workers=args.workers,
        exact_only=args.auto,
        like_tracks=is_favorites,
        cleanup_deleted=args.cleanup,
        cleanup_selector=None if args.auto else select_tracks_to_remove,
    )
    print()  # New line after progress

    # Results
    console.print()
    results_table = Table(title=f"Результаты для '{result.playlist_name}'", show_header=False)
    results_table.add_column("Метрика", style="bold")
    results_table.add_column("Значение", justify="right")

    results_table.add_row("Всего треков", str(result.total_tracks))

    if result.is_delta:
        results_table.add_row("Уже в Tidal", str(result.skipped_tracks))
        results_table.add_row("Добавлено новых", f"[green]{result.found_tracks}[/]")
    else:
        results_table.add_row("Найдено в Tidal", f"[green]{result.found_tracks}[/]")

    # Match statistics
    if result.match_stats:
        stats = result.match_stats
        if stats.exact > 0:
            results_table.add_row("  ├ Точные", f"[green]{stats.exact}[/]")
        if stats.fuzzy_good > 0:
            results_table.add_row("  ├ Fuzzy надёжные", f"[green]{stats.fuzzy_good}[/]")
        if stats.fuzzy_medium > 0:
            results_table.add_row("  ├ Fuzzy возможные", f"[yellow]{stats.fuzzy_medium}[/]")
        if stats.fuzzy_bad > 0:
            results_table.add_row("  └ Fuzzy сомнительные", f"[red]{stats.fuzzy_bad}[/]")

    results_table.add_row("Не найдено", f"[red]{len(result.not_found_tracks)}[/]")
    if result.removed_tracks > 0:
        results_table.add_row("Удалено из Tidal", f"[red]🗑 {result.removed_tracks}[/]")
    if result.liked_tracks > 0:
        results_table.add_row("Лайкнуто в Tidal", f"[magenta]♥ {result.liked_tracks}[/]")
    results_table.add_row("Успешность", f"[bold]{result.success_rate:.1f}%[/]")

    console.print(results_table)

    if result.not_found_tracks:
        console.print("\n[bold red]Не найдены в Tidal:[/]")
        for track in result.not_found_tracks[:10]:
            console.print(f"  [dim]•[/] {track.artist} - {track.title}")
        if len(result.not_found_tracks) > 10:
            console.print(f"  [dim]... и ещё {len(result.not_found_tracks) - 10}[/]")

    console.print("\n[bold green]Синхронизация завершена![/]")
    logger.info("Синхронизация завершена успешно")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Отменено[/]")
        sys.exit(130)
    except Exception as e:
        logger.exception("Критическая ошибка")
        console.print(f"\n[bold red]Ошибка:[/] {e}")
        sys.exit(1)
