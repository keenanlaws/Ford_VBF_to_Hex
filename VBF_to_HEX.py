import os
import struct
import ctypes


def convert_vbf2hex(input_vbf_file, output_hex_file):

    # does the file exists
    if os.path.exists(input_vbf_file) == False:
        return 0

    # check file size
    in_file_size = os.path.getsize(input_vbf_file)

    if in_file_size == 0:
        return 0

    # open input file
    in_file = open(input_vbf_file, 'rb')

    # find last } in the script file
    count_open = count_close = 0
    found_last_one = False

    while in_file_size:

        value = in_file.read(1)

        if value == '{':
            count_open += 1
        elif value == '}':
            count_close += 1

        if count_open > 0 and count_open == count_close:
            found_last_one = True
            break

        in_file_size -= 1

    #
    if found_last_one == False:
        in_file.close()
        return 0

    # base
    base = struct.unpack(">I", in_file.read(4))[0]

    # binary blob size
    size = struct.unpack(">I", in_file.read(4))[0]

    # create output file
    out_file = open(output_hex_file, 'w+b')

    out_file.write("\n")
    out_file.write("VBF source file = %s\n" % input_vbf_file)
    out_file.write("VBF source file = COMPRESSED\n")
    out_file.write("HEX output file = COMPRESSED\n")
    out_file.write("\n")

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

        # read one unsigned byte
        value = struct.unpack("B", in_file.read(1))[0]

        # section
        if (ul_byte & 0xFFFF) == 0:

            block_open = True

            line = ":"
            line += "02000004"

            line += "%04X" % (ul_hex_address >> 16)

            ul_record_checksum = (((ul_hex_address >> 24) & 0xFF) + ((ul_hex_address >> 16) & 0xFF) + 6)
            ul_extrecord_checksum = - ( ((ul_hex_address >> 24) & 0xFF) + ((ul_hex_address >> 16) & 0xFF) + 6)

            #print("%08X %08X + %08X + 6 = %08X" % (ul_hex_address, hibyte(ul_hex_address), byte2(ul_hex_address), ctypes.c_uint8(ul_extrecord_checksum).value) )

            line += "%02X" % ctypes.c_uint8(ul_extrecord_checksum).value

            line += "\n"

            us_section_counter = ul_hex_address & 0xFFFF

            file_items.append(line)
            line = ""

        # new line prefix
        if us_start_string is True:

            block_open = True

            line = ":"
            line += hex_chars[2]
            line += hex_chars[0]
            line += hex_chars[us_section_counter >> 12]
            line += hex_chars[(us_section_counter >> 8) & 0xF]
            line += hex_chars[(us_section_counter >> 4) & 0xF]
            line += hex_chars[us_section_counter & 0xF]
            line += hex_chars[0]
            line += hex_chars[0]

            us_start_string = False

            file_items.append(line)
            line = ""

        # char from the blob
        line += hex_chars[(value >> 4) & 0x0F] + hex_chars[value & 0x0F]

        # update checksum with the current byte
        ul_record_checksum_total += value

        finished_line = False

        # line is finished, attach checksum
        if ((ul_byte & 0x1F) == 31):

            finished_line = True
            block_open = False

            ul_record_checksum_total += 32
            ul_record_checksum_total += (us_section_counter & 0xFF)
            ul_record_checksum_total += (us_section_counter >> 8) & 0xFF

            ul_record_checksum_2 = - ul_record_checksum_total

            line += hex_chars[(ul_record_checksum_2 >> 4) & 0xF] + hex_chars[ul_record_checksum_2 & 0xF]
            line += "\n"

            file_items.append(line)

            ul_record_checksum_total = 0
            us_start_string = True

            us_section_counter = (us_section_counter + 32) & 0xFFFF

        # update counters

        size -= 1
        ul_byte += 1

    #print(block_open)
    #print(finished_line)

    if block_open is True and finished_line is False:
        file_items.pop()

    file_items.append(":00000001FF\n")

    for item in file_items:
        out_file.write(item)

    out_file.close()

    ret = 1

    return ret

#
# dd big_endian_base
# dd big_endian_size
# db data
# dw big_endian_crc
#

# Example below
# result = convert_vbf2hex("E:\\dev\\work\\ford\\ford\\HK62-12K532-PMD.vbf", "E:\\dev\\work\\ford\\ford\\HK62-12K532-PMD.vbf.hex")
# print result

result = convert_vbf2hex("Input File", "Output file")
print result


