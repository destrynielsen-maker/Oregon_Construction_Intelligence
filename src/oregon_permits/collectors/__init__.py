from .beaverton import BeavertonCollector
from .bend import BendCollector
from .eugene import EugeneCollector
from .gresham import GreshamCollector
from .hillsboro import HillsboroCollector
from .portland import PortlandCollector

COLLECTORS = [PortlandCollector(), EugeneCollector(), BendCollector(), HillsboroCollector(), GreshamCollector(), BeavertonCollector()]
