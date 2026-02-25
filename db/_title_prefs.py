"""Title preference tracking — learn which job titles users prefer to enrich."""

import logging

logger = logging.getLogger(__name__)


class TitlePrefsMixin:
    """Track selected/skipped job titles to learn user preferences."""

    def record_title_selections(
        self,
        selected_titles: list[str],
        skipped_titles: list[str],
    ) -> None:
        """Record which titles were selected and skipped during enrichment.

        Args:
            selected_titles: Job titles the user chose to enrich
            skipped_titles: Job titles the user skipped (at companies where another contact was chosen)
        """
        for raw_title in selected_titles:
            title = _normalize_title(raw_title)
            if not title:
                continue
            self.execute_write(
                """INSERT INTO title_preferences (title, selected_count, skipped_count, last_selected)
                   VALUES (?, 1, 0, CURRENT_TIMESTAMP)
                   ON CONFLICT(title) DO UPDATE SET
                       selected_count = selected_count + 1,
                       last_selected = CURRENT_TIMESTAMP""",
                (title,),
            )

        for raw_title in skipped_titles:
            title = _normalize_title(raw_title)
            if not title:
                continue
            self.execute_write(
                """INSERT INTO title_preferences (title, selected_count, skipped_count, last_selected)
                   VALUES (?, 0, 1, NULL)
                   ON CONFLICT(title) DO UPDATE SET
                       skipped_count = skipped_count + 1""",
                (title,),
            )

        total = len(selected_titles) + len(skipped_titles)
        logger.info(
            "Title preferences recorded: %d selected, %d skipped (%d total)",
            len(selected_titles), len(skipped_titles), total,
        )

    def get_title_preferences(self) -> dict[str, float]:
        """Get all title preference scores.

        Returns:
            Dict mapping normalized title → preference score (0.0–1.0).
            Higher = more preferred. Titles never seen are not included.
        """
        rows = self.execute(
            "SELECT title, selected_count, skipped_count FROM title_preferences"
        )
        prefs = {}
        for title, selected, skipped in rows:
            total = selected + skipped
            if total > 0:
                prefs[title] = selected / total
        return prefs

    def get_title_preference(self, raw_title: str) -> float | None:
        """Get preference score for a single title.

        Returns:
            Preference score (0.0–1.0), or None if title never seen.
        """
        title = _normalize_title(raw_title)
        if not title:
            return None
        rows = self.execute(
            "SELECT selected_count, skipped_count FROM title_preferences WHERE title = ?",
            (title,),
        )
        if not rows:
            return None
        selected, skipped = rows[0]
        total = selected + skipped
        return selected / total if total > 0 else 0.5

    def get_title_stats(self) -> list[dict]:
        """Get all title preference stats for display.

        Returns:
            List of dicts with title, selected_count, skipped_count, preference, last_selected.
        """
        rows = self.execute(
            """SELECT title, selected_count, skipped_count, last_selected
               FROM title_preferences
               ORDER BY selected_count DESC, skipped_count ASC"""
        )
        results = []
        for title, selected, skipped, last_selected in rows:
            total = selected + skipped
            results.append({
                "title": title,
                "selected_count": selected,
                "skipped_count": skipped,
                "preference": selected / total if total > 0 else 0.5,
                "last_selected": last_selected,
            })
        return results


def _normalize_title(raw_title: str | None) -> str:
    """Normalize a job title for consistent matching.

    Lowercase, strip whitespace. Exact match for now — fuzzy grouping later.
    """
    if not raw_title:
        return ""
    return raw_title.strip().lower()


# Public alias for external callers (avoids importing private function)
normalize_title = _normalize_title
