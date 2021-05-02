import pytest

from freecad.lumberjack.testing import FreeCADGui  # noqa


@pytest.fixture
def cutlist():
    from freecad.lumberjack import cutlist

    return cutlist
