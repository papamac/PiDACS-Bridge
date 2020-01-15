"""
 PACKAGE:  papamac's common module library (papamaclib)
  MODULE:  messagesocket.py
   TITLE:  messagesocket core classes and methods (messagesocket)
FUNCTION:  Provides classes and methods to reliably receive and send fixed-
           length messages over TCP/IP network sockets.
   USAGE:  messagesocket is imported and used within main programs.  It is
           compatible with Python 2.7.16 and all versions of Python 3.x.
  AUTHOR:  papamac
 VERSION:  1.0.9
    DATE:  January 15, 2020


MIT LICENSE:

Copyright (c) 2018-2020 David A. Krause, aka papamac

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


DESCRIPTION:

****************************** needs work *************************************

DEPENDENCIES/LIMITATIONS:

****************************** needs work *************************************

"""
__author__ = 'papamac'
__version__ = '1.0.9'
__date__ = 'January 15, 2020'


from binascii import crc32
from datetime import datetime
from logging import DEBUG, ERROR
from math import sqrt
from socket import *
from threading import Thread, Lock

from .colortext import getLogger


# Global constants:

LOG = getLogger('Plugin')               # Color logger.
CRC_LEN = 8                             # CRC length (bytes).
SEQ_LEN = 8                             # Sequence number length (bytes).
HEX_LEN = CRC_LEN + SEQ_LEN             # Hex segment length (bytes).
DT_LEN = 26                             # Datetime length (bytes).
HDR_LEN = HEX_LEN + DT_LEN              # Total header length (bytes).
DATA_LEN = 120                          # Data segment length (bytes).
MSG_LEN = HDR_LEN + DATA_LEN            # Total fixed message length (bytes).
SOCKET_TIMEOUT = 10.0                   # Timeout limit for socket connection,
#                                         recv, and send methods (sec).
STATUS_INTERVAL = 600.0                 # Status reporting interval (sec).
#                                         Also imported by the PiDACS package
#                                         (iomgr.py)


# messagesocket module functions:

def set_logger(logger):                # Allow using modules to change the
    global LOG                         # messagesocket logger.
    LOG = logger


def set_status_interval(status_interval):  # Allow using modules to change the
    global STATUS_INTERVAL                 # STATUS_INTERVAL.
    STATUS_INTERVAL = status_interval


def next_seq(seq):
    return seq + 1 if seq < 0xffffffff else 0


class MessageSocket(Thread):

    # Private methods.

    def __init__(self, reference_name=None, disconnected=None,
                 process_message=None, recv_timeout=0.0):
        Thread.__init__(self)
        self._reference_name = reference_name
        self._disconnected = disconnected
        self._process_message = process_message
        self._recv_timeout = recv_timeout
        self._socket = None
        self._name = None
        self._status = None
        self._recvd_dt = datetime.now()
        self._send_seq = 0
        self.connected = False
        self.running = False

    def _shutdown(self, err_msg):
        """
        Shutdown the message socket after a terminal error or shutdown by the
        peer process.  When multiple recv/send threads have near-simultaneous
        errors, perform shutdown for the first one and record a debug message
        for the second.
        """
        if self.connected:
            self.connected = False
            self.running = False
            LOG.error(err_msg)
            self._socket.close()
            if self._disconnected:
                self._disconnected(self._reference_name)
        else:
            LOG.debug(err_msg)

    # Public methods.

    def connect_to_client(self, client_socket, client_address_tuple):
        self._socket = client_socket
        self._socket.settimeout(SOCKET_TIMEOUT)
        self.connected = True
        ipv4, port_number = client_address_tuple
        self.name = '[%s:%s]' % (ipv4, port_number)
        self._status = MessageStatus(self.name)
        hostname = self.recv()
        if hostname:
            self.name = hostname + self.name
            LOG.info('connected "%s"' % self.name)
            self._status = MessageStatus(self.name)
        else:
            err_msg = 'connection aborted "%s"' % self.name
            self._shutdown(err_msg)

    def connect_to_server(self, server, port_number):
        self._socket = socket(AF_INET, SOCK_STREAM)
        self._socket.settimeout(SOCKET_TIMEOUT)
        try:
            self._socket.connect((server, port_number))
        except timeout:
            LOG.error('connection timeout "%s:%s"' % (server, port_number))
            return
        except gaierror as err:
            errno, strerr = err
            LOG.error('server address error %s "%s:%s" %s'
                      % (errno, server, port_number, strerr))
            return
        except OSError as err:
            LOG.error('connection error %s "%s:%s" %s'
                      % (err.errno, server, port_number, err.strerror))
            return
        except Exception as err:  # Needed for Python 2.7.
            LOG.error('connection error "%s:%s" %s'
                      % (server, port_number, err))
            return
        self.connected = True
        ipv4, port = self._socket.getpeername()
        self.name = '%s[%s:%s]' % (server, ipv4, port)
        LOG.info('connected "%s"' % self.name)
        self._status = MessageStatus(self.name)
        self.send(gethostname())

    def run(self):
        self.running = self.connected
        while self.running:
            message = self.recv()
            if message and self._process_message:
                self._process_message(self._reference_name, message)

    def stop(self):
        self.running = False
        if self.is_alive():
            self.join()
        if self.connected:
            self._socket.shutdown(SHUT_RDWR)
            self._socket.close()

    def recv(self):
        """
        Receive a fixed-length message in multiple segments.

        recv has three possible returns:

        message:     recv returns the message without header data if a valid
                     message was received.
        null string: recv returns a null string if a timeout occurred, or a
                     message was received, but it contains fatal header errors
                     and cannot be processed.  The socket remains open.
        None:        recv returns None if no message was received and the
                     socket is closed.  This category includes long timeouts,
                     socket exceptions, and normal socket shutdown by the peer.
        """
        if not self.connected:
            return  # Return None for hard error.
        
        byte_msg = b''
        bytes_received = 0
        while bytes_received < MSG_LEN:

            # Try receiving a message segment and handle exceptions.

            try:
                segment = self._socket.recv(MSG_LEN - bytes_received)
            except timeout:
                if not self._recv_timeout:
                    return ''
                interval = (datetime.now() - self._recvd_dt).total_seconds()
                if interval < self._recv_timeout:
                    return ''
                self._socket.shutdown(SHUT_RDWR)
                err_msg = 'recv timeout "%s"' % self.name
                self._shutdown(err_msg)
                return
            except OSError as err:
                err_msg = ('recv error %s "%s" %s'
                           % (err.errno, self.name, err.strerror))
                self._shutdown(err_msg)
                return
            if not segment:  # Null segment; peer disconnected.
                err_msg = 'disconnected "%s"' % self.name
                self._shutdown(err_msg)
                return

            # Segment received; continue.

            byte_msg += segment
            bytes_received = len(byte_msg)

        # Full-length byte_msg received.

        message = byte_msg.decode().strip()
        self._recvd_dt = datetime.now()
        message = self._status.recv(message, self._recvd_dt)
        return message  # Return the message without the header or a null
#                         string as determined by _status.recv.

    def send(self, message):
        if not self.connected:
            return

        # Remove blanks and truncate if necessary.

        message = message.strip()
        if len(message) > DATA_LEN:
            LOG.warning('message truncated "%s"' % message)
            message = message[:DATA_LEN]

        # Add the crc, sequence number, and datetime to create a fixed-length
        # byte message.

        now_dt = datetime.now()
        iso_dt = now_dt.isoformat('|')
        if not now_dt.microsecond:
            iso_dt += '.000000'
        message = '%08x%s%s' % (self._send_seq, iso_dt, message)
        crc = crc32(message.encode()) & 0xffffffff  # Works with 2.7, 3.x
        message = '%08x%s' % (crc, message)
        byte_msg = message.ljust(MSG_LEN).encode()

        # Send the byte_msg in multiple segments.

        bytes_sent = 0
        while bytes_sent < MSG_LEN:

            # Try sending a segment and handle exceptions.

            try:
                segment_bytes_sent = self._socket.send(byte_msg[bytes_sent:])
            except timeout:
                self._status.send_timeout()
                return
            except OSError as err:
                err_msg = ('send error %s "%s" %s'
                           % (err.errno, self.name, err.strerror))
                self._shutdown(err_msg)
                return
            if not segment_bytes_sent:  # Error; segment not sent.
                self._status.send_error()
                return

            # Segment sent; continue.
            
            bytes_sent += segment_bytes_sent

        # Full-length byte_msg sent.

        self._status.send()
        self._send_seq = next_seq(self._send_seq)


class MessageStatus:

    # Private methods:

    def __init__(self, name):
        self._name = name
        self._lock = Lock()
        self._min = None
        self._max = None
        self._recv_seq = None
        self._init()

    def _init(self):
        self._shorts = self._crc_errs = self._dt_errs = self._seq_errs = 0
        self._send_errs = self._send_timeouts = 0
        self._recvd = self._sent = 0
        self._min = 1000000.0
        self._max = self._sum = self._sum2 = 0.0
        self._status_dt = datetime.now()

    def _report(self):
        """
        Report accumulated status data if the status interval has expired.
        """
        with self._lock:
            interval = (datetime.now() - self._status_dt).total_seconds()
            if interval >= STATUS_INTERVAL:
                min_ = 0 if self._min == 1000000.0 else self._min
                avg = self._sum / self._recvd if self._recvd else 0.0
                std = (sqrt(self._sum2 / self._recvd - avg * avg)
                       if self._recvd else 0.0)
                recv_rate = self._recvd / interval
                recv_status = ('recv[%i %i %i %i|%i %i %i %i|%i %i]'
                               % (self._shorts, self._crc_errs, self._dt_errs,
                                  self._seq_errs, min_, self._max, avg, std,
                                  self._recvd, recv_rate))
                send_rate = self._sent / interval
                send_status = ('send[%i %i|%i %i]'
                               % (self._send_errs, self._send_timeouts,
                                  self._sent, send_rate))
                errs = (self._shorts + self._crc_errs + self._dt_errs +
                        self._seq_errs + self._send_errs + self._send_timeouts
                        or self._max > 1000.0 * SOCKET_TIMEOUT)
                level = ERROR if errs else DEBUG
                LOG.log(level, 'status "%s" %s %s'
                               % (self._name, recv_status, send_status))
                self._init()  # Initialize status data for the next interval.

    # Public methods.

    def recv(self, message, recvd_dt):
        """
        Check the message header for short messages, crc errors, datetime
        errors, and sequence errors.  Update error and status data and call the
        _report method for status reporting.  Return the message without the
        header if no errors are found, or a null message otherwise (soft
        error).
        """
        if len(message) < HDR_LEN:  # Check for short message.
            self._shorts += 1
            self._report()
            return ''
        crc_msg = int(message[:CRC_LEN], 16)  # Check for CRC error.
        crc_calc = crc32(message.encode()[CRC_LEN:]) & 0xffffffff  # 2.7 & 3.x
        if crc_msg != crc_calc:
            self._crc_errs += 1
            self._report()
            return ''
        try:  # Check for datetime error.
            msg_dt = datetime.strptime(message[HEX_LEN:HDR_LEN],
                                       '%Y-%m-%d|%H:%M:%S.%f')
        except ValueError:
            self._dt_errs += 1
            self._report()
            return ''
        msg_seq = int(message[CRC_LEN:HEX_LEN], 16)  # Check for sequence error
        if self._recv_seq is not None:
            if msg_seq != self._recv_seq:
                self._seq_errs += 1
        self._recv_seq = msg_seq

        # Update message count, sequence number, datetime, and latency data.

        self._recvd += 1
        self._recv_seq = next_seq(self._recv_seq)
        latency = 1000.0 * (recvd_dt - msg_dt).total_seconds()
        self._min = min(latency, self._min)
        self._max = max(latency, self._max)
        self._sum += latency
        self._sum2 += latency * latency
        self._report()
        return message[HDR_LEN:]  # Good message; return it without header.

    def send(self):
        self._sent += 1
        self._report()

    def send_error(self):
        self._send_errs += 1
        self._report()

    def send_timeout(self):
        self._send_timeouts += 1
        self._report()


class MessageServer:
    """
    """
    # Private methods:

    def __init__(self, port_number, get_message=None, process_request=None):
        self._socket = socket(AF_INET, SOCK_STREAM)
        self._socket.settimeout(SOCKET_TIMEOUT)
        self._socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self._socket.bind(('', port_number))
        self._get_message = get_message
        self._process_request = process_request
        self._accept = Thread(name='accept_client_connections',
                              target=self._accept_client_connections)
        self._serve = Thread(name='serve_clients',
                             target=self._serve_clients)
        self._clients = []
        self.running = False

    def start(self):
        self.running = True
        self._accept.start()
        self._serve.start()

    def stop(self):
        self._accept.join()
        self._serve.join()
        for client in self._clients:
            client.stop()

    def _accept_client_connections(self):
        self._socket.listen(5)
        ipv4, port = self._socket.getsockname()
        name = '%s[%s:%s]' % (gethostname(), ipv4, port)
        LOG.warning('accepting client connections "%s"' % name)
        while self.running:
            try:
                client_socket, client_address_tuple = self._socket.accept()
            except timeout:
                continue
            client = MessageSocket(name, process_message=self._process_request)
            client.connect_to_client(client_socket, client_address_tuple)
            client.start()
            self._clients.append(client)

    def _serve_clients(self):
        while self.running:
            message = self._get_message() if self._get_message else 'test msg'
            if message:
                for client in self._clients:
                    if client.running:
                        client.send(message)
