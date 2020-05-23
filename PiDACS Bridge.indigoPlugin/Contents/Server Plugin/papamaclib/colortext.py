"""
 PACKAGE:  papamac's common module library (papamaclib)
  MODULE:  colortext.py
   TITLE:  add color to text messages (colortext)
FUNCTION:  colortext provides globally-defined ASCII escape sequences and a
           simple function (ct) to add color text capabilities to other
           modules.  It also provides a ColortextLogger class and getLogger
           function to enable color logging using the standard Python logging
           classes and methods.
   USAGE:  Import colortext globals, class and functions as needed in other
           modules.  It is compatible with Python 2.7.16 and all versions of
           Python 3.x.
  AUTHOR:  papamac
 VERSION:  1.0.9
    DATE:  May 22, 2020


MIT LICENSE:

Copyright (c) 2019-2020 David A. Krause, aka papamac

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
__date__ = 'May 22, 2020'

import logging
from logging import DEBUG, INFO, WARNING, ERROR, CRITICAL

# Global constants used in colortext, but also imported in
# papamaclib/argsandlogs.py, PiDACS/iomgr.py, and PiDACS-Bridge/plugin.py.

THREADDEBUG = 5                         # New THREADDEBUG logging level.
DATA = 15                               # New DATA logging level.

# ASCII escape sequences for text attributes and colors:

esc = {'normal':     '\033[0m',  'bright': '\033[1m',  'dim':     '\033[2m',
       'underscore': '\033[4m',  'blink':  '\033[5m',  'reverse': '\033[7m',
       'black':      '\033[30m', 'red':    '\033[31m', 'green':   '\033[32m',
       'yellow':     '\033[33m', 'blue':   '\033[34m', 'magenta': '\033[35m',
       'cyan':       '\033[36m', 'white':  '\033[37m'}

colors = {THREADDEBUG: 'magenta', DEBUG: 'green', INFO: '', DATA: '',
          WARNING: 'yellow', ERROR: 'red', CRITICAL: 'red'}


# colortext module functions:

def ct(color, text, attribute='bright'):
    color_esc = esc.get(color, '')
    if color_esc:
        return color_esc + esc.get(attribute, '') + text + esc['normal']
    else:
        return text


def getLogger(name):
    return ColortextLogger(logging.getLogger(name))


class ColortextLogger(logging.LoggerAdapter):
    """
    **************************** needs work ***********************************
    """

    def __init__(self, logger, extra=None):
        if extra is None:
            extra = {'extra': ''}
        logging.LoggerAdapter.__init__(self, logger, extra)

    # New methods for ColortextLogger:

    def threaddebug(self, message, *args, **kwargs):
        self.log(THREADDEBUG, message, *args, **kwargs)

    def data(self, message, *args, **kwargs):
        self.log(DATA, message, *args, **kwargs)

    def blue(self, message, *args, **kwargs):
        self.log(INFO, ct('blue', message), *args, **kwargs)

    def green(self, message, *args, **kwargs):
        self.log(INFO, ct('green', message), *args, **kwargs)

    # log method overrides logging.LoggerAdapter.log:

    def log(self, level, message, *args, **kwargs):
        logging.LoggerAdapter.log(self, level, ct(colors[level], message),
                                  *args, **kwargs)
