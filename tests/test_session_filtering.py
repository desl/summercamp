"""
Tests for session filtering logic used in the booking modal.

Run with: python3 -m pytest tests/test_session_filtering.py -v
Or simply: python3 tests/test_session_filtering.py
"""

from datetime import datetime, date


def session_overlaps_week(session_start, session_end, week_start, week_end):
    """
    Check if a session overlaps with a week.

    A session matches if at least one day of the session falls within the week.
    Sessions without dates always match.

    This is a copy of the logic from schedule.py for isolated testing.
    """
    if not session_start or not session_end:
        # Sessions without dates are always shown
        return True

    # Check for actual date overlap (no buffer)
    # Session overlaps week if: session_start <= week_end AND session_end >= week_start
    return session_start <= week_end and session_end >= week_start


class TestSessionOverlapsWeek:
    """Test cases for session filtering logic."""

    def test_session_completely_before_week(self):
        """Session ends before week starts - should NOT match."""
        # Session: 6/7-6/11, Week: 6/15-6/19
        session_start = date(2026, 6, 7)
        session_end = date(2026, 6, 11)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == False

    def test_session_completely_after_week(self):
        """Session starts after week ends - should NOT match."""
        # Session: 6/22-6/26, Week: 6/15-6/19
        session_start = date(2026, 6, 22)
        session_end = date(2026, 6, 26)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == False

    def test_session_exactly_matches_week(self):
        """Session dates exactly match week dates - should match."""
        # Session: 6/15-6/19, Week: 6/15-6/19
        session_start = date(2026, 6, 15)
        session_end = date(2026, 6, 19)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_starts_before_ends_during_week(self):
        """Session starts before week and ends during week - should match."""
        # Session: 6/10-6/17, Week: 6/15-6/19
        session_start = date(2026, 6, 10)
        session_end = date(2026, 6, 17)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_starts_during_ends_after_week(self):
        """Session starts during week and ends after week - should match."""
        # Session: 6/17-6/24, Week: 6/15-6/19
        session_start = date(2026, 6, 17)
        session_end = date(2026, 6, 24)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_completely_contains_week(self):
        """Session completely contains the week - should match."""
        # Session: 6/10-6/25, Week: 6/15-6/19
        session_start = date(2026, 6, 10)
        session_end = date(2026, 6, 25)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_week_completely_contains_session(self):
        """Week completely contains the session - should match."""
        # Session: 6/16-6/18, Week: 6/15-6/19
        session_start = date(2026, 6, 16)
        session_end = date(2026, 6, 18)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_ends_on_week_start(self):
        """Session ends exactly on week start day - should match (shares one day)."""
        # Session: 6/10-6/15, Week: 6/15-6/19
        session_start = date(2026, 6, 10)
        session_end = date(2026, 6, 15)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_starts_on_week_end(self):
        """Session starts exactly on week end day - should match (shares one day)."""
        # Session: 6/19-6/25, Week: 6/15-6/19
        session_start = date(2026, 6, 19)
        session_end = date(2026, 6, 25)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_ends_day_before_week_starts(self):
        """Session ends one day before week starts - should NOT match."""
        # Session: 6/10-6/14, Week: 6/15-6/19
        session_start = date(2026, 6, 10)
        session_end = date(2026, 6, 14)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == False

    def test_session_starts_day_after_week_ends(self):
        """Session starts one day after week ends - should NOT match."""
        # Session: 6/20-6/25, Week: 6/15-6/19
        session_start = date(2026, 6, 20)
        session_end = date(2026, 6, 25)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == False

    def test_session_without_start_date(self):
        """Session without start date - should always match."""
        session_start = None
        session_end = date(2026, 6, 19)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_without_end_date(self):
        """Session without end date - should always match."""
        session_start = date(2026, 6, 15)
        session_end = None
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_session_without_any_dates(self):
        """Session without any dates - should always match."""
        session_start = None
        session_end = None
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        assert session_overlaps_week(session_start, session_end, week_start, week_end) == True

    def test_multi_week_session_spanning_multiple_weeks(self):
        """Multi-week session should match any week it overlaps."""
        # 2-week session: 6/15-6/26, Week 1: 6/15-6/19, Week 2: 6/22-6/26
        session_start = date(2026, 6, 15)
        session_end = date(2026, 6, 26)

        # Should match week 1
        week1_start = date(2026, 6, 15)
        week1_end = date(2026, 6, 19)
        assert session_overlaps_week(session_start, session_end, week1_start, week1_end) == True

        # Should match week 2
        week2_start = date(2026, 6, 22)
        week2_end = date(2026, 6, 26)
        assert session_overlaps_week(session_start, session_end, week2_start, week2_end) == True

        # Should NOT match week 3 (after session ends)
        week3_start = date(2026, 6, 29)
        week3_end = date(2026, 7, 3)
        assert session_overlaps_week(session_start, session_end, week3_start, week3_end) == False

    def test_reported_bug_case(self):
        """Test the specific case reported in issue #15.

        Week: 6/15-6/19 should NOT show session 6/7-6/11
        """
        # Session: 6/7-6/11 (Monkey Business Camp sessions)
        session_start = date(2026, 6, 7)
        session_end = date(2026, 6, 11)

        # Week: 6/15-6/19 (first week of summer)
        week_start = date(2026, 6, 15)
        week_end = date(2026, 6, 19)

        # This should NOT match - session ends before week starts
        assert session_overlaps_week(session_start, session_end, week_start, week_end) == False


def run_tests():
    """Run all tests and report results."""
    import traceback

    test_classes = [TestSessionOverlapsWeek]
    passed = 0
    failed = 0
    errors = []

    for test_class in test_classes:
        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith('test_'):
                try:
                    getattr(instance, method_name)()
                    passed += 1
                    print(f"  ✓ {test_class.__name__}.{method_name}")
                except AssertionError as e:
                    failed += 1
                    errors.append((f"{test_class.__name__}.{method_name}", str(e)))
                    print(f"  ✗ {test_class.__name__}.{method_name}: {e}")
                except Exception as e:
                    failed += 1
                    errors.append((f"{test_class.__name__}.{method_name}", traceback.format_exc()))
                    print(f"  ✗ {test_class.__name__}.{method_name}: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")

    if errors:
        print(f"\nFailed tests:")
        for name, error in errors:
            print(f"  - {name}")
            print(f"    {error[:200]}")

    return failed == 0


if __name__ == "__main__":
    print("Running Session Filtering Tests\n")
    print("="*60)
    success = run_tests()
    exit(0 if success else 1)
