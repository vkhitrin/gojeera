from itertools import product

from gojeera.internal.store import cache as cache_module
from gojeera.internal.store.cache import ApplicationCache


def test_filter_options_have_independent_rows_and_freshness(application_cache, monkeypatch):
    now = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: now)
    expected = {}
    for index, (starred_only, include_shared) in enumerate(product([False, True], repeat=2)):
        filters = [
            {
                'label': 'Same label',
                'expression': f'project = PROJECT{index}',
                'source': 'remote',
                'starred': starred_only,
            }
        ]
        expected[starred_only, include_shared] = filters
        application_cache.set_remote_filters(
            'user-1',
            filters,
            ttl_seconds=10 * (index + 1),
            starred_only=starred_only,
            include_shared=include_shared,
        )

    now += 11
    for (starred_only, include_shared), filters in expected.items():
        result = application_cache.get_remote_filters(
            'user-1',
            starred_only=starred_only,
            include_shared=include_shared,
        )
        if not starred_only and not include_shared:
            assert result is None
            result = application_cache.get_remote_filters('user-1', allow_stale=True)
        assert [item.as_filter_dict() for item in result] == filters
        assert (
            application_cache.get_remote_filters(
                'user-2',
                starred_only=starred_only,
                include_shared=include_shared,
            )
            is None
        )

    application_cache.set_profile('other-profile')
    assert application_cache.get_remote_filters('user-1', starred_only=True) is None


def test_legacy_filter_cache_is_preserved_but_not_reused(application_cache):
    legacy = [{'label': 'Legacy', 'expression': 'project = OLD'}]
    application_cache._set('remote_filters', legacy, 'user-1')

    for starred_only, include_shared in product([False, True], repeat=2):
        assert (
            application_cache.get_remote_filters(
                'user-1',
                starred_only=starred_only,
                include_shared=include_shared,
                allow_stale=True,
            )
            is None
        )

    application_cache.set_remote_filters('user-1', [], starred_only=True)
    assert application_cache.get_remote_filters('user-1', starred_only=True) == []
    assert application_cache._get('remote_filters', 'user-1')[0].label == 'Legacy'


def test_option_scoped_filters_survive_restart_and_clear(tmp_path):
    path = tmp_path / 'filters.db'
    cache = ApplicationCache(path)
    try:
        cache.set_remote_filters('user-1', [], include_shared=True)
    finally:
        cache.close()

    cache = ApplicationCache(path)
    try:
        assert cache.get_remote_filters('user-1', include_shared=True) == []
        assert cache.get_remote_filters('user-1') is None
        cache.clear()
        assert cache.get_remote_filters('user-1', include_shared=True, allow_stale=True) is None
    finally:
        cache.close()
