"""Type stubs for mss."""

from typing import Any, Dict, List

class ScreenShot:
    size: tuple[int, int]
    rgb: bytes
    width: int
    height: int

class MSSBase:
    monitors: List[Dict[str, int]]
    def grab(self, monitor: Dict[str, int]) -> ScreenShot: ...
    def __enter__(self) -> 'MSSBase': ...
    def __exit__(self, *args: Any) -> None: ...

def mss() -> MSSBase: ...
