import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qt_helpers import qt_application, retire_window
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from logreader.file_loader import LoadedLog
from logreader.ui.qt_app import LogreaderWindow
from qt_helpers import wait_for_load


class SourceViewCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_application()

    def setUp(self):
        self.addCleanup(self.app.clipboard().clear)
        self.callback_errors = []
        self.previous_hook = sys.excepthook
        sys.excepthook = lambda kind, value, traceback: self.callback_errors.append(f"{kind.__name__}: {value}")
        self.addCleanup(setattr, sys, "excepthook", self.previous_hook)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "source.log"
        self.path.write_text("INFO: seed\n", encoding="utf-8")
        self.window = LogreaderWindow()
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.window.resize(1200, 850)
        self.window.show()
        self.window.load_file(self.path)
        self.page = self.window._document
        self.view = self.page.results_view
        self.source = self.view.source_view
        wait_for_load(self.page)

    def tearDown(self):
        retire_window(self.window)
        self.assertEqual(self.callback_errors, [])


    def settle_source(self):
        for _ in range(1000):
            QTest.qWait(2)
            loader = self.source.loader
            self.assertIsNone(loader.error)
            if (self.source.editor.navigation.pending is None and not loader.timer.isActive()
                    and loader.buffer is None):
                return
        self.fail("Requested source screen did not settle")

    def stage(self, lines, total=None):
        self.page.stage_loaded_log(self.path, LoadedLog(lines, "UTF-8", total))
