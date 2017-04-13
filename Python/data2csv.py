#!/usr/bin/python

# v1.0 2014-08-29

# Reads a JAGA capture file and prints the data as a CSV, with a timestamp
# for each set of samples. The initial timestamp is determined as follows:
#
# (1) The first SKIP_COUNT packets are skipped because these often have
#     buffered latency effects.
#
# (2) The next CALC_COUNT packets are examined and the first sample time is
#     extrapolated based on the packet timestamp and the counters in the
#     packet data.
#
# (3) Due to packet jitter the extrapolated start times are not identical,
#     so we average them to remove jitter effects. LATENCY seconds are
#     subtracted to represent the packet latency on the network.
#
# (4) All the SKIP_COUNT and CALC_COUNT packets are then printed, using
#     the extrapolated and averaged start time, and with the in-packet
#     counters providing timing since start of capture.

import argparse

import packet_buffer

parser = argparse.ArgumentParser(
    description="Convert a capture file into a .csv")
parser.add_argument('--matlab', action='store_true')
parser.add_argument('filename')
args = parser.parse_args()

pb = packet_buffer.PacketBuffer(args.filename)

for p in pb:
    if args.matlab:
        rows = p.show_samples(epoch=True, ttl_fix=True)
    else:
        rows = p.show_samples(ttl_fix=True)
    for row in rows:
        print row

# sys.stderr.write("Number of packets read: " + str(packet_count) + "\n")
# sys.stderr.write("Uncorrected start time: " + p.time2str(uncorrected_time) + "\n")
# sys.stderr.write("Extrapolated start time: " + p.time2str(first_timestamp) + "\n")
