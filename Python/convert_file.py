#!/usr/bin/python
"""Convert file with v3 packets to v0 packets, for backwards compatibility."""

__author__ = 'Markus De Shon'

import sys

import packet_buffer

pb = packet_buffer.PacketBuffer(sys.argv[1])
outfile = open(sys.argv[1] + ".v0", 'wb')

for p in pb:
    p.convert_v3_to_v0()
    outfile.write(p.binary_packet())

outfile.close()