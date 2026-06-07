"""
Unit tests for the interface (widget group) registry.

Run with:
    python -m pytest scripts/gamebridge/tests/
"""
from scripts.gamebridge.state import interfaces


class TestOccludes:
    def test_registered_panel_occludes(self):
        assert interfaces.occludes(149) is True  # inventory

    def test_viewport_root_does_not_occlude(self):
        assert interfaces.occludes(161) is False  # resizable_viewport

    def test_unknown_group_defaults_to_non_occluding(self):
        assert interfaces.occludes(123456) is False


class TestInfoFor:
    def test_known_group_returns_info(self):
        info = interfaces.info_for(12)
        assert info is not None
        assert info.name == "bank"
        assert info.occludes is True

    def test_unknown_group_returns_none(self):
        assert interfaces.info_for(123456) is None


class TestNameFor:
    def test_known_group_returns_name(self):
        assert interfaces.name_for(149) == "inventory"

    def test_unknown_group_returns_none(self):
        assert interfaces.name_for(123456) is None


class TestGroupIdFor:
    def test_known_name_returns_id(self):
        assert interfaces.group_id_for("bank") == 12

    def test_unknown_name_returns_none(self):
        assert interfaces.group_id_for("not_a_real_interface") is None

    def test_round_trips_with_name_for(self):
        for group_id, info in interfaces.INTERFACES.items():
            assert interfaces.group_id_for(info.name) == group_id
            assert interfaces.name_for(group_id) == info.name
