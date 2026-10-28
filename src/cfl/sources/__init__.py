"""Source clients, looked up by the ``source`` field of a SeriesSpec."""

from types import ModuleType

from cfl.sources import census, fred, statcan, valet

CLIENTS: dict[str, ModuleType] = {"valet": valet, "statcan": statcan, "fred": fred, "census": census}


def client_for(source: str) -> ModuleType:
    return CLIENTS[source]
