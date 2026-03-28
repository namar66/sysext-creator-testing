#!/usr/bin/python3

import sys
import os
import subprocess
import logging
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QSplitter, QListWidget, QTableView,
                             QLineEdit, QTabWidget, QTextEdit, QLabel, QPushButton,
                             QHeaderView, QMenu, QMessageBox, QAbstractItemView)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# ==========================================
# ASYNC WORKER THREAD
# ==========================================
class DnfAsyncWorker(QThread):
    packages_loaded = pyqtSignal(list)
    groups_loaded = pyqtSignal(list)
    group_details_loaded = pyqtSignal(list)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, task="available", group_name=None):
        super().__init__()
        self.task = task
        self.group_name = group_name

    def get_all_installed_packages(self) -> set:
        """
        Combines packages from host RPM DB and local sysext manifests.
        """
        installed_set = set()
        
        # 1. Host Native Packages
        try:
            cmd = ["rpm", "-qa", "--queryformat", "%{NAME}\n"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            installed_set.update(res.stdout.splitlines())
        except Exception as e:
            logging.warning(f"Failed to fetch host packages: {e}")

        # 2. Sysext Manifests
        # Path where our builder saves lists of included packages
        manifest_dir = "/usr/share/sysext/manifests"
        try:
            if os.path.exists(manifest_dir):
                for manifest in os.listdir(manifest_dir):
                    if manifest.endswith(".txt"):
                        with open(os.path.join(manifest_dir, manifest), 'r') as f:
                            pkgs = [line.strip() for line in f if line.strip()]
                            installed_set.update(pkgs)
        except Exception as e:
            logging.warning(f"Failed to read sysext manifests: {e}")

        return installed_set

    def load_available_packages(self):
        installed = self.get_all_installed_packages()
        cmd = [
            "toolbox", "run", "-c", "sysext-builder", 
            "dnf", "repoquery", "--quiet", "--queryformat", "%{name}|%{version}-%{release}|%{repoid}\n"
        ]
        
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            batch = []
            for line in process.stdout:
                clean_line = line.strip()
                if not clean_line: continue
                parts = clean_line.split("|")
                if len(parts) == 3:
                    name, version, repo = parts
                    if name not in installed:
                        batch.append([name, version, repo, "Available"])
                
                if len(batch) >= 500:
                    self.packages_loaded.emit(batch)
                    batch = []
            
            if batch: self.packages_loaded.emit(batch)
            process.wait()
        except Exception as e:
            self.error.emit(f"DNF Error: {e}")

    def load_groups(self):
        installed = self.get_all_installed_packages()
        cmd = ["toolbox", "run", "-c", "sysext-builder", "dnf", "group", "list", "--hidden"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            groups = []
            for line in res.stdout.splitlines():
                clean_line = line.strip()
                if not clean_line or clean_line.startswith(("ID", "Available", "Installed", "Hidden", "Environment", "Last", "Aktualizace", "Repozitáře")):
                    continue
                
                parts = re.split(r'\s{2,}', clean_line)
                if len(parts) >= 3:
                    # In DNF5, we check if group components are in our 'installed' set
                    # For now, we use DNF's reported state
                    groups.append([parts[0], "Group", parts[1], parts[2]])
            self.groups_loaded.emit(groups)
        except Exception as e:
            self.error.emit(f"Group Error: {e}")

    def load_group_details(self):
        installed = self.get_all_installed_packages()
        cmd = ["toolbox", "run", "-c", "sysext-builder", "env", "LANG=C", "dnf", "group", "info", "--quiet", self.group_name]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            packages = []
            parsing = False
            for line in res.stdout.splitlines():
                if ":" in line:
                    left, right = line.split(":", 1)
                    l_clean, r_clean = left.strip(), right.strip()
                    if l_clean in ["Mandatory packages", "Default packages"]:
                        parsing = True
                        if r_clean and r_clean not in installed: packages.append(r_clean)
                    elif l_clean == "" and parsing:
                        if r_clean and r_clean not in installed: packages.append(r_clean)
                    else:
                        parsing = False
            self.group_details_loaded.emit(packages)
        except Exception as e:
            self.error.emit(f"Details Error: {e}")

    def run(self):
        if self.task == "available": self.load_available_packages()
        elif self.task == "groups": self.load_groups()
        elif self.task == "group_details": self.load_group_details()
        self.finished.emit()

# ==========================================
# MAIN GUI CLASS
# ==========================================
class SysextAdvancedGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sysext Creator Pro")
        self.resize(1150, 800)
        self.transaction_queue = []
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(main_splitter)

        # LEFT PANEL
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self.category_list = QListWidget()
        self.category_list.addItems(["📦 Available (DNF)", "✅ Installed (Sysext)", "🔄 Updates", "📁 Package Groups", "🛒 Transaction Queue (0)"])
        self.category_list.currentRowChanged.connect(self.on_category_changed)
        
        left_layout.addWidget(QLabel("<b>Categories</b>"))
        left_layout.addWidget(self.category_list)
        
        self.btn_clear = QPushButton("Clear Queue")
        self.btn_clear.clicked.connect(self.clear_queue)
        left_layout.addWidget(self.btn_clear)

        self.btn_apply = QPushButton("Apply Transaction")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setStyleSheet("background-color: #2e8b57; color: white; font-weight: bold; padding: 10px;")
        self.btn_apply.clicked.connect(self.apply_transaction)
        left_layout.addWidget(self.btn_apply)

        # RIGHT PANEL
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        top_right_panel = QWidget()
        top_right_layout = QVBoxLayout(top_right_panel)
        
        self.status_label = QLabel("Ready.")
        top_right_layout.addWidget(self.status_label)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        top_right_layout.addWidget(self.search_bar)

        self.package_table = QTableView()
        self.package_model = QStandardItemModel(0, 4)
        self.package_model.setHorizontalHeaderLabels(["Name", "Version", "Repository", "State"])
        
        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.package_model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy_model.setFilterKeyColumn(0)
        
        self.package_table.setModel(self.proxy_model)
        self.package_table.setSortingEnabled(True)
        self.package_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.package_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.package_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.package_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.package_table.customContextMenuRequested.connect(self.show_context_menu)
        self.package_table.selectionModel().selectionChanged.connect(self.on_table_selection)
        
        top_right_layout.addWidget(self.package_table)

        self.details_tabs = QTabWidget()
        self.tab_info = QTextEdit()
        self.tab_info.setReadOnly(True)
        self.details_tabs.addTab(self.tab_info, "Information")
        
        right_splitter.addWidget(top_right_panel)
        right_splitter.addWidget(self.details_tabs)
        right_splitter.setSizes([550, 250])
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([250, 900])

    def on_category_changed(self, index):
        self.package_model.removeRows(0, self.package_model.rowCount())
        category = self.category_list.item(index).text()
        
        if "Groups" in category:
            self.package_model.setHorizontalHeaderLabels(["ID", "Type", "Name", "Installed"])
        else:
            self.package_model.setHorizontalHeaderLabels(["Name", "Version", "Repository", "State"])

        if "Available" in category: self.start_worker("available")
        elif "Groups" in category: self.start_worker("groups")
        elif "Queue" in category: self.show_queue()

    def start_worker(self, task):
        if getattr(self, 'worker', None) and self.worker.isRunning(): return
        self.status_label.setText(f"⏳ Loading {task}...")
        self.worker = DnfAsyncWorker(task=task)
        if task == "groups": self.worker.groups_loaded.connect(self.on_batch_loaded)
        else: self.worker.packages_loaded.connect(self.on_batch_loaded)
        self.worker.finished.connect(lambda: self.status_label.setText("✅ Done."))
        self.worker.start()

    def on_batch_loaded(self, batch):
        for item in batch:
            row = [QStandardItem(str(i)) for i in item]
            self.package_model.appendRow(row)

    def on_table_selection(self):
        indexes = self.package_table.selectionModel().selectedRows()
        if not indexes: return
        real_idx = self.proxy_model.mapToSource(indexes[0])
        name = self.package_model.item(real_idx.row(), 0).text()
        v_type = self.package_model.item(real_idx.row(), 1).text()

        if v_type == "Group":
            self.tab_info.setHtml(f"<h3>Loading group: {name}...</h3>")
            self.worker_det = DnfAsyncWorker(task="group_details", group_name=name)
            self.worker_det.group_details_loaded.connect(self.on_group_details_ready)
            self.worker_det.start()
        else:
            self.tab_info.setHtml(f"<h3>{name}</h3><p>Selected package.</p>")

    def on_group_details_ready(self, packages):
        self.current_group_pkgs = packages
        html = f"<h3>Group Details ({len(packages)} new pkgs)</h3><ul>"
        html += "".join([f"<li>{p}</li>" for p in packages]) + "</ul>"
        self.tab_info.setHtml(html)

    def show_context_menu(self, pos):
        idx = self.package_table.selectionModel().selectedRows()
        if not idx: return
        
        menu = QMenu()
        curr_cat = self.category_list.currentRow()
        
        if curr_cat == 4: # Queue
            act = QAction("❌ Remove from Transaction Queue", self)
            act.triggered.connect(lambda: self.remove_from_queue(idx))
        else:
            act = QAction("🛒 Add to Transaction Queue", self)
            act.triggered.connect(lambda: self.add_to_queue(idx))
        
        menu.addAction(act)
        menu.exec(self.package_table.viewport().mapToGlobal(pos))

    def add_to_queue(self, indexes):
        for idx in indexes:
            real_idx = self.proxy_model.mapToSource(idx)
            name = self.package_model.item(real_idx.row(), 0).text()
            v_type = self.package_model.item(real_idx.row(), 1).text()

            if v_type == "Group":
                if hasattr(self, 'current_group_pkgs'):
                    for p in self.current_group_pkgs:
                        if p not in self.transaction_queue: self.transaction_queue.append(p)
                    self.package_model.setItem(real_idx.row(), 3, QStandardItem("Queued 🛒"))
            else:
                if name not in self.transaction_queue:
                    self.transaction_queue.append(name)
                    self.package_model.setItem(real_idx.row(), 3, QStandardItem("Queued 🛒"))
        self.update_ui_state()

    def remove_from_queue(self, indexes):
        for idx in reversed(indexes): # Reverse to maintain correct row mapping
            real_idx = self.proxy_model.mapToSource(idx)
            name = self.package_model.item(real_idx.row(), 0).text()
            if name in self.transaction_queue:
                self.transaction_queue.remove(name)
            self.package_model.removeRow(real_idx.row())
        self.update_ui_state()

    def clear_queue(self):
        self.transaction_queue.clear()
        if self.category_list.currentRow() == 4:
            self.package_model.removeRows(0, self.package_model.rowCount())
        self.update_ui_state()

    def update_ui_state(self):
        count = len(self.transaction_queue)
        self.category_list.item(4).setText(f"🛒 Transaction Queue ({count})")
        self.btn_apply.setEnabled(count > 0)
        self.btn_apply.setText(f"Apply Transaction ({count})" if count > 0 else "Apply Transaction")

    def show_queue(self):
        self.package_model.removeRows(0, self.package_model.rowCount())
        for name in self.transaction_queue:
            row = [QStandardItem(name), QStandardItem("pending"), QStandardItem("queue"), QStandardItem("To be installed")]
            self.package_model.appendRow(row)

    def apply_transaction(self):
        msg = f"Build new Sysext with {len(self.transaction_queue)} packages?"
        if QMessageBox.question(self, 'Confirm', msg) == QMessageBox.StandardButton.Yes:
            # Here we will link the actual builder process tomorrow!
            self.clear_queue()

    def closeEvent(self, event):
        try:
            if getattr(self, 'worker', None) and self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(1000)
        except: pass
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SysextAdvancedGUI()
    window.show()
    sys.exit(app.exec())
