"""Tests for geo.py - ZIP radius calculations."""

import pytest
from geo import (
    haversine_distance,
    get_zips_in_radius,
    get_states_from_zips,
    get_state_counts_from_zips,
    load_zip_centroids,
)


class TestHaversineDistance:
    """Tests for haversine_distance function."""

    def test_same_point_returns_zero(self):
        """Same coordinates should return 0 distance."""
        distance = haversine_distance(32.7767, -96.7970, 32.7767, -96.7970)
        assert distance == 0.0

    def test_dallas_to_fort_worth(self):
        """Dallas to Fort Worth is approximately 30 miles."""
        # Dallas: 32.7767, -96.7970
        # Fort Worth: 32.7555, -97.3308
        distance = haversine_distance(32.7767, -96.7970, 32.7555, -97.3308)
        assert 29 < distance < 32

    def test_new_york_to_los_angeles(self):
        """NY to LA is approximately 2,450 miles."""
        # New York: 40.7128, -74.0060
        # Los Angeles: 34.0522, -118.2437
        distance = haversine_distance(40.7128, -74.0060, 34.0522, -118.2437)
        assert 2400 < distance < 2500

    def test_symmetry(self):
        """Distance A to B should equal distance B to A."""
        d1 = haversine_distance(32.7767, -96.7970, 33.4484, -112.0740)
        d2 = haversine_distance(33.4484, -112.0740, 32.7767, -96.7970)
        assert d1 == pytest.approx(d2, rel=1e-9)


class TestLoadZipCentroids:
    """Tests for load_zip_centroids function."""

    def test_loads_data(self):
        """Should load ZIP centroid data (US Census 2024 ZCTA Gazetteer ~33.6k)."""
        centroids = load_zip_centroids()
        assert len(centroids) > 30000

    def test_no_centroid_collapse(self):
        """No more than 3 ZIPs may share the same (lat, lng).

        Catches the data corruption pattern where a low-quality source
        collapses many ZIPs onto a single shared coordinate, producing
        geographically meaningless radius searches.
        """
        centroids = load_zip_centroids()
        coord_counts: dict[tuple[float, float], int] = {}
        for lat, lng, _ in centroids.values():
            coord_counts[(lat, lng)] = coord_counts.get((lat, lng), 0) + 1
        worst = max(coord_counts.values())
        assert worst <= 3, f"Centroid collapse detected: max {worst} ZIPs share one coordinate"

    def test_contains_known_zips(self):
        """Should contain well-known ZIP codes."""
        centroids = load_zip_centroids()
        assert "75201" in centroids  # Dallas
        assert "10001" in centroids  # New York
        assert "90210" in centroids  # Beverly Hills

    def test_data_format(self):
        """Each entry should be (lat, lng, state) tuple."""
        centroids = load_zip_centroids()
        lat, lng, state = centroids["75201"]
        assert isinstance(lat, float)
        assert isinstance(lng, float)
        assert isinstance(state, str)
        assert len(state) == 2
        assert state == "TX"


class TestGetZipsInRadius:
    """Tests for get_zips_in_radius function."""

    def test_center_zip_included_first(self):
        """Center ZIP should be first in results with 0 distance."""
        zips = get_zips_in_radius("75201", 10)
        assert len(zips) > 0
        assert zips[0]["zip"] == "75201"
        assert zips[0]["distance_miles"] == 0.0

    def test_sorted_by_distance(self):
        """Results should be sorted by distance ascending."""
        zips = get_zips_in_radius("75201", 15)
        distances = [z["distance_miles"] for z in zips]
        assert distances == sorted(distances)

    def test_all_within_radius(self):
        """All returned ZIPs should be within specified radius."""
        radius = 10
        zips = get_zips_in_radius("75201", radius)
        for z in zips:
            assert z["distance_miles"] <= radius

    def test_invalid_zip_returns_empty(self):
        """Invalid ZIP should return empty list."""
        zips = get_zips_in_radius("00000", 10)
        assert len(zips) == 0

    def test_zero_radius_returns_only_center(self):
        """Zero radius should return only the center ZIP."""
        zips = get_zips_in_radius("75201", 0)
        assert len(zips) == 1
        assert zips[0]["zip"] == "75201"

    def test_result_contains_required_fields(self):
        """Each result should have required fields."""
        zips = get_zips_in_radius("75201", 5)
        assert len(zips) > 0
        for z in zips:
            assert "zip" in z
            assert "state" in z
            assert "lat" in z
            assert "lng" in z
            assert "distance_miles" in z

    def test_larger_radius_includes_more_zips(self):
        """Larger radius should include more ZIPs."""
        zips_10 = get_zips_in_radius("75201", 10)
        zips_15 = get_zips_in_radius("75201", 15)
        assert len(zips_15) > len(zips_10)


class TestBorderZipDetection:
    """Tests for state border detection."""

    def test_texarkana_includes_arkansas(self):
        """Texarkana TX (75501) near AR border should find AR ZIPs.

        ZCTA 75501 covers a large rural area; its Census internal point sits
        ~6mi SW of downtown Texarkana, putting the nearest AR ZIP (71854) at
        exactly 15mi. A 20mi radius reliably captures both states.
        """
        zips = get_zips_in_radius("75501", 20)
        states = get_states_from_zips(zips)
        assert "TX" in states
        assert "AR" in states

    def test_dallas_single_state(self):
        """Dallas (75201) far from borders should only find TX ZIPs."""
        zips = get_zips_in_radius("75201", 15)
        states = get_states_from_zips(zips)
        assert states == ["TX"]

    def test_kansas_city_includes_missouri_and_kansas(self):
        """Kansas City area should include both MO and KS."""
        # Kansas City, KS: 66101
        zips = get_zips_in_radius("66101", 15)
        states = get_states_from_zips(zips)
        assert "KS" in states
        assert "MO" in states


class TestGetStatesFromZips:
    """Tests for get_states_from_zips function."""

    def test_empty_input(self):
        """Empty list should return empty list."""
        states = get_states_from_zips([])
        assert states == []

    def test_single_state(self):
        """Single state should return list with one state."""
        zips = [
            {"zip": "75201", "state": "TX"},
            {"zip": "75202", "state": "TX"},
        ]
        states = get_states_from_zips(zips)
        assert states == ["TX"]

    def test_multiple_states_ordered_by_frequency(self):
        """States should be ordered by frequency (most first)."""
        zips = [
            {"zip": "1", "state": "TX"},
            {"zip": "2", "state": "TX"},
            {"zip": "3", "state": "TX"},
            {"zip": "4", "state": "OK"},
        ]
        states = get_states_from_zips(zips)
        assert states[0] == "TX"  # Most frequent
        assert states[1] == "OK"

    def test_alphabetical_tiebreaker(self):
        """Equal frequency states should be alphabetical."""
        zips = [
            {"zip": "1", "state": "TX"},
            {"zip": "2", "state": "OK"},
            {"zip": "3", "state": "AR"},
        ]
        states = get_states_from_zips(zips)
        assert states == ["AR", "OK", "TX"]


class TestGetStateCountsFromZips:
    """Tests for get_state_counts_from_zips function."""

    def test_empty_input(self):
        """Empty list should return empty dict."""
        counts = get_state_counts_from_zips([])
        assert counts == {}

    def test_counts_correct(self):
        """Should return correct counts per state."""
        zips = [
            {"zip": "1", "state": "TX"},
            {"zip": "2", "state": "TX"},
            {"zip": "3", "state": "OK"},
        ]
        counts = get_state_counts_from_zips(zips)
        assert counts == {"TX": 2, "OK": 1}

    def test_real_data(self):
        """Should work with real ZIP data."""
        zips = get_zips_in_radius("75501", 20)  # Texarkana (20mi to cross AR border reliably)
        counts = get_state_counts_from_zips(zips)
        assert counts["TX"] > 0
        assert counts["AR"] > 0
        assert sum(counts.values()) == len(zips)


class TestDistanceBetweenZips:
    """R-04 (HADES-1hw): messy ZoomInfo ZIPs (ZIP+4, int, 4-digit) must be
    normalized before the centroid lookup — a silent miss fabricated a 15mi
    default for 40% of the geography score."""

    def test_clean_zips(self):
        from geo import distance_between_zips
        d = distance_between_zips("75201", "75201")
        assert d == 0.0

    def test_zip_plus_four_normalized(self):
        from geo import distance_between_zips
        assert distance_between_zips("75201-1234", "75201") == 0.0
        assert distance_between_zips("75201 1234", "75201") == 0.0

    def test_int_zip_normalized(self):
        from geo import distance_between_zips
        assert distance_between_zips(75201, "75201") == 0.0

    def test_dropped_leading_zero_normalized(self):
        from geo import distance_between_zips
        # 4-digit Excel-mangled MA ZIP (01001 Agawam → 1001)
        assert distance_between_zips("1001", "01001") == 0.0

    def test_unknown_zip_returns_none(self):
        from geo import distance_between_zips
        assert distance_between_zips("00000", "75201") is None
        assert distance_between_zips("", "75201") is None
        assert distance_between_zips(None, "75201") is None

    def test_real_distance_positive(self):
        from geo import distance_between_zips
        d = distance_between_zips("75201", "76102")  # Dallas → Fort Worth
        assert d is not None and 25 < d < 40


class TestNorthernVirginiaStates:
    """R-05: small-radius NoVA searches must derive VA, not DC."""

    def test_ashburn_radius_derives_va(self):
        from geo import get_zips_in_radius, get_states_from_zips
        zips = get_zips_in_radius("20147", 5.0)  # Ashburn VA
        states = get_states_from_zips(zips)
        assert "VA" in states
        assert "DC" not in states
