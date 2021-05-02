import pytest
import mock


@pytest.mark.parametrize(
    "names, expected",
    [([], "Cutlist"), (["foo"], "foo-Cutlist"), (["foo", "bar"], "foo-bar-Cutlist")],
)
def test_cutlist_name(cutlist, names, expected):
    items = []
    for name in names:
        item = mock.Mock()
        item.Label = name
        item.isDerivedFrom = mock.Mock()
        item.isDerivedFrom.return_value = False
        items.append(item)
    assert cutlist.CutList(items).name == expected
