import sys
import time

from struct_methods import *


class Packet:
    """Read a single JAGA packet. Can be given an input buffer, or constructed"""


    SAMPLES_PER_PACKET = {
        1: 500,
        2: 250,
        4: 125,
        8: 86,
        16: 43
    }

    TTL_READS_V0 = {  # (samples_per_packet / 8) + 1, aligned to 2-byte boundaries
        1  : 64,
        2  : 32,
        4  : 16,
        8  : 12,
        16 : 6
    }

    TTL_READS_V3 = {  # Aligned to 4-byte boundaries.
        1  : 64,
        2  : 32,
        4  : 16,
        8  : 12,
        16 : 8
    }

    # Bit flags in the bits_per_sample field, which in format 1 is called the "Mode word" field.
    # Mode word bit fields:
    # // Bit 15:     Is 1 if TTL info present
    # // Bit 14:     Is 1 if packet is CRC packet (format 1 only)
    # // Bit 13:     Is 1 if bottom 6 bits indicates # of queued packets (i.e. not yet sent)
    # // Bit 12:     Is 1 if bottom 6 bits indicates # of discarded packets since previous report (i.e. that could not be sent due to network traffic)
    # // Bits 8-11   Unassigned.
    # // Bits 0-7:   If format = 0, this is bits-per-sample (always 16)
	# If format = 1, indicates either the # of queued (unsent) packets, or the # of discarded packets
    TTL = 1 << 15
    CRC = 1 << 14
    QUEUED = 1 << 13
    DISCARDED = 1 << 12
    VALUE = 0x00FF

    def __init__(self, buffer=None, start_time=None, first_seconds=None,
                 first_sequence=None, channels=None, has_timestamp=True):
        self.buffer = buffer
        self.start_time = start_time
        self.first_seconds = first_seconds
        self.first_sequence = first_sequence
        self.all_samples = []
        self.ttl_bytes = None
        self.ttl_bits = None
        self.channels = channels
	self.has_timestamp = has_timestamp
        if self.buffer:
            # A buffer was supplied, so read data from the buffer.
            try:
                self.data_header()
                self.data_samples()
                if self.ttl:
                    if self.V0:
                        ttl_reads = Packet.TTL_READS_V0[self.channels]
                    else:
                        ttl_reads = Packet.TTL_READS_V3[self.channels]
                    self.ttl_bytes = []
                    self.ttl_bits = []
                    self.data_ttl(ttl_reads)
            except struct.error as e:
                # Out of data, exit cleanly.
		#sys.stderr.write(str(e) + "\n")  # TODO: Reenable
                raise ValueError
        # If self.buffer == None, then we're constructing a packet from scratch, for example when
        # reconstructing a packet from a CRC and the XOR of a series of packets.

    def data_header(self):
        """Read the data header."""
	if self.has_timestamp:
          self.timestamp = read_doublele(self.buffer)
        self.version = read_char(self.buffer)

        diagnostic_word = None
        if self.version == 0:
            self.V0 = True
            self.V3 = False
            read_char(self.buffer)  # Unused byte because version field is uint16 little-endian in v0 headers.
            channels = read_uint16le(self.buffer)  # uint16 in v0 header.
            mode_word = read_uint16le(self.buffer)
            self.samples_per_second = read_uint16le(self.buffer)
            self.seconds = read_uint16le(self.buffer)
            self.sample_count = read_uint16le(self.buffer)
            self.queued_packets = None
            self.discarded_packets = None
            self.cumulative_discarded = None
        elif self.version == 3:
            self.V0 = False
            self.V3 = True
            channels = read_char(self.buffer)  # uint8 in v3 header.
            diagnostic_word = read_uint16le(self.buffer)  # Only in v3 header.
            mode_word = read_uint16le(self.buffer)
            self.samples_per_second = read_uint16le(self.buffer)
            self.seconds = None
            self.sample_count = read_uint32le(self.buffer)
        else:
            sys.stderr.write("ERROR: Header version " + str(self.version) + " not supported.\n")
            raise ValueError

        # Calculated fields.
        self.ttl = (mode_word & Packet.TTL == Packet.TTL)
        self.crc = (mode_word & Packet.CRC == Packet.CRC)
        self.queued = (mode_word & Packet.QUEUED == Packet.QUEUED)
        self.discarded = (mode_word & Packet.DISCARDED == Packet.DISCARDED)
        if self.V0:
            self.bits_per_sample = (mode_word & Packet.VALUE)
        else:
            self.queued_packets = diagnostic_word if self.queued and diagnostic_word else None  # v3 behavior.
            self.discarded_packets = (mode_word & Packet.VALUE) if self.discarded else None
            self.bits_per_sample = None

        if self.crc:
            self.crc_interval = channels  # channels field overloaded in CRC packets.
            if not self.channels:
                raise AttributeError("channels parameter was not set for CRC packet.")
        else:
            self.channels = channels
        self.samples_per_packet = self.SAMPLES_PER_PACKET[self.channels]

    def data_ttl(self, ttl_reads):
        """Read TTL values at the end of the packet. Should only call if self.ttl=True."""
        for i in range(ttl_reads):
            self.ttl_bytes.append(read_char(self.buffer))
        for i in range(self.samples_per_packet):
            self.ttl_bits.append((self.ttl_bytes[i / 8] & (1 << (7 - (i % 8)))) > 0)
        assert(len(self.ttl_bytes) == ttl_reads)
        assert(len(self.ttl_bits) == self.samples_per_packet)

    def packet_assembly_time(self):
        if self.channels and self.samples_per_second:
            # Can only be calculated if channel number is known, i.e. for non-CRC
            # packets.
            return (float(self.samples_per_packet) / (float(self.samples_per_second)))
        else:
            return None

    def __str__(self):
        output = "=== packet v"
        output += str(self.version) + "\n"
        mode = []
        if self.crc: mode.append('CRC')
        if self.ttl: mode.append('TTL')
        if len(mode) > 0:
            output += " ".join(mode) + "\n"
	if self.has_timestamp:
          output += "Timestamp: " + self.time2str(self.timestamp) + "\n"
        output += str(self.channels) + " channels\n"
        output += (str(self.crc_interval) + " packets between CRC packets\n") if self.crc else ""
        output += (str(self.bits_per_sample) + " bits per sample\n") if self.bits_per_sample else ""
        output += (str(self.samples_per_second) + " samples per second\n") if self.samples_per_second else ""
        output += (str(self.queued_packets) + " packets in queue\n") if self.queued else ""
        output += (str(self.discarded_packets) + " packets discarded\n") if self.discarded_packets else ""
        output += (str(self.seconds) + " elapsed seconds\n") if self.seconds else ""
        output += str(self.sample_count) + " sample count\n"
        output += "First set of samples:\n"
        output += str(self.all_samples[0]) + "\n\n"
        return output

    def convert_v3_to_v0(self):
        """Provide backwards compatibility by converting a V3 packet to V0."""
        self.version = 0
        self.V0 = True
        self.V3 = False
        self.bits_per_sample = 16
        self.seconds = self.sample_count / self.samples_per_second
        self.sample_count = self.sample_count % self.samples_per_second
        self.queued = False
        self.queued_packets = None
        self.discarded = False
        self.discarded_packets = None
        if self.ttl:
            self.ttl_bytes_v0 = self.ttl_bytes[0:self.TTL_READS_V0[self.channels]]

    def set_start_time(self, start_time, first_sequence, first_seconds=0):
        """Set the actual start time and counters if known"""
        self.start_time = start_time
        self.first_seconds = first_seconds
        self.first_sequence = first_sequence

    def data_samples(self):
        """Read all the data samples from the packet"""
        for i in range(self.samples_per_packet):
            samples = []
            for j in range(self.channels):
                sample = read_uint16le(self.buffer)
                samples.append(sample)
            self.all_samples.append(samples)

    def show_samples(self, epoch=False, ttl_fix=False):
        """Display data samples from the packet. start_time must be known."""
        assert (self.start_time is not None)
        assert (self.first_seconds is not None)
        assert (self.first_sequence is not None)
        assert (self.channels is not None)  # CRC packets aren't samples, so timing is not needed.
        elapsed_time = self.get_elapsed_time(self.first_seconds, self.first_sequence)
        output = []
        if self.ttl and ttl_fix:  # Adjust for last-bit glitches.
            last_index = len(self.all_samples) - 1
            self.ttl_bits[last_index] = self.ttl_bits[last_index - 1]
        for i in range(len(self.all_samples)):
            fraction = float(i) * float(self.packet_assembly_time()) / float(self.samples_per_packet)
            current_time = self.start_time + elapsed_time + fraction
            if epoch:
                # Just output as floating point.
                timestr = "{:06f}".format(current_time)
            else:
                timestr = self.time2str(current_time)
            sample_string = timestr + "," + ",".join([str(x) for x in self.all_samples[i]])
            if self.ttl:
                sample_string += "," + ("1" if self.ttl_bits[i] else "0")
            output.append(sample_string)
        return output


    def time2str(self, current_time):
        """Convert a floating point time into human readable form"""
        secs, usecs = "{:0.06f}".format(current_time).split('.')
        time_struct = time.localtime(int(secs))
        return (time.strftime("%Y-%m-%d %H:%M:%S.", time_struct) +
                "{:06d}".format(int(usecs)))

    def get_elapsed_time(self, first_seconds, first_sequence):
        """Given starting counters and current timestamp, show time since start_time."""
        if self.V0:
            elapsed_samples = ((self.seconds * self.samples_per_second + self.sample_count)
                               - (first_seconds * self.samples_per_second + first_sequence))
        else:
            elapsed_samples = self.sample_count - first_sequence
        return float(elapsed_samples) / float(self.samples_per_second)

    def _mode_word(self):
        mode_word = 0
        mode_word |= (Packet.TTL if self.ttl else 0)
        mode_word |= (Packet.CRC  if self.crc else 0)
        mode_word |= (Packet.QUEUED if self.queued else 0)
        mode_word |= ((Packet.DISCARDED | self.discarded_packets) if self.discarded else 0)
        return mode_word

    def _diagnostic_word(self):
        diagnostic_word = 0
        diagnostic_word |= self.queued_packets
        return diagnostic_word

    def binary_packet(self):
        """Render the packet to binary form as if captured from a JAGA device."""
        output = struct.pack("<d", self.timestamp)
        if self.version == 0:
            output += struct.pack("<H", self.version)
            output += struct.pack("<H", self.channels)
            output += struct.pack("<H", self.bits_per_sample | self._mode_word())
            output += struct.pack("<HHH", self.samples_per_second, self.seconds, self.sample_count)
        elif self.version == 3:
            output += struct.pack("B", self.version)
            if self.crc:
                output += struct.pack("B", self.crc_interval)
            else:
                output += struct.pack("B", self.channels)
            output += struct.pack("<H", self._diagnostic_word())
            output += struct.pack("<H", self._mode_word())
            output += struct.pack("<H", self.samples_per_second)
            output += struct.pack("<I", self.sample_count)
        else:
            raise ValueError("Format version " + str(self.version) + " is invalid.")
        for samples in self.all_samples:
            for sample in samples:
                output += struct.pack("<H", sample)
        if self.ttl:
            if self.version == 0:
                self.ttl_bytes = [0] * Packet.TTL_READS_V0[self.channels]
            else:
                self.ttl_bytes = [0] * Packet.TTL_READS_V3[self.channels]
            for i in range(len(self.ttl_bits)):
                self.ttl_bytes[i / 8] |= self.ttl_bits[i] << (7 - (i % 8))
            for byte in self.ttl_bytes:
                output += struct.pack("B", byte)
        return output

    @staticmethod
    def possible_packet_lengths_v3():
        """Return a list of possible v3 packet lengths from most likely to least likely."""
        packet_lengths = []
        ttl_lengths = []
        for channel in sorted(Packet.TTL_READS_V3.keys(), reverse=True):
            # 8 byte timestamp + 12 byte header + # of uint16 samples * 2
            length = 20 + Packet.SAMPLES_PER_PACKET[channel] * channel * 2
            if length not in packet_lengths:
                packet_lengths.append(length)
            length += Packet.TTL_READS_V0[channel]  # with TTL data.
            if length not in ttl_lengths:
                ttl_lengths.append(length)
        return packet_lengths + ttl_lengths
