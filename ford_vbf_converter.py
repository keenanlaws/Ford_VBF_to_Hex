import os
import struct
import time
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QLineEdit, QMessageBox, QHBoxLayout, QStyleFactory, QGroupBox
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtMultimedia import QSoundEffect


# --- VBF metadata parser for display ---

class VBFMeta:
    def __init__(self, data: bytes):
        self.version = ""
        self.description = ""
        self.sw_part = ""
        self.sw_part_type = ""
        self.network = None
        self.data_format_identifier = None
        self.ecu_address = None
        self.verification_block_start = None
        self.frame_format = ""
        self.file_checksum = None
        self.erase = []
        self.regions = []
        self.valid = False
        self.error = ""
        try:
            self._parse(data)
            self.valid = True
        except Exception as e:
            self.error = str(e)

    def _parse(self, data: bytes):
        import re
        m = re.search(rb"vbf_version\s*=\s*([^\s;]+)\s*;", data)
        if m: self.version = m.group(1).decode("ascii")
        header_match = re.search(rb"header\s*{(.*?)};", data, re.DOTALL)
        if not header_match:
            raise ValueError("Header block not found")
        header = header_match.group(1)
        desc_match = re.search(rb'description\s*=\s*"(.*?)";', header, re.DOTALL)
        if desc_match:
            self.description = desc_match.group(1).replace(b'\n', b' ').decode('utf-8').strip()
        m = re.search(rb'sw_part_number\s*=\s*"?(.*?)"?;', header)
        if m: self.sw_part = m.group(1).decode("ascii").strip()
        m = re.search(rb'sw_part_type\s*=\s*"?(.*?)"?;', header)
        if m: self.sw_part_type = m.group(1).decode("ascii").strip()
        m = re.search(rb'network\s*=\s*"?([0-9A-Fa-fx]+)"?;', header)
        if m:
            try:
                self.network = int(m.group(1).replace(b'0x', b''), 16)
            except:
                self.network = None
        m = re.search(rb'data_format_identifier\s*=\s*"?([0-9A-Fa-fx]+)"?;', header)
        if m:
            try:
                self.data_format_identifier = int(m.group(1).replace(b'0x', b''), 16)
            except:
                self.data_format_identifier = None
        m = re.search(rb'ecu_address\s*=\s*0x([0-9A-Fa-f]+);', header)
        if m:
            try:
                self.ecu_address = int(m.group(1), 16)
            except:
                self.ecu_address = None
        m = re.search(rb'verification_block_start\s*=\s*0x([0-9A-Fa-f]+);', header)
        if m:
            try:
                self.verification_block_start = int(m.group(1), 16)
            except:
                self.verification_block_start = None
        m = re.search(rb'frame_format\s*=\s*"?(.*?)"?;', header)
        if m: self.frame_format = m.group(1).decode("ascii").strip()
        m = re.search(rb'file_checksum\s*=\s*0x([0-9A-Fa-f]+);', header)
        if m:
            try:
                self.file_checksum = m.group(1).decode()
            except:
                self.file_checksum = None
        erase_match = re.search(rb'erase\s*=\s*{([^}]*)}', header, re.DOTALL)
        if erase_match:
            self.erase = []
            import re as r2
            erase_entries = r2.findall(r'0x([0-9A-Fa-f]+)\s*,\s*0x([0-9A-Fa-f]+)', erase_match.group(1).decode())
            for start, end in erase_entries:
                self.erase.append((int(start, 16), int(end, 16)))
        self.regions = self.extract_data_regions(data)

    def extract_data_regions(self, data: bytes):
        header_end = data.find(b"\n}") + 2
        regions = []
        if header_end < 2:
            return regions
        binary = data[header_end:]
        pos = 0
        while pos + 10 <= len(binary):
            addr = int.from_bytes(binary[pos:pos + 4], "big")
            size = int.from_bytes(binary[pos + 4:pos + 8], "big")
            regions.append((addr, size))
            pos += 8 + size + 2
        return regions

    def summary_html(self):
        def hx(val):
            return f"0x{val:08X}" if isinstance(val, int) else "N/A"

        rows = []
        rows.append(f"<b>VBF Version:</b> {self.version or 'N/A'}")
        rows.append(f"<b>Part Number:</b> {self.sw_part or 'N/A'} &nbsp; <b>Type:</b> {self.sw_part_type or 'N/A'}")
        rows.append(f"<b>ECU Address:</b> {hx(self.ecu_address)} &nbsp; <b>Network:</b> {hx(self.network)}")
        rows.append(
            f"<b>Data Format:</b> {hx(self.data_format_identifier)} &nbsp; <b>Frame:</b> {self.frame_format or 'N/A'}")
        rows.append(f"<b>Description:</b> {self.description or 'N/A'}")
        rows.append(
            f"<b>Verification Block:</b> {hx(self.verification_block_start)} &nbsp; <b>Checksum:</b> {self.file_checksum or 'N/A'}")
        if self.erase:
            rows.append(f"<b>Erase Regions:</b><br>" + "<br>".join([f"0x{a:08X} - 0x{b:08X}" for a, b in self.erase]))
        if self.regions:
            region_lines = [f"Region {i + 1}: <b>0x{addr:08X}</b> - <b>0x{addr + size - 1:08X}</b> (Size: {size} bytes)"
                            for i, (addr, size) in enumerate(self.regions)]
            rows.append("<b>Data Regions:</b><br>" + "<br>".join(region_lines))
            rows.append(f"<b>Total Data Regions:</b> {len(self.regions)}")
        return "<br>".join(rows)


# --- Intel HEX conversion ---

def vbf_to_intel_hex(vbf_path, hex_path):
    with open(vbf_path, "rb") as f:
        data = f.read()
    header_end = data.find(b"\n}") + 2
    if header_end < 2:
        return 0, "Could not find binary data start."
    binary = data[header_end:]
    records = []
    pos = 0
    while pos + 10 <= len(binary):
        addr = int.from_bytes(binary[pos:pos + 4], "big")
        size = int.from_bytes(binary[pos + 4:pos + 8], "big")
        data_blob = binary[pos + 8:pos + 8 + size]
        pos += 8 + size + 2
        for off in range(0, len(data_blob), 32):
            chunk = data_blob[off:off + 32]
            ll = len(chunk)
            aaaa = addr + off
            tt = 0x00
            line = [ll, (aaaa >> 8) & 0xFF, aaaa & 0xFF, tt] + list(chunk)
            checksum = (-(sum(line)) & 0xFF)
            hexline = ":{:02X}{:04X}{:02X}{}".format(ll, aaaa, tt, ''.join("{:02X}".format(x) for x in chunk))
            hexline += "{:02X}\n".format(checksum)
            records.append(hexline)
    records.append(":00000001FF\n")
    try:
        with open(hex_path, "w") as f:
            f.writelines(records)
        return 1, "Success"
    except Exception as e:
        return 0, f"Error writing HEX: {e}"


# --- GUI ---

class VBFConverterGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.init_sounds()

        self.setWindowTitle("Ford VBF Converter")
        self.setMinimumWidth(690)
        self.setMinimumHeight(500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint)
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        self.setAcceptDrops(True)

        main_layout = QVBoxLayout()
        header = QLabel("🚗 <b>Ford VBF Converter</b>")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 22px; padding: 18px;")
        main_layout.addWidget(header)

        meta_box = QGroupBox("VBF File Info")
        self.meta_label = QLabel("Select a VBF file to display info.")
        self.meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.meta_label.setWordWrap(True)
        vbox = QVBoxLayout()
        vbox.addWidget(self.meta_label)
        meta_box.setLayout(vbox)
        main_layout.addWidget(meta_box)

        form_layout = QVBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select .vbf file or drag & drop...")
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Save as .hex file...")

        btn_in = QPushButton("Browse Input VBF")
        btn_out = QPushButton("Browse Output HEX")
        btn_in.clicked.connect(self.browse_in)
        btn_out.clicked.connect(self.browse_out)

        form_row1 = QHBoxLayout()
        form_row1.addWidget(self.input_edit)
        form_row1.addWidget(btn_in)
        form_layout.addLayout(form_row1)

        form_row2 = QHBoxLayout()
        form_row2.addWidget(self.output_edit)
        form_row2.addWidget(btn_out)
        form_layout.addLayout(form_row2)
        main_layout.addLayout(form_layout)

        self.run_btn = QPushButton("Convert VBF to HEX")
        self.run_btn.clicked.connect(self.run_convert)
        main_layout.addWidget(self.run_btn)

        self.status_lbl = QLabel("Select VBF file and output location.")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_lbl)

        exit_btn = QPushButton("Exit")
        exit_btn.setStyleSheet(
            "background: #ff1744; color: #fff; font-weight: bold; border-radius: 8px; min-height: 36px; min-width: 120px;")
        exit_btn.clicked.connect(QApplication.quit)
        footer_row = QHBoxLayout()
        footer_row.addStretch(1)
        footer_row.addWidget(exit_btn)
        main_layout.addLayout(footer_row)

        self.setLayout(main_layout)
        self.setStyleSheet("""
            QWidget { background: #20232a; color: #bfc7d5; font-family: Segoe UI, Arial; }
            QPushButton { background: #304ffe; color: #fff; font-weight: bold; border-radius: 8px; min-height: 36px; min-width: 150px; }
            QPushButton:hover { background: #7c4dff; }
            QLineEdit { background: #282c34; color: #fff; border-radius: 6px; padding: 3px; }
            QLabel { color: #bfc7d5; }
            QGroupBox { border: 1px solid #304ffe; border-radius: 10px; margin-top: 10px; font-size: 16px; }
            QGroupBox:title { subcontrol-origin: margin; left: 10px; padding: 0 4px 0 4px; }
        """)

        self.input_edit.textChanged.connect(self.on_input_change)

    def init_sounds(self):
        self.success_sound = QSoundEffect()
        self.error_sound = QSoundEffect()
        try:
            success_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Sounds", "wav.wav"))
            if os.path.exists(success_path):
                self.success_sound.setSource(QUrl.fromLocalFile(success_path))
            self.success_sound.setVolume(0.7)
        except Exception:
            pass
        try:
            error_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "Sounds", "wav-4.wav"))
            if os.path.exists(error_path):
                self.error_sound.setSource(QUrl.fromLocalFile(error_path))
            self.error_sound.setVolume(0.7)
        except Exception:
            pass

    def closeEvent(self, event):
        if hasattr(self, 'success_sound'):
            self.success_sound.stop()
        if hasattr(self, 'error_sound'):
            self.error_sound.stop()
        super().closeEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith('.vbf'):
                event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            vbf_path = urls[0].toLocalFile()
            if vbf_path.lower().endswith('.vbf'):
                self.input_edit.setText(vbf_path)
                base = os.path.splitext(vbf_path)[0]
                outname = base + ".hex"
                self.output_edit.setText(outname)
                self.show_vbf_meta(vbf_path)

    def browse_in(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open VBF File", "", "VBF Files (*.vbf);;All Files (*)")
        if fname:
            self.input_edit.setText(fname)
            base = os.path.splitext(fname)[0]
            outname = base + ".hex"
            self.output_edit.setText(outname)
            self.show_vbf_meta(fname)

    def browse_out(self):
        fname, _ = QFileDialog.getSaveFileName(self, "Save HEX File", "", "HEX Files (*.hex);;All Files (*)")
        if fname:
            if not fname.lower().endswith('.hex'):
                fname += '.hex'
            self.output_edit.setText(fname)

    def on_input_change(self, path):
        self.show_vbf_meta(path)

    def show_vbf_meta(self, fname):
        if not fname or not os.path.exists(fname):
            self.meta_label.setText("No file selected or file does not exist.")
            return
        try:
            with open(fname, "rb") as f:
                data = f.read()
            meta = VBFMeta(data)
            if meta.valid:
                self.meta_label.setText(meta.summary_html())
            else:
                self.meta_label.setText(f"Error reading VBF metadata: {meta.error}")
        except Exception as e:
            self.meta_label.setText(f"Could not read file: {str(e)}")

    def validate_inputs(self):
        in_path = self.input_edit.text().strip()
        out_path = self.output_edit.text().strip()
        if not in_path or not out_path:
            QMessageBox.warning(self, "Input Required", "Please select both VBF and HEX file paths.")
            return False
        if not in_path.lower().endswith('.vbf'):
            QMessageBox.warning(self, "Invalid Input", "Input file must be a .vbf file.")
            return False
        if not os.path.isfile(in_path):
            QMessageBox.warning(self, "Invalid Input", "Input file does not exist.")
            return False
        return True

    def run_convert(self):
        if not self.validate_inputs():
            return
        in_path = self.input_edit.text().strip()
        out_path = self.output_edit.text().strip()
        if not out_path.lower().endswith('.hex'):
            out_path += '.hex'
            self.output_edit.setText(out_path)
        self.status_lbl.setText("Processing...")
        QApplication.processEvents()
        t0 = time.time()
        ret, msg = vbf_to_intel_hex(in_path, out_path)
        elapsed = time.time() - t0
        if ret == 1:
            self.status_lbl.setText(f"✅ Successfully converted in {elapsed:.2f}s!")
            try:
                self.success_sound.play()
            except Exception:
                QApplication.beep()
            QMessageBox.information(self, "Success", f"Conversion complete.\nHEX saved to:\n{out_path}")
        else:
            self.status_lbl.setText("❌ " + msg)
            try:
                self.error_sound.play()
            except Exception:
                QApplication.beep()
            QMessageBox.critical(self, "Failed", f"Conversion failed:\n{msg}")


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    gui = VBFConverterGUI()
    gui.show()
    sys.exit(app.exec_())
