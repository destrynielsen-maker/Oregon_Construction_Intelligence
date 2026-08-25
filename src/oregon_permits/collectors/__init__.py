from .bend import BendCollector
from .eugene import EugeneCollector
from .portland import PortlandCollector

COLLECTORS = [PortlandCollector(), EugeneCollector(), BendCollector()]
