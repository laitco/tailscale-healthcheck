import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import dbstore  # noqa: E402


def _fresh_db(tmp_path):
    dbstore.configure(str(tmp_path / "healthcheck.db"))
    dbstore.init_db()


def test_health_state_round_trip(tmp_path):
    _fresh_db(tmp_path)
    assert dbstore.get_health_state("device") == {}

    dbstore.set_health_state("device", "d1", True)
    dbstore.set_health_state("device", "d2", False)
    assert dbstore.get_health_state("device") == {"d1": True, "d2": False}


def test_health_state_upsert_overwrites(tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "d1", True)
    dbstore.set_health_state("device", "d1", False)
    assert dbstore.get_health_state("device") == {"d1": False}


def test_health_state_is_scoped_by_entity_type(tmp_path):
    """A device and a key sharing the same id string must not collide -
    entity_lock uses its own entity_type ("device_lock") too, independent of
    plain device health."""
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "x1", True)
    dbstore.set_health_state("key", "x1", False)
    dbstore.set_health_state("device_lock", "x1", True)
    assert dbstore.get_health_state("device") == {"x1": True}
    assert dbstore.get_health_state("key") == {"x1": False}
    assert dbstore.get_health_state("device_lock") == {"x1": True}


def test_prune_health_state_drops_removed_entities(tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "d1", True)
    dbstore.set_health_state("device", "d2", True)
    dbstore.set_health_state("device", "d3", False)

    dbstore.prune_health_state("device", {"d1", "d3"})
    assert dbstore.get_health_state("device") == {"d1": True, "d3": False}


def test_prune_health_state_with_empty_keep_set_clears_all(tmp_path):
    _fresh_db(tmp_path)
    dbstore.set_health_state("device", "d1", True)
    dbstore.prune_health_state("device", set())
    assert dbstore.get_health_state("device") == {}
