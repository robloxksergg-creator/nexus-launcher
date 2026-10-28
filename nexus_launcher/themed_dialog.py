"""Preserve QDialog behavior and install launcher chrome before showing it."""
from PySide6.QtWidgets import QDialog


class NexusDialog(QDialog):
    def setVisible(self, visible):
        if visible and self.isWindow():
            # Delayed import avoids importing the application package at startup.
            from nexus_launcher.nexus_platform.dialog_chrome import watch_dialog
            watch_dialog(self)
        super().setVisible(visible)
