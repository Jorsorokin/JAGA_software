import struct

def read_char(buffer):
	return struct.unpack('B', buffer.read(1))[0]

def read_uint32(buffer):
	return struct.unpack('>I', buffer.read(4))[0]

def read_uint32le(buffer):
	return struct.unpack('<I', buffer.read(4))[0]

def read_int32(buffer):
	return struct.unpack('>i', buffer.read(4))[0]

def read_int32le(buffer):
	return struct.unpack('<i', buffer.read(4))[0]

def read_uint16(buffer):
	return struct.unpack('>H', buffer.read(2))[0]

def read_uint16le(buffer):
	return struct.unpack('<H', buffer.read(2))[0]

def read_doublele(buffer):
	return struct.unpack("<d", buffer.read(8))[0]
