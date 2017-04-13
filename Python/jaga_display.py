#!env python

import argparse
import io
import math
import matplotlib
import os
import platform
if platform.system() == 'Darwin':  # OSX
  matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy
import socket
import struct
import sys
import threading
import time
import Queue

from packet import Packet

import profile

# Global queues
queues = []  # Per-thread working queue.
message_queue = Queue.Queue()
run_flag = True


class CaptureThread(threading.Thread):
 
  def __init__(self, bind_port, length, label, data_dir='Data'):
    threading.Thread.__init__(self)
    self.bind_port = bind_port
    self.length = length
    self.label = label
    self.packet_count = 0
    self.data_dir = data_dir

  def run(self):
    self.sock = socket.socket(type=socket.SOCK_DGRAM)
    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.sock.bind(('0.0.0.0', self.bind_port))
    message_queue.put('Listening to port {}\n'.format(self.bind_port))
    filename = self.generate_filename()
    message_queue.put('Writing to file {}\n'.format(filename))
    self.outfile = open(filename, 'wb')
    while run_flag:
      data, address = self.sock.recvfrom(self.length)
      timestamp = time.time()
      self.outfile.write(struct.pack("<d", timestamp) + data)
      self.packet_count += 1
      if queues[self.label].empty():
        # Only add data if the previous data has been displayed already.
        queues[self.label].put(data)

  def generate_filename(self):
    fileroot = 'jaga.dat'
    if os.name == 'nt':
      return os.path.join(self.data_dir, datetime.datetime.fromtimestamp(
          time.time()).strftime('%Y-%m-%d_%H-%M-%S_') + fileroot)
    else:
      return os.path.join(self.data_dir, time.strftime('%Y-%m-%d_%H-%M-%S_',
          time.localtime()) + fileroot)
  

  def __del__(self):
    message_queue.put("Received {} packets from device {}.\n".format(
        self.packet_count, self.label))
    self.outfile.close()

class MessageThread(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)

  def run(self):
    while run_flag:
      if not message_queue.empty():
        sys.stderr.write(message_queue.get() + "\n")
      time.sleep(3)


class JagaMultiDisplay:
  """Receive data from one or more JAGA devices and display."""

  def __init__(self, num_devices=1, starting_port=55000, data_dir='Data'):
    # Passed variables.
    self.num_devices = num_devices
    self.starting_port = starting_port
    self.data_dir = data_dir
    # Internal variables.
    self.data_frame = None
    self.threads = []
    self.message_thread = MessageThread()
    self.message_thread.start()
    self.channels = 16  # Need a default until we've read the first packet.
    self.length = 1500
    self.first_packet = True
    self.fh = io.BytesIO()
    self.axes = []
    self.lines = []
    self.fig = plt.figure(figsize=(15,10))
    self.fig.canvas.set_window_title("Jaga")


  def first_parsed_packet_(self, p, length):
    self.length = length
    self.channels = p.channels
    self.num_axes = self.channels * self.num_devices
    self.data_frame = [[] for x in range(self.num_axes)]
    rows = int(math.sqrt(self.num_axes))
    columns = self.num_axes / rows
    while rows * columns < self.num_axes:
      columns += 1
    for i in range(self.num_axes):
      self.axes.append(self.fig.add_subplot(rows, columns, i + 1))
      self.axes[i].clear()
      self.axes[i].set_ylim([0, 65535])
      #self.axes[i].set_ylim([32000, 33000])
      self.lines.append(self.axes[i].plot(range(p.samples_per_packet))[0])
    wm = plt.get_current_fig_manager()
    wm.window.state('zoomed')
    plt.show(False)
    plt.draw()

  def start(self):
    """Start capturing data on the bound ports, and display."""
    if os.path.exists(self.data_dir):
      if not os.path.isdir(self.data_dir):
        sys.stderr.write(
            "ERROR: Path {} exists, but is not a directory\n".format(
                self.data_dir))
        return
    else:
      os.makedirs(self.data_dir)
    for i in xrange(self.num_devices):
      sys.stderr.write("Starting capture for device {}\n".format(i))
      queues.append(Queue.Queue())
      self.threads.append(CaptureThread(
          self.starting_port + i,  # bind_port
	  self.length,             # length
	  i,                       # label
          self.data_dir))          # data_dir
      self.threads[i].start()
    frames = 0
    while run_flag:
      if self.data_frame:
        self.data_frame = [[] for x in range(self.num_axes)]
      for i in xrange(self.num_devices):
	crc = True
	data = None
	p = None
	while crc:
          data = queues[i].get()  # Blocks until data is available.
          self.fh.seek(0)
          self.fh.write(data)
          self.fh.seek(0)
          p = Packet(self.fh, channels=self.channels, has_timestamp=False)
	  crc = p.crc
	if self.first_packet:
	  self.first_parsed_packet_(p, len(data))
	  self.first_packet = False
	t = numpy.transpose(p.all_samples)
	for k in xrange(self.channels):
	  #self.data_frame[i * self.channels + k] = t[k]
	  axis = i * self.channels + k
	  self.lines[axis].set_ydata(t[k])
	  #self.fig.canvas.blit(self.axes[axis].bbox)
      #for i in range(self.num_axes):
      #  self.axes[i].clear()
#	#self.axes[i].set_title("Ch " + str(i + 1))
#	self.axes[i].plot(self.data_frame[i])
#        self.fig.canvas.blit(self.axes[i].bbox)
      plt.draw()
      self.fig.canvas.draw()
      self.fig.canvas.flush_events()


  #def __del__(self):
  #  del self.message_thread
  #  for thread in self.threads:
  #    del thread

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--starting_port', type=int,
                      help='First port number to listen to for data.',
		      default=55000)
  parser.add_argument('--num_devices', type=int,
                      help='Number of devices to listen for.', default=1)
  parser.add_argument('--data_dir', type=str,
                      help='Directory to write data files to.',
                      default='Data')
  args = parser.parse_args()
  md = JagaMultiDisplay(args.num_devices, args.starting_port, args.data_dir)
  try:
    run_flag = True
    md.start()
  except KeyboardInterrupt:
    print "Received interrupt, exiting."
    run_flag = False
