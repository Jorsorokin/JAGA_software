#!/usr/bin/python
import errno
import os
import Queue
import signal
import socket
import struct
from subprocess import Popen, PIPE
import sys
import threading
import time

# System-specific imports
if os.name == 'nt':
  import datetime
  import msvcrt
else:
  import fcntl

PORT=55000
DEFAULT_FILEROOT='jaga_samples_py'
BUFSIZE=2048   # Needs to be >= maximum packet payload size.
MATLAB_SLEEP=6  # Number of seconds to sleep while MATLAB is starting up.
BUSY_LOOP_SLEEP=0.5  # Number of seconds to sleep in busy loop if on hold.
DISPLAY_SLEEP=0  # Number of seconds to wait for MATLAB to display a plot before capturing more data.
if os.name == 'nt':
  MATLAB_PATH="C:\\Program Files\\MATLAB\\R2012b\\bin\\matlab.exe"  # A possible Windows path.
else:
  MATLAB_PATH="/usr/local/bin/matlab"   #  A possible path on Unix-like systems.
DATA_PATH='Data'   # Subdirectory to store data in.

class Capture():
  '''Open UDP port to receive data and save to a file.'''
  def __init__(self, fileroot=DEFAULT_FILEROOT, port=PORT):
    if os.name == 'nt':
      self.windows = True # This is Windows OS
    else:
      self.windows = False
    self.ESC = '\x1b'
    self.fileroot = fileroot
    self.s = socket.socket(type=socket.SOCK_DGRAM)
    self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.s.bind(('0.0.0.0', port))
    sys.stderr.write("Listening on port " + str(port) + "\n")
    self._no_timeout()
    if not os.path.exists(DATA_PATH):
      os.mkdir(DATA_PATH)
    self.filename = self.gen_filename()
    self.q = Queue.Queue()
    self.end = 'END'
    self.p = None  # No matlab instance until we open one.
    self.rotate = False  # Set to True when we need to rotate files.
    self.buffer = True   # Put packets into the capture queue.
    self.waiting_for_return = False  # Set to true when user is prompted to hit return.


  def _no_timeout(self):
    if self.windows:
      self.s.settimeout(None)
    else:
      self.s.settimeout(0)    

  def gen_filename(self):
    if self.windows:
      return os.path.join(DATA_PATH, datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%H-%M-%S_') + self.fileroot + '.dat')
    else:
      return os.path.join(DATA_PATH, time.strftime('%Y-%m-%d_%H-%M-%S_', time.localtime()) + self.fileroot + '.dat')

  def start_capture(self):
    writer = threading.Thread(target=self.writer_thread)
    writer.daemon = True
    writer.start()
    self.capture_thread()

  def end_capture(self):
    sys.stderr.write("Ending capture.\n")
    self.s.close()
    if not self.waiting_for_return:
      self.q.put(self.end)
      self.q.join()

  def writer_thread(self):
    self._open_file()
    packet_count = 0
    while True:
      packet_string = self.q.get()
      if packet_string != self.end:
        packet_count = packet_count + 1
        self.fh.write(packet_string)
      else:
        self.buffer = False
        sys.stderr.write("Wrote " + str(packet_count) + " packets to file " + self.filename + ".\n")
        packet_count = 0
        self.fh.close()
        if self.keep_capturing:
          sys.stderr.write("Hit RETURN to continue capture in a new file.\n")
          self.waiting_for_return = True
          sys.stdin.readline()
          self.waiting_for_return = False
          self.buffer = True
          self.filename = self.gen_filename()
          self._open_file()
        else:
          self.q.task_done()
          break  # We're exiting, so leave the infinite loop.
      self.q.task_done()

  def _open_file(self):
    sys.stderr.write("Opening file " + self.filename + "\n")
    self.fh = open(self.filename, 'wb')

  def capture_thread(self):
    self.timeout_set = False
    self.keep_capturing = True
    sys.stderr.write("Ready to capture.\n")
    while self.keep_capturing:
      if self.waiting_for_return:
        time.sleep(BUSY_LOOP_SLEEP)
        continue
      if self.windows:
        if msvcrt.kbhit() and msvcrt.getch() == self.ESC:
          # Someone hit the ESC key.
          self.rotate = True
      if self.rotate:
        self.rotate_file()
        self.rotate = False
      try:
        data = self.s.recv(BUFSIZE)
        if not self.buffer:
          continue  # Don't save this packet.
        if not self.timeout_set:
          sys.stderr.write("Receiving data.\n")
          self.s.settimeout(1.0)
          self.timeout_set = True
        timestamp = time.time()
        packet_string = struct.pack("<d", timestamp) + data
        self.q.put(packet_string)
      except socket.timeout:
        sys.stderr.write("Stopped receiving data.\n")
        self.rotate = True
      except KeyboardInterrupt:
        sys.stderr.write("Capture terminated.\n")
        break
      except socket.error, e:
        if e.errno == errno.EAGAIN:
          continue
        if e.errno == errno.EINTR:
          # We're handling a signal, this is normal.
          continue
        else:
          raise e
    self.end_capture()

  def rotate_file(self):
    file_to_read = self.filename
    current_filehandle = self.fh
    self.q.put(self.end)
    while not current_filehandle.closed:
      pass # Wait until the capture file has been closed.
    if self.p:
      # Call matlab with the finished filename.
      sys.stderr.write("Calling MATLAB to display " + file_to_read + ".\n")
      self.p.stdin.write("samples = plot_jaga('" + file_to_read + "');\n\n")
      time.sleep(DISPLAY_SLEEP)
    self._no_timeout()
    self.timeout_set = False

  def open_matlab(self):
    sys.stderr.write("Launching MATLAB...")
    p = Popen(MATLAB_PATH, stdin = PIPE, stdout=PIPE, stderr=PIPE)
    #p = Popen(MATLAB_PATH, stdin = PIPE)   # Debug.
    if not self.windows:
      flags = fcntl.fcntl(p.stdin, fcntl.F_GETFL)
      fcntl.fcntl(p.stdin, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    self.p = p
    time.sleep(MATLAB_SLEEP)  # Let MATLAB start up fully before continuing.
    sys.stderr.write("done.\n")

  def sigint_handler(self, signum, frame):
    self.keep_capturing = False

  def sigtstp_handler(self, signum, frame):
    self.rotate = True
    if self.p:
      # MATLAB needs a start to continue running.
      self.p.send_signal(signal.SIGCONT)

  def __del__(self):
    self.fh.close()
    self.s.close()


if __name__ == '__main__':
  try:
    port_number = int(sys.argv[1])
  except:
    port_number = None
  if len(sys.argv) == 3:
    fileroot = sys.argv[2]
  else:
    fileroot = None
  if port_number and fileroot:
    c = Capture(port=port_number, fileroot=fileroot)
  elif port_number:
    c = Capture(port=port_number)
  else:
    c = Capture()
  if c.windows:
    signal.signal(signal.SIGINT, c.sigint_handler)
    sys.stderr.write("Type CTRL-C to quit.\n")
    #signal.signal(signal.SIGBREAK, c.sigtstp_handler)
    sys.stderr.write("Type ESC to rotate to a new capture file.\n")
  else:
    signal.signal(signal.SIGINT, c.sigint_handler)
    sys.stderr.write("Type CTRL-C to quit.\n")
    signal.signal(signal.SIGTSTP, c.sigtstp_handler)
    sys.stderr.write("Type CTRL-Z to rotate to a new capture file.\n")
  if len(sys.argv) > 1:
    if sys.argv[1] == '-matlab':
      c.open_matlab()
  c.start_capture()
