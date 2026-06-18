# -*- coding: utf-8 -*-
import unittest

from micu_bsl.packets import BslPacketBuilder


class BslPacketBuilderTest(unittest.TestCase):
    def test_connection_packet_matches_original_shape(self):
        builder = BslPacketBuilder()
        packet = builder.connection_packet()
        self.assertEqual(packet[:4], b"\x80\x01\x00\x12")
        self.assertEqual(len(packet), 8)

    def test_password_packet_length(self):
        builder = BslPacketBuilder()
        packet = builder.password_packet(bytes(range(32)))
        self.assertEqual(packet[:4], b"\x80\x21\x00\x21")
        self.assertEqual(len(packet), 40)

    def test_firmware_packets_build_program_packet(self):
        builder = BslPacketBuilder()
        packets = builder.firmware_packets(["@C000", "01 02 03 04", "q"])
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0][:4], b"\x80\x09\x00\x20")
        self.assertEqual(packets[0][4:8], b"\x00\xC0\x00\x00")


if __name__ == "__main__":
    unittest.main()
