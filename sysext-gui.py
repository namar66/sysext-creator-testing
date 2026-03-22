#!/usr/bin/python3

# Sysext-Creator GUI v4.5 - Fedora Atomic Desktop
# Tabs: Manager, Creator, Doctor, Search, Updater

import sys
import os
import varlink
import json
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel,
                             QPushButton, QMessageBox, QHBoxLayout,
                             QLineEdit, QProgressBar, QTabWidget, QPlainTextEdit,
                             QHeaderView, QTableWidget, QTableWidgetItem, QListWidget)
from PyQt6.QtCore import QThread, pyqtSignal, QProcess, Qt

SOCKET_PATH = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"
CONTAINER_NAME = "sysext-builder"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"

# --- WORKER THREADS ---

class VarlinkWorker(QThread):
    """Obecný worker pro asynchronní Varlink volání"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, method_name, *args):
        super().__init__()
        self.method_name = method_name
        self.args = args

    def run(self):
        try:
            with varlink.Client(address=SOCKET_PATH) as client:
                with client.open(INTERFACE) as remote:
                    method = getattr(remote, self.method_name)
                    reply = method(*self.args)
                    self.finished.emit(reply)
        except Exception as e:
            self.error.emit(str(e))

class SysextManagerGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.workers = [] # List to keep workers alive
        self.init_ui()

    def run_worker(self, method_name, *args, callback=None):
        """Helper to run Varlink tasks safely in background"""
        worker = VarlinkWorker(method_name, *args)
        self.workers.append(worker) # Keep reference
        
        if callback:
            worker.finished.connect(callback)
        
        # Cleanup worker from list when done
        worker.finished.connect(lambda: self.workers.remove(worker) if worker in self.workers else None)
        worker.error.connect(lambda msg: (QMessageBox.warning(self, "Varlink Error", msg), 
                                         self.workers.remove(worker) if worker in self.workers else None))
        worker.start()
        return worker

    def init_ui(self):
        self.setWindowTitle("Sysext Manager Pro v4.5")
        self.setMinimumSize(1000, 750)
        self.setStyleSheet("""
            QWidget { background-color: #f5f5f5; font-family: 'Segoe UI', sans-serif; }
            QTabWidget::pane { border: 1px solid #ccc; background: white; border-radius: 5px; }
            QPushButton { padding: 8px 15px; border-radius: 4px; background-color: #0078d4; color: white; font-weight: bold; }
            QPushButton:hover { background-color: #005a9e; }
            QPushButton:disabled { background-color: #ccc; }
            QLineEdit { padding: 8px; border: 1px solid #ccc; border-radius: 4px; background: white; }
            QTableWidget { border: none; gridline-color: #eee; }
            QHeaderView::section { background-color: #eee; padding: 5px; border: 1px solid #ddd; font-weight: bold; }
        """)

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        # --- TABS INITIALIZATION ---
        self.init_manager_tab()
        self.init_creator_tab()
        self.init_search_tab()
        self.init_update_tab()
        self.init_doctor_tab()

        main_layout.addWidget(self.tabs)

        # Build Process
        self.build_process = QProcess(self)
        self.build_process.readyReadStandardOutput.connect(self.read_build_output)
        self.build_process.finished.connect(self.on_build_finished)

        # Initial Load
        self.refresh_manager()

    # --- TAB: MANAGER ---
    def init_manager_tab(self):
        self.tab_manager = QWidget()
        layout = QVBoxLayout(self.tab_manager)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Version", "Packages"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_refresh = QPushButton("🔄 Refresh List")
        btn_refresh.clicked.connect(self.refresh_manager)
        btn_remove = QPushButton("🗑️ Remove Selected")
        btn_remove.setStyleSheet("background-color: #d83b01;")
        btn_remove.clicked.connect(self.remove_selected)
        
        btn_layout.addWidget(btn_refresh)
        btn_layout.addWidget(btn_remove)
        layout.addLayout(btn_layout)
        self.tabs.addTab(self.tab_manager, "📦 Extensions")

    # --- TAB: CREATOR ---
    def init_creator_tab(self):
        self.tab_creator = QWidget()
        layout = QVBoxLayout(self.tab_creator)
        
        self.name_in = QLineEdit()
        self.name_in.setPlaceholderText("Extension name (e.g. my-tools)")
        self.pkgs_in = QLineEdit()
        self.pkgs_in.setPlaceholderText("Packages space separated (e.g. htop nmap vim)")
        
        layout.addWidget(QLabel("<b>Layer Name:</b>"))
        layout.addWidget(self.name_in)
        layout.addWidget(QLabel("<b>Packages to Include:</b>"))
        layout.addWidget(self.pkgs_in)
        
        self.build_btn = QPushButton("🔨 Build & Deploy Sysext")
        self.build_btn.clicked.connect(self.start_build)
        layout.addWidget(self.build_btn)
        
        self.build_log = QPlainTextEdit()
        self.build_log.setReadOnly(True)
        self.build_log.setStyleSheet("background: #1e1e1e; color: #00ff00; font-family: monospace; font-size: 11px;")
        layout.addWidget(self.build_log)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.tabs.addTab(self.tab_creator, "🔨 Creator")

    # --- TAB: SEARCH ---
    def init_search_tab(self):
        self.tab_search = QWidget()
        layout = QVBoxLayout(self.tab_search)
        
        search_bar = QHBoxLayout()
        self.search_in = QLineEdit()
        self.search_in.setPlaceholderText("Search Fedora packages...")
        self.search_in.returnPressed.connect(self.run_search)
        btn_search = QPushButton("🔍 Search")
        btn_search.clicked.connect(self.run_search)
        search_bar.addWidget(self.search_in)
        search_bar.addWidget(btn_search)
        layout.addLayout(search_bar)
        
        self.search_results = QTableWidget(0, 2)
        self.search_results.setHorizontalHeaderLabels(["Package Name", "Description"])
        self.search_results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.search_results.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.search_results)
        
        self.tabs.addTab(self.tab_search, "🔍 Search")

    # --- TAB: UPDATE ---
    def init_update_tab(self):
        self.tab_update = QWidget()
        layout = QVBoxLayout(self.tab_update)
        
        self.update_table = QTableWidget(0, 3)
        self.update_table.setHorizontalHeaderLabels(["Extension", "Current Version", "New Version"])
        self.update_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.update_table)
        
        btn_layout = QHBoxLayout()
        btn_check = QPushButton("🔄 Check for Updates")
        btn_check.clicked.connect(self.check_updates)
        self.btn_update_all = QPushButton("🚀 Update All")
        self.btn_update_all.setEnabled(False)
        self.btn_update_all.clicked.connect(self.run_update_all)
        
        btn_layout.addWidget(btn_check)
        btn_layout.addWidget(self.btn_update_all)
        layout.addLayout(btn_layout)
        
        self.tabs.addTab(self.tab_update, "✨ Updates")

    # --- TAB: DOCTOR ---
    def init_doctor_tab(self):
        self.tab_doctor = QWidget()
        layout = QVBoxLayout(self.tab_doctor)
        
        self.doctor_log = QPlainTextEdit()
        self.doctor_log.setReadOnly(True)
        self.doctor_log.setStyleSheet("background: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(QLabel("<b>System Health Diagnostics:</b>"))
        layout.addWidget(self.doctor_log)
        
        btn_doctor = QPushButton("🩺 Run Diagnostics")
        btn_doctor.clicked.connect(self.run_doctor)
        layout.addWidget(btn_doctor)
        
        self.tabs.addTab(self.tab_doctor, "🩺 Doctor")

    # --- LOGIC: MANAGER ---
    def refresh_manager(self):
        self.run_worker("ListExtensions", callback=self.on_manager_loaded)

    def on_manager_loaded(self, res):
        self.table.setRowCount(0)
        for e in res.get('extensions', []):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(e['name']))
            self.table.setItem(row, 1, QTableWidgetItem(e['version']))
            self.table.setItem(row, 2, QTableWidgetItem(e['packages']))

    def remove_selected(self):
        row = self.table.currentRow()
        if row < 0: return
        name = self.table.item(row, 0).text()
        if QMessageBox.question(self, "Confirm", f"Remove {name}?") == QMessageBox.StandardButton.Yes:
            self.run_worker("RemoveSysext", name, callback=lambda _: self.refresh_manager())

    # --- LOGIC: SEARCH ---
    def run_search(self):
        query = self.search_in.text().strip()
        if not query: return
        self.search_results.setRowCount(0)
        self.run_worker("SearchPackages", query, callback=self.on_search_results)

    def on_search_results(self, res):
        pkgs = res.get('packages', [])
        for p in pkgs:
            row = self.search_results.rowCount()
            self.search_results.insertRow(row)
            self.search_results.setItem(row, 0, QTableWidgetItem(p['name']))
            self.search_results.setItem(row, 1, QTableWidgetItem(p['summary']))

    # --- LOGIC: UPDATER ---
    def check_updates(self):
        self.update_table.setRowCount(0)
        self.run_worker("CheckUpdates", callback=self.on_updates_checked)

    def on_updates_checked(self, res):
        updates = res.get('updates', [])
        self.btn_update_all.setEnabled(len(updates) > 0)
        for u in updates:
            row = self.update_table.rowCount()
            self.update_table.insertRow(row)
            self.update_table.setItem(row, 0, QTableWidgetItem(u['name']))
            self.update_table.setItem(row, 1, QTableWidgetItem(u['current_version']))
            self.update_table.setItem(row, 2, QTableWidgetItem(u['new_version']))
        if not updates:
            QMessageBox.information(self, "Updates", "All extensions are up to date!")

    def run_update_all(self):
        self.btn_update_all.setEnabled(False)
        self.run_worker("UpdateAll", callback=lambda _: (self.check_updates(), self.refresh_manager()))

    # --- LOGIC: DOCTOR ---
    def run_doctor(self):
        self.doctor_log.setPlainText("Running diagnostics...")
        self.run_worker("GetDoctorStatus", callback=self.on_doctor_finished)

    def on_doctor_finished(self, res):
        checks = res.get('checks', [])
        report = []
        for c in checks:
            status_icon = "✅" if c['status'] == 'ok' else "❌"
            report.append(f"{status_icon} {c['name']}: {c['message']}")
        self.doctor_log.setPlainText("\n".join(report))

    # --- LOGIC: CREATOR ---
    def read_build_output(self):
        out = self.build_process.readAllStandardOutput().data().decode()
        self.build_log.appendPlainText(out.strip())

    def start_build(self):
        name = self.name_in.text().strip()
        pkgs = self.pkgs_in.text().strip()
        if not name or not pkgs: return
        self.current_name = name
        self.build_btn.setEnabled(False)
        self.build_log.clear()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        script = "/run/host" + BUILDER_SCRIPT
        self.build_process.start("toolbox", ["run", "-c", CONTAINER_NAME, "python3", script, name, *pkgs.split()])

    def on_build_finished(self):
        self.progress_bar.setVisible(False)
        self.build_btn.setEnabled(True)
        if self.build_process.exitCode() == 0:
            path = f"/var/tmp/sysext-creator/{self.current_name}.raw"
            self.run_worker("DeploySysext", self.current_name, path, True, 
                           callback=lambda _: (self.refresh_manager(), QMessageBox.information(self, "Done", "Sysext Deployed!")))
        else:
            QMessageBox.critical(self, "Error", "Build failed. Check logs.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = SysextManagerGUI()
    gui.show()
    sys.exit(app.exec())
