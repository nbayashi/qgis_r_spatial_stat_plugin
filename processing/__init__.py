from .run_r_script_algorithm import RunRScriptAlgorithm
from qgis.core import QgsProcessingProvider

class RScriptProcessingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        self.addAlgorithm(RunRScriptAlgorithm())

    def id(self):
        return "rrunner"

    def name(self):
        return "R Runner"