"""
jaga_display.py
"""

#!env python
import argparse, io, math, os, platform, numpy, socket, struct, sys, threading, time, Queue, matplotlib
if platform.system() == 'Darwin':  # OSX
  matplotlib.use('Qt4Agg')
import matplotlib.pyplot as plt
plt.style.use('dark_background')
import matplotlib.colors as colors
import matplotlib.cm as cm
from packet import Packet
from numba import jit

# Global queues
queues = []  # Per-thread working queue.
message_queue = Queue.Queue() # construct a Queue object simply for printing messages 
run_flag = True # <-- might be more efficient to avoid global variable?

# ========================================
class CaptureThread(threading.Thread): 
  """
  class used inside "JagaMultiDisplay" for threading data stream
  """

  def __init__(self, bind_port, length, label, data_dir, file_name):
    threading.Thread.__init__(self) # are we appending an instance of the threading class here?
    self.bind_port = bind_port
    self.length = length
    self.label = label
    self.packet_count = 0
    self.data_dir = data_dir
    self.file_name = file_name
  
  def __del__(self):
    """
    closes the output file to stop the writing process
    """
    message_queue.put("Received {} packets from device {}.\n".format(
        self.packet_count, self.label))
    self.outfile.close()    

  def run(self):
    """
    connects to the IP client "JAGA" and continuously receives data
    packets via the UDP framework (through the python "socket" class)

    If we are only streaming to disk without need for real-time control,
    it may be advantageous to use TCP vs. UDP data streaming to minimize
    packet drop / reordering. - JMS
    """
    # Initiate the socket to connect to client JAGA 
    self.sock = socket.socket(type=socket.SOCK_DGRAM) # DGRAM = connectionless?
    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.sock.bind(('0.0.0.0', self.bind_port))

    # print the port number and generate a file name with the date-time appended
    message_queue.put('Listening to port {}\n'.format(self.bind_port))
    filename = self.generate_filename()
    message_queue.put('Writing to file {}\n'.format(filename))
    self.outfile = open(filename, 'wb') # open the file for writing binary data ("wb") since not writing text files
  
    while run_flag:
      data, address = self.sock.recvfrom(self.length) # read the data packet. Could split data from here too
      timestamp = time.time() # get the time-stamp of the data packet read
      self.outfile.write(struct.pack("<d", timestamp) + data) # write to the output file...saves us from over-riding data
      self.packet_count += 1

      # Only add data if the previous data has been displayed already.
      # ... could this run into the issue of overlapping data packets if 
      # display time exceeds read time? - JMS
      if queues[self.label].empty(): 
        queues[self.label].put(data) # no timeout

  def generate_filename(self):
    """
    Generate the file name for the streamed data based on operating system.

    If the file name is not provided at terminal prompt, default to "jaga.dat"
    Automatically append date-time information to the file name.
    """
    if os.name == 'nt':
      return os.path.join(self.data_dir, datetime.datetime.fromtimestamp(
          time.time()).strftime('%Y-%m-%d_%H-%M-%S_') + self.file_name + '.dat')
    else:
      return os.path.join(self.data_dir, time.strftime('%Y-%m-%d_%H-%M-%S_',
          time.localtime()) + self.file_name + '.dat')


# ========================================
class MessageThread(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)

  def run(self):
    while run_flag:
      if not message_queue.empty():
        sys.stderr.write(message_queue.get() + "\n") 
      time.sleep(3) # could just put the timeout into the message_que.get() method? 


# ========================================
class JagaMultiDisplay:
  """Receive data from one or more JAGA devices and display."""

  def __init__(self, data_dir, file_name, num_devices, starting_port, plot_memory, color_map):
    
    # Passed variables.
    self.num_devices = num_devices
    self.starting_port = starting_port
    self.data_dir = data_dir
    self.file_name = file_name
    self.plot_memory = plot_memory
    self.color_map = color_map

    # Internal variables.
    self.plotData = None
    self.threads = []
    self.message_thread = MessageThread() # instance of the MessageThread class above
    self.message_thread.start()
    self.channels = 16  # Need a default until we've read the first packet.
    self.length = 1500 # data packet byte size? 
    self.first_packet = True
    self.fh = io.BytesIO() # instance of the BytesIO class from the io package. Provides interface for buffered I/O data
    self.axes = []
    self.lines = []

  @jit
  def first_parsed_packet_(self, p, length):
    """Initiates the figure and subplot axes for displaying the data."""
    
    # initiate the number of rows/columns of subplots for displaying all channels
    self.length = length
    self.channels = p.channels
    self.num_axes = self.channels * self.num_devices
    rows = int(math.sqrt(self.num_axes))
    columns = self.num_axes / rows
    while rows * columns < self.num_axes:
      columns += 1

    # initiate the color map for the figure
    colorVals = xrange(self.num_axes)
    scalarMap = cm.ScalarMappable(norm=colors.Normalize(vmin=0,vmax=colorVals[-1]),cmap=plt.get_colormap(self.color_map))

    # initiate the figure
    self.fig,_ = plt.subplots(rows,columns,sharex=True,sharey=True,figsize=(12,8)) # initiates matplotlib figure
    self.fig.canvas.set_window_title("JAGA")
    self.fig.subplots_adjust(hspace=0,wspace=0.1,left=0.05,right=0.95) # remove vertical space, leave small horizontal space, reduce left/right spaces

    # initiate the plotting data as all zeros. Will be replaced continuously with incomming data,
    # and this allows us to have some memory in our plots for visual clarity
    self.plotData = np.zeros((p.samples_per_packet*self.plot_memory,self.num_axes)) 

    # now initiate the subplots
    for i in xrange(self.num_axes):
      self.lines.append(self.fig.axes[i].plot(self.plotData[:,i],color=scalarMap.to_rgba(colorVals[i]))[0]) # plots the line object and stores into the "lines" list
      self.fig.axes[i].set_ylim([0, 65535])
      self.fig.axes[i].set_xlim([0,p.samples_per_packet*self.plot_memory])
      fig.axes[ch].tick_params(axis='x') # white ticks
      fig.axes[ch].tick_params(axis='y') # ditto
      fig.axes[ch].set_ylabel('CH: ' + str(ch+1)) # channel number on right-hand side
      fig.axes[ch].yaxis.set_label_position('right')
      fig.axes[ch].spines['right'].set_visible(False) 
      fig.axes[ch].yaxis.set_ticks_position('left')
      fig.axes[ch].xaxis.set_ticks_position('bottom')
      fig.axes[ch].tick_params(direction='out')
      #self.axes[i].set_ylim([32000, 33000])
    
    # render the figure for viewing
    fig.canvas.draw()
    fig.show()

  @jit(cache=True,nopython=True)
  def update_data(self,p,device):
    #t = numpy.transpose(p.all_samples)
    self.plotData[:-p.samples_per_packet,:] = data[-p.samples_per_packet*(self.plot_memory-1):,:] # remove last buffer-amount of data
    self.plotData[-p.samples_per_packet:,:] = numpy.transpose(p.all_samples) # append new data 

  def start(self):
    """Start capturing data on the bound ports, and display."""

    # Make the output folder if it doesn't already exist
    if os.path.exists(self.data_dir):
      if not os.path.isdir(self.data_dir):
        sys.stderr.write(
            "ERROR: Path {} exists, but is not a directory\n".format(self.data_dir))
        return
    else:
      os.makedirs(self.data_dir)

    # Check the number of clients (devices) discovered over the JAGA network  
    for i in xrange(self.num_devices):
      sys.stderr.write("Starting capture for device {}\n".format(i))
      queues.append(Queue.Queue()) # append a new Queue instance to the "queues" list for each device
      
      # create an instance of the CaptureThread object to connect to this device 
      self.threads.append(CaptureThread( 
          self.starting_port + i,  # bind_port
	        self.length,             # length
	        i,                       # label (device number)
          self.data_dir,           # data directory
          self.file_name))         # file name
      
      # initiate data streaming for this device
      self.threads[i].run()

    # loop indefinitely and extract packet data 
    while run_flag:
      for i in xrange(self.num_devices):
        crc = True
        data = None
        p = None
        while crc:
          data = queues[i].get()  # Blocks until data is available.
          self.fh.seek(0)
          self.fh.write(data)
          self.fh.seek(0)
          p = Packet(self.fh, channels=self.channels, has_timestamp=False) # read in the packet
          crc = p.crc
      
        # check if we have received the first packet of data. 
        # if so, parse the packet and initialize our figure
        if self.first_packet:
          self.first_parsed_packet_(p, len(data)) # creates the figure
          self.first_packet = False

        # update the figure
        for ch in xrange(self.channels):
          ax = device*self.channels+k
          self.lines[ax].set_ydata(self.plotData[ax]) # update the "lines" object for each axes
          self.fig.axes[ax].draw_artist(self.fig.axes[ax].patch)
          self.fig.axes[ax].draw_artist(self.lines[ax])

      # now update the figure
      self.fig.canvas.update()
      self.fig.canvas.flush_events()

#=============================================
if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--starting_port', type=int,
                      help='First port number to listen to for data.',default=55000)
  parser.add_argument('--num_devices', type=int,
                      help='Number of devices to listen for.', default=1)
  parser.add_argument('--data_dir', type=str,
                      help='Directory to write data files to.',default='JAGA_data')
  parser.add_argument('--file_name',type=str,
                      help='Name of file to write data into.',default='jaga')
  parser.add_argument('--plot_memory',type=int,
                      help='Number of packets to display. More packets results in smoother but slower plotting',
                      default=10)
  parser.add_argument('--color_map',type=str,
                      help='Color map for drawing the data. See matplotlib documentation for details',
                      default='Set2')
  
  args = parser.parse_args() # parse the optionals
  md = JagaMultiDisplay(args.data_dir, args.file_name, args.num_devices, args.starting_port, args.plot_memory, args.color_map) # create an instance of the main runtime class
  
  try:
    md.run_flag = True
    md.start() # start the runtime
  except KeyboardInterrupt:
    print "Received interrupt, exiting."
    run_flag = False
