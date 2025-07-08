import os
import struct
import ctypes
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QLineEdit, QMessageBox, QHBoxLayout, QStyleFactory
)
from PyQt5.QtCore import Qt


def convert_vbf2hex(input_vbf_file, output_hex_file):
    # file exists check
    if not os.path.exists(input_vbf_file):
        return 0, "Input file does not exist."

    in_file_size = os.path.getsize(input_vbf_file)
    if in_file_size == 0:
        return 0, "Input file is empty."

    with open(input_vbf_file, 'rb') as in_file:
        # Find last '}'
        count_open = count_close = 0
        found_last_one = False
        orig_pos = in_file.tell()
        while True:
            b = in_file.read(1)
            if not b:
                break
            if b == b'{':
                count_open += 1
            elif b == b'}':
                count_close += 1
            if count_open > 0 and count_open == count_close:
                found_last_one = True
                break
        if not found_last_one:
            return 0, "Invalid VBF format: unmatched braces."

        # read base address and size
        base_bytes = in_file.read(4)
        size_bytes = in_file.read(4)
        if len(base_bytes) < 4 or len(size_bytes) < 4:
            return 0, "Corrupt VBF: missing base/size."
        base = struct.unpack(">I", base_bytes)[0]
        size = struct.unpack(">I", size_bytes)[0]

        try:
            with open(output_hex_file, 'w+b') as out_file:
                # Header
                out_file.write(b"\n")
                out_file.write(f"VBF source file = {input_vbf_file}\n".encode())
                out_file.write(b"VBF source file = COMPRESSED\n")
                out_file.write(b"HEX output file = COMPRESSED\n\n")

                ul_byte = 0
                block_address = base
                ul_record_checksum_total = 0
                us_section_counter = 0
                us_start_string = True
                line = ""
                block_open = False
                finished_line = False

                hex_chars = "0123456789ABCDEF"
                file_items = []

                while size:
                    ul_hex_address = ul_byte + block_address
                    value_byte = in_file.read(1)
                    if not value_byte:
                        break
                    value = struct.unpack("B", value_byte)[0]
                    if (ul_byte & 0xFFFF) == 0:
                        block_open = True
                        line = ":02000004"
                        line += "%04X" % (ul_hex_address >> 16)
                        ul_extrecord_checksum = -(((ul_hex_address >> 24) & 0xFF) +
                                                  ((ul_hex_address >> 16) & 0xFF) + 6)
                        line += "%02X\n" % ctypes.c_uint8(ul_extrecord_checksum).value
                        us_section_counter = ul_hex_address & 0xFFFF
                        file_items.append(line)
                        line = ""

                    if us_start_string:
                        block_open = True
                        line = ":20%04X00" % us_section_counter
                        us_start_string = False

                    line += hex_chars[(value >> 4) & 0xF] + hex_chars[value & 0xF]
                    ul_record_checksum_total += value
                    finished_line = False

                    if ((ul_byte & 0x1F) == 31):  # 32 bytes
                        finished_line = True
                        block_open = False
                        ul_record_checksum_total += 32
                        ul_record_checksum_total += (us_section_counter & 0xFF)
                        ul_record_checksum_total += (us_section_counter >> 8) & 0xFF
                        ul_record_checksum_2 = -ul_record_checksum_total
                        line += "%02X\n" % (ctypes.c_uint8(ul_record_checksum_2).value)
                        file_items.append(line)
                        ul_record_checksum_total = 0
                        us_start_string = True
                        us_section_counter = (us_section_counter + 32) & 0xFFFF
                        line = ""
                    size -= 1
                    ul_byte += 1

                if block_open and not finished_line:
                    if file_items:
                        file_items.pop()

                file_items.append(":00000001FF\n")
                for item in file_items:
                    out_file.write(item.encode() if isinstance(item, str) else item)

            return 1, "Success"
        except Exception as e:
            return 0, f"Error writing HEX: {str(e)}"


class VBFConverterGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ford VBF Converter")
        self.setMinimumWidth(560)
        self.setMinimumHeight(260)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint)
        # High DPI support
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        # Layout
        main_layout = QVBoxLayout()
        header = QLabel("🚗 <b>Ford VBF Converter</b>")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 22px; padding: 18px;")
        main_layout.addWidget(header)

        form_layout = QVBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select .vbf file...")
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

        self.setLayout(main_layout)
        self.setStyleSheet("""
            QWidget { background: #20232a; color: #bfc7d5; font-family: Segoe UI, Arial; }
            QPushButton { background: #304ffe; color: #fff; font-weight: bold; border-radius: 8px; min-height: 36px; min-width: 150px; }
            QPushButton:hover { background: #7c4dff; }
            QLineEdit { background: #282c34; color: #fff; border-radius: 6px; padding: 3px; }
            QLabel { color: #bfc7d5; }
        """)

    def browse_in(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open VBF File", "", "VBF Files (*.vbf);;All Files (*)")
        if fname:
            self.input_edit.setText(fname)
            # suggest default output
            outname = os.path.splitext(fname)[0] + ".hex"
            self.output_edit.setText(outname)

    def browse_out(self):
        fname, _ = QFileDialog.getSaveFileName(self, "Save HEX File", "", "HEX Files (*.hex);;All Files (*)")
        if fname:
            self.output_edit.setText(fname)

    def run_convert(self):
        in_path = self.input_edit.text().strip()
        out_path = self.output_edit.text().strip()
        if not in_path or not out_path:
            QMessageBox.warning(self, "Input Required", "Please select both VBF and HEX file paths.")
            return
        self.status_lbl.setText("Processing...")
        QApplication.processEvents()
        ret, msg = convert_vbf2hex(in_path, out_path)
        if ret == 1:
            self.status_lbl.setText("✅ Successfully converted!")
            QMessageBox.information(self, "Success", f"Conversion complete.\nHEX saved to:\n{out_path}")
        else:
            self.status_lbl.setText("❌ " + msg)
            QMessageBox.critical(self, "Failed", f"Conversion failed:\n{msg}")


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    # Dark Fusion style
    app.setStyle(QStyleFactory.create("Fusion"))
    gui = VBFConverterGUI()
    gui.show()
    sys.exit(app.exec_())
