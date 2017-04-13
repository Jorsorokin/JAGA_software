#!/usr/bin/python

import argparse
import packet_buffer
import sys

parser = argparse.ArgumentParser(
    description="Calculate statistics for a JAGA capture file.")
parser.add_argument('--debug', action='store_true')
parser.add_argument('filename')
args = parser.parse_args()

pb = packet_buffer.PacketBuffer(args.filename, debug=args.debug)

count = 0
version = None

last_sample_count = None
for packet in pb:
    count += 1
    if args.debug and last_sample_count:
        increment = (packet.sample_count - last_sample_count) / packet.samples_per_packet
        if increment > 1:
            sys.stderr.write(str(increment - 1) + " packets unrecovered at count " + str(count) + "\n")
    last_sample_count = packet.sample_count
    if version is None:
        version = packet.version

if count == 0:
    sys.stderr.write("ERROR: File did not contain any packets... Exiting.\n")
    sys.exit(1)

print "Format version: ", version
print "Sampling rate: ", pb.samples_per_second
print "No. channels: ", pb.channels
print "Data packets received: ", pb.packets_received
if pb.crc_received and pb.crc_received > 0:
    print "CRC packets received: ", pb.crc_received
print "Packets lost: ", pb.total_lost
if version != 0:
    print "Packets recovered: ", pb.packets_recovered
    print "Packets after recovery: ", count
print "Total packets expected: ", pb.packets_received + pb.total_lost
if version == 0:
    print "Loss rate: ", float(pb.total_lost) / float(pb.packets_received + pb.total_lost)
else:
    print "Raw loss rate: ", float(pb.total_lost) / float(pb.packets_received + pb.total_lost)
    print "Net loss rate: ", float((pb.packets_received + pb.total_lost) - count) / float(pb.packets_received + pb.total_lost)