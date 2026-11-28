from .beaverton import BeavertonCollector
from .bend import BendCollector
from .eugene import EugeneCollector
from .gresham import GreshamCollector
from .hillsboro import HillsboroCollector
from .portland import PortlandCollector
from .hermiston import HermistonCollector
from .malheur import MalheurCollector

COLLECTORS = [
    PortlandCollector(), EugeneCollector(), BendCollector(), HillsboroCollector(),
    GreshamCollector(), BeavertonCollector(), HermistonCollector(), MalheurCollector(),
]
