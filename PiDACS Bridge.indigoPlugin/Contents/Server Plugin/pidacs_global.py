"""
MIT LICENSE

Copyright (c) 2018-2019 David A. Krause, aka papamac

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

DESCRIPTION

"""
__author__ = 'papamac'
__version__ = '0.9.0'
__date__ = 'April 12, 2018'

from datetime import datetime
from socket import *


# PiDACS message length constants:

MESSAGE_LENGTH = 110          # Fixed message length for data queue and sockets
#                              (bytes).
DATETIME_LENGTH = len(str(datetime.now()))  # Length of datetime message
#                                             segment (bytes).
TEXT_LENGTH = MESSAGE_LENGTH - DATETIME_LENGTH - 3  # Length of text message
#                                                     segment (bytes).

# PiDACS socket/server constants:

SOCKET_TIMEOUT = 0.75         # Timeout limit for socket connection, recv, and
#                               send methods (sec).
LATENCY = 1.0                 # Limit on network latency for all server to
#                               client messages (sec).  Exceeding the latency
#                               limit is reported for user awareness, but does
#                               nor otherwise effect rpio processing.
SERVER_TIMEOUT = 610.0        # Timeout limit for server keep-alive or other
#                               data messages (sec).  Must be comfortably
#                               longer than the IOMGR STATUS_INTERVAL (600 sec)
#                               to allow time for network delays.
DEFAULT_ADDRESS = 'localhost' # local pidacs server.
DYNAMIC_PORT_RANGE = range(49152, 65535)  # Range of valid dynamic ports.
DEFAULT_PORT_NUMBER = 50000   # Arbitrary selection from DYNAMIC_PORT_RANGE.


# PiDACS exceptions:

class BrokenPipe(Exception):
    pass


class ServerTimeout(Exception):
    pass


# Socket I/O functions for PiDACS fixed length messages.

def recv_msg(thread, sock, dt_recvd=None):
    msg = b''
    bytes_recvd = 0
    while thread.running and bytes_recvd < MESSAGE_LENGTH:
        try:
            segment = sock.recv(MESSAGE_LENGTH - bytes_recvd)
        except timeout:
            if dt_recvd:
                secs_since_last_msg = (datetime.now()
                                       - dt_recvd).total_seconds()
                if secs_since_last_msg > SERVER_TIMEOUT:
                    raise ServerTimeout
            continue
        if not segment:
            raise BrokenPipe
        msg += segment
        bytes_recvd = len(msg)
    return msg.decode().strip()


def send_msg(sock, msg):
    msg = msg.ljust(MESSAGE_LENGTH).encode()[:MESSAGE_LENGTH]
    bytes_sent = 0
    while bytes_sent < MESSAGE_LENGTH:
        bytes_sent_this_segment = sock.send(msg[bytes_sent:])
        if not bytes_sent_this_segment:
            raise BrokenPipe
        bytes_sent += bytes_sent_this_segment
