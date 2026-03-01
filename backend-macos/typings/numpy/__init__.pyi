"""Type stubs for numpy."""

from typing import Any

class ndarray:
    def __getitem__(self, key: Any) -> 'ndarray': ...
    shape: tuple[int, ...]
    dtype: Any

def array(object: Any, *args: Any, **kwargs: Any) -> ndarray: ...
