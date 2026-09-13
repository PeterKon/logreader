import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox

from logreader.filter_panel import ContextSpinBox, ScanLimitSpinBox


class TieredSpinBoxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_spin(self, kind):
        spin = kind()
        self.addCleanup(spin.deleteLater)
        return spin

    def assert_round_trip(self, spin, values):
        spin.setValue(values[0])
        spin.stepDown()
        self.assertEqual(spin.value(), values[0])
        for value in values[1:]:
            spin.stepUp()
            self.assertEqual(spin.value(), value)
        spin.stepUp()
        self.assertEqual(spin.value(), values[-1])
        for value in reversed(values[:-1]):
            spin.stepDown()
            self.assertEqual(spin.value(), value)

    def test_scan_sequence_is_reversible_through_all_boundaries(self):
        spin = self.make_spin(ScanLimitSpinBox)
        self.assertEqual(spin.value(), 2_000_000)
        values = ([1] + list(range(1_000, 10_001, 1_000))
                  + list(range(100_000, 1_000_001, 100_000))
                  + list(range(2_000_000, 10_000_001, 1_000_000))
                  + list(range(20_000_000, 2_140_000_001, 10_000_000))
                  + [2_147_483_647])
        self.assert_round_trip(spin, values)

    def test_context_sequence_is_reversible_through_all_boundaries(self):
        spin = self.make_spin(ContextSpinBox)
        self.assertEqual(spin.value(), 5)
        values = (list(range(6)) + list(range(10, 101, 10))
                  + list(range(200, 1_001, 100)))
        self.assert_round_trip(spin, values)

    def test_multiple_steps_cross_tiers_like_repeated_presses(self):
        for kind, start, steps, expected in (
            (ScanLimitSpinBox, 9_000_000, 3, 30_000_000),
            (ScanLimitSpinBox, 2_000_000, -3, 800_000),
            (ContextSpinBox, 5, 3, 30),
            (ContextSpinBox, 200, -3, 80),
        ):
            with self.subTest(kind=kind, steps=steps):
                spin = self.make_spin(kind)
                spin.setValue(start)
                spin.stepBy(steps)
                self.assertEqual(spin.value(), expected)

    def test_manual_values_step_to_adjacent_boundaries(self):
        for kind, value, down, up in (
            (ScanLimitSpinBox, 55_000, 10_000, 100_000),
            (ScanLimitSpinBox, 1_500_000, 1_000_000, 2_000_000),
            (ScanLimitSpinBox, 10_500_000, 10_000_000, 20_000_000),
            (ContextSpinBox, 7, 5, 10),
            (ContextSpinBox, 99, 90, 100),
            (ContextSpinBox, 150, 100, 200),
        ):
            with self.subTest(kind=kind, value=value):
                spin = self.make_spin(kind)
                spin.setValue(value)
                spin.stepDown()
                self.assertEqual(spin.value(), down)
                spin.setValue(value)
                spin.stepUp()
                self.assertEqual(spin.value(), up)
        spin = self.make_spin(ScanLimitSpinBox)
        spin.lineEdit().setText("9 500 000")
        spin.stepUp()
        self.assertEqual(spin.value(), 10_000_000)

    def test_arrow_clicks_and_keyboard_use_tiered_steps(self):
        for kind, initial, up, down in (
            (ScanLimitSpinBox, 2_000_000, 3_000_000, 1_000_000),
            (ContextSpinBox, 5, 10, 4),
        ):
            with self.subTest(kind=kind):
                spin = self.make_spin(kind)
                spin.resize(220, 32)
                spin.show()
                self.addCleanup(spin.close)
                self.app.processEvents()
                option = QStyleOptionSpinBox()
                spin.initStyleOption(option)
                for control, expected in (
                    (QStyle.SubControl.SC_SpinBoxUp, up),
                    (QStyle.SubControl.SC_SpinBoxDown, down),
                ):
                    spin.setValue(initial)
                    rect = spin.style().subControlRect(
                        QStyle.ComplexControl.CC_SpinBox, option, control, spin,
                    )
                    QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=rect.center())
                    self.assertEqual(spin.value(), expected)
                spin.setValue(initial)
                QTest.keyClick(spin, Qt.Key.Key_Up)
                self.assertEqual(spin.value(), up)
                QTest.keyClick(spin, Qt.Key.Key_Down)
                self.assertEqual(spin.value(), initial)
