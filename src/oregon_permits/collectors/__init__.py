from .bend import BendCollector
from .eugene import EugeneCollector
from .hillsboro import HillsboroCollector
from .portland import PortlandCollector

COLLECTORS = [PortlandCollector(), EugeneCollector(), BendCollector(), HillsboroCollector()]
