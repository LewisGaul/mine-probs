import logging
import signal
import sys

from PyQt5.QtCore import pyqtRemoveInputHook, QTimer
from PyQt5.QtWidgets import QApplication

from .minefield import MinefieldWidget


logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s[%(levelname)s](%(name)s) %(message)s",
)

logger.info("Starting up")


app = QApplication(sys.argv)
pyqtRemoveInputHook()

gui = MinefieldWidget()
gui.show()

# Create a timer to run Python code periodically, so that Ctrl+C can be caught.
signal.signal(signal.SIGINT, lambda *args: gui.close())
_timer = QTimer()
_timer.timeout.connect(lambda: None)
_timer.start(100)

sys.exit(app.exec_())
