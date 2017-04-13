__author__ = 'Markus De Shon'

import copy
import packet
import sys


class PacketBuffer():
    MIN_FILL = 100
    MAX_FILL = 1000
    SKIP_COUNT = 10  # Skip initial packets when calculating start time because their timing is odd.
    LATENCY = 0.003  # Latency of packet delivery on the network.

    def __init__(self, filename, debug=False):
        self.fh = open(filename, 'rb')
        self.channels = None
        self.first_seconds = None
        self.last_seconds = None
        self.first_sample_count = None
        self.last_sample_count = None
        self.start_time = None
        self.total_lost = 0
        self.crc_received = 0
        self.samples_per_packet = None
        self.samples_per_second = None
        self.packets_received = 0
        self.packets_recovered = 0
        self.packet_array = []
        self.packet_array_index = 0
        self.lost_since_last_crc = 0
        self.debug = debug

    def __del__(self):
        self.fh.close()

    def __iter__(self):
        return self

    def next(self):
        if len(self.packet_array) < PacketBuffer.MIN_FILL:
            self._fill_array()
        try:
            p = self.packet_array.pop(0)  # FIFO
            if (self.first_seconds is not None and self.first_sample_count is not None
                and self.start_time is not None):
                p.set_start_time(start_time=self.start_time, first_sequence=self.first_sample_count,
                                 first_seconds=self.first_seconds)
            return p
        except IndexError:
            # No packets left.
            raise StopIteration

    def _read_next(self):
        try:
            p = packet.Packet(self.fh, channels=self.channels)
            if p.crc:
                self.crc_received += 1
                return p, 0
            if self.channels is None and p.channels:
                self.channels = p.channels
                self.samples_per_packet = p.samples_per_packet
                self.samples_per_second = p.samples_per_second
            self.packets_received += 1
            lost_packets = 0
            if p.V0:
                if self.last_seconds:
                    lost_packets = self._count_lost_packets(p)
                self.last_seconds = p.seconds
                self.last_sample_count = p.sample_count
            else:  # V3 packets
                if self.last_sample_count:
                    lost_packets = self._count_lost_packets(p)
                self.last_sample_count = p.sample_count
            return p, lost_packets
        except ValueError:  # Ran out of data.
            return None, 0
        except AttributeError:
            # The first packet in the file is a CRC packet, so self.channels is not set yet.
            sys.stderr.write("WARNING: First packet was a CRC, seeking next packet to continue.\n")
            self._seek_channels()
            assert(self.channels is not None)
            # We've set self.channels from the next packet, so try again to read the leading CRC packet.
            return self._read_next()

    def _seek_channels(self):
        # The first packet was a CRC, so we need to find the channel count in the next packet.
        for length in packet.Packet.possible_packet_lengths_v3():
            self.fh.seek(length)
            try:
                sys.stderr.write("Trying offset " + str(length) + "\n")
                p = packet.Packet(self.fh)
                sys.stderr.write("Next packet header was found... continuing.\n")
                self.channels = p.channels
                # We found the right offset and set the self.channels value, so go back to the beginning.
                self.fh.seek(0)
                return
            except Exception as e:
                sys.stderr("WARNING: Exception received: " + e.message + "\n")
                # Try the next offset.
                continue
        sys.stderr.write("ERROR: Next packet header could not be found. Exiting.\n")
        sys.exit(1)

    def _count_lost_packets(self, p):
        assert (not p.crc)
        if p.V0:
            increment = self.samples_per_second * (p.seconds - self.last_seconds)
            increment += p.sample_count - self.last_sample_count
        else:
            increment = p.sample_count - self.last_sample_count
        lost = (increment / self.samples_per_packet) - 1
        if self.debug and lost > 0:
            sys.stderr.write(str(lost) + " packets lost.\n")
        return (increment / self.samples_per_packet) - 1

    def _fill_array(self):
        p, lost_packets = self._read_next()
        timestamps = []
        if self.first_sample_count is None:
            if p.V0:
                self.first_seconds = 0
                self.first_sample_count = (p.seconds * p.samples_per_second) + p.sample_count
            else:
                self.first_seconds = 0
                self.first_sample_count = p.sample_count
        while p and len(self.packet_array) < PacketBuffer.MAX_FILL - 1:
            array_length = len(self.packet_array)
            timestamps.append(p.timestamp)
            if lost_packets > 0:
                self.lost_since_last_crc += lost_packets
                self.total_lost += lost_packets
            if p.crc:
                if (array_length > p.crc_interval) and self.lost_since_last_crc > 0:
                    # Reconstruct a single missing packet. Need at least 1 packet of history before window.
                    if self.debug:
                        sys.stderr.write("Attempting to reconstruct packet using CRC.\n")
                    start_window = array_length - p.crc_interval + 1  # Only works for one lost packet.
                    end_window = array_length
                    if self.debug:
                        sys.stderr.write("start_window " + str(start_window) + " end_window "
                                         + str(end_window) + "\n")
                    (missing_index, missing_count, xor) = self._xor_over_window(start_window, end_window)
                    if self.debug:
                        sys.stderr.write("missing_index " + str(missing_index) + " missing_count "
                                         + str(missing_count) + "\n")
                    if missing_count == 1 and missing_index and start_window <= missing_index <= end_window:
                        if self.debug:
                            sys.stderr.write("Single missing packet found before sample_count "
                                             + str(self.packet_array[missing_index].sample_count) + "\n")
                        self._reconstruct_packet(p, missing_index, xor=xor)
                    else:
                        if self.debug:
                            sys.stderr.write("Could not reconstruct packet, missing " + str(missing_count)
                                             + " packets.\n")
                self.lost_since_last_crc = 0
            else:
                self.packet_array.append(p)
            p, lost_packets = self._read_next()
        if p and not p.crc:
            self.packet_array.append(p)  # The last valid packet that was read.
        if not self.start_time:
            if len(timestamps) > PacketBuffer.MIN_FILL * 2:
                timestamps = timestamps[PacketBuffer.MIN_FILL:]  # Drop the first MIN_FILL if we can.
            self.start_time = (sum(timestamps) / float(len(timestamps))) - PacketBuffer.LATENCY

    def _xor_over_window(self, start_window, end_window):
        xor = None
        missing_index = None
        missing_count = 0
        for i in range(start_window, end_window):
            interval = (self.packet_array[i].sample_count - self.packet_array[i - 1].sample_count)
            if (((self.packet_array[i].sample_count - self.packet_array[i - 1].sample_count)
                     / self.samples_per_packet) - 1 == 1):
                missing_index = i
                missing_count += 1
            if xor:
                self._xor_arrays(xor, self.packet_array[i].all_samples)
            else:
                # xor not defined yet, set to the samples from the first packet.
                xor = copy.deepcopy(self.packet_array[i].all_samples)
        return missing_index, missing_count, xor

    def _reconstruct_packet(self, crc_packet, missing_index=None, xor=None, start_window=None, end_window=None):
        # Reconstruct packet that would have appeared before missing_index within window
        # Two usage modes:
        # 1) set xor, missing_index and optionally start_window, end_window OR
        # 2) only set start_window, end_window (need to calculate xor and find missing_index).
        if not xor:
            # Need to calculate xor over the window.
            assert (start_window is not None and start_window >= 1)
            assert (end_window is not None and end_window >= start_window)
            (missing_index, missing_count, xor) = self._xor_over_window(start_window, end_window)
        new_packet = copy.deepcopy(self.packet_array[missing_index - 1])  # Start with an existing packet.
        new_packet.timestamp = (self.packet_array[missing_index].timestamp + self.packet_array[
            missing_index - 1].timestamp) / 2.0
        new_packet.sample_count = new_packet.sample_count + self.samples_per_packet
        self._xor_arrays(xor, crc_packet.all_samples)
        new_packet.all_samples = xor
        self.packet_array.insert(missing_index, new_packet)
        self.packets_recovered += 1

    def _xor_arrays(self, a, b):
        assert (len(a) == len(b))
        for i in range(len(b)):
            for j in range(len(b[i])):
                a[i][j] ^= b[i][j]
