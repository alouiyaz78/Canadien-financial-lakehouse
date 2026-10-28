"""Source clients, looked up by the ``source`` field of a SeriesSpec."""

from types import ModuleType

from cfl.sources import fred, statcan, valet

CLIENTS: dict[str, ModuleType] = {"valet": valet, "statcan": statcan, "fred": fred}


def client_for(source: str) -> ModuleType:
    return CLIENTS[source]
