import importlib

import pytest

MODULES = ["extract", "detect", "mask", "vault", "index", "answer", "roles", "pipeline"]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(f"src.{name}")


def test_only_hr_sees_real_values():
    from src import roles

    assert roles.can_see_real_values(roles.HR)
    assert not roles.can_see_real_values(roles.EMPLOYEE)
