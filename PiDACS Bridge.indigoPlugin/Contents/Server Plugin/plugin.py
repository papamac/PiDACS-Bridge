# coding=utf-8
"""
 PACKAGE:  indigo plugin interface to PiDACS (PiDACS-Bridge)
  MODULE:  plugin.py
   TITLE:  primary Python module in the PiDACS indigo plugin bundle (plugin)
FUNCTION:  plugin is a PiDACS client that can connect to multiple PiDACS
           servers (instances of pidacs) and interface with indigo GUIs and
           device objects.
   USAGE:  plugin.py is included in a standard indigo plugin bundle.
  AUTHOR:  papamac
 VERSION:  1.1.2
    DATE:  May 5, 2020


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

plugin imports the modules colortext and messagesocket from papamaclib.
Because the indigo plugin bundle is a standalone container, the primary
papamaclib cannot be externally referenced.  A copy of papamaclib with the
modules colortext and messagesocket (and __init__.py) must be included in the
bundle.

"""
__author__ = u'papamac'
__version__ = u'1.1.2'
__date__ = u'May 5, 2020'

import indigo
from logging import addLevelName, getLogger, NOTSET
from random import choice
from socket import gaierror, gethostbyname
from time import sleep

from papamaclib.colortext import THREAD_DEBUG, DATA
from papamaclib.messagesocket import set_logger, MessageSocket, STATUS_INTERVAL


# Globals:

PLUGIN = None                             # Plugin instance object.
LOG = getLogger(u'Plugin')                # Standard logger (no color).
set_logger(LOG)                           # Override color logger in
#                                           messagesocket.

VALID_PORTS = range(50000, 60000, 1000)   # Enumeration of valid PiDACS ports.
SERVER_TIMEOUT = STATUS_INTERVAL + 10.0   # Timeout must be longer than the
#                                           status reporting interval to avoid
#                                           timeouts from an idle server.
PORT_TYPES = (u'ab', u'ga', u'gb', u'gp')


class PluginServer(MessageSocket):
    """
    """
    # Private method:

    def __init__(self, dev, *args, **kwargs):
        MessageSocket.__init__(self, dev.name, *args, **kwargs)
        self._dev = dev
        self._server = dev.pluginProps[u'serverAddress']
        self._portNumber = int(dev.pluginProps[u'portNumber'])

    # Public methods:

    def run(self):
        LOG.log(THREAD_DEBUG, u'run called "%s"' % self._dev.name)
        self.running = True

        # Connect to PiDACS server.

        sleep(3)
        connectionErrors = 0
        while self.running:
            self.connect_to_server(self._server, self._portNumber)
            if self.connected:
                break

            # Not connected; sleep for a while and try again.

            connectionErrors += 1
            if connectionErrors <= 5:
                sleepTime = 10
                messageTime = u'10 seconds'
            elif connectionErrors <= 10:
                sleepTime = 60
                messageTime = u'1 minute'
            else:
                sleepTime = 600
                messageTime = u'10 minutes'
            LOG.error(u'will try connecting again in %s', messageTime)
            for i in range(sleepTime):
                if not self.running:
                    return
                sleep(1)
        else:
            return

        # Connected; update indigo server states.

        self._dev.setErrorStateOnServer(None)
        self._dev.updateStateOnServer(key=u'status', value=u'Running')
        self._dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
        LOG.info(u'started "%s" using socket "%s"'
                 % (self._dev.name, self.name))

        # Start all PiDACS devices connected to server.

        for dev in indigo.devices.iter(u'self'):
            if dev.pluginProps.get(u'serverName') == self._dev.name:
                dev.setErrorStateOnServer(None)
                if dev.enabled:
                    Plugin.startDevice(dev)

        # Start message processing run loop.

        LOG.log(THREAD_DEBUG, u'starting run loop "%s"' % self._dev.name)
        while self.running:
            message = self.recv()
            if message and self._process_message:
                self._process_message(self._reference_name, message)
        LOG.log(THREAD_DEBUG, u'run loop ended "%s"' % self._dev.name)

    def sendRequest(self, *args):
        LOG.log(THREAD_DEBUG, u'sendRequest called "%s"' % self._dev.name)
        self.send(u' '.join((str(arg) for arg in args)))


class Plugin(indigo.PluginBase):

    # Class attribute:

    _servers = {}

    # Private methods:

    def __init__(self, pluginId, pluginDisplayName,
                 pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName,
                                     pluginVersion, pluginPrefs)

        global PLUGIN
        PLUGIN = self

        addLevelName(THREAD_DEBUG, 'THREAD_DEBUG')
        addLevelName(DATA, 'DATA')
        self.indigo_log_handler.setLevel(NOTSET)
        LOG.setLevel(pluginPrefs[u'loggingLevel'])
        LOG.debug(pluginPrefs)

    def __del__(self):
        indigo.PluginBase.__del__(self)

    # Public class methods that are accessible from instances of both the
    # PluginServer class and this Plugin class:

    @classmethod
    def startServer(cls, dev):
        LOG.log(THREAD_DEBUG, u'startServer called "%s"' % dev.name)
        server = PluginServer(dev, disconnected=cls.disconnected,
                              process_message=cls.processMessage,
                              recv_timeout=SERVER_TIMEOUT)
        cls._servers[dev.name] = server
        server.start()

    @classmethod
    def startDevice(cls, dev):
        LOG.log(THREAD_DEBUG, u'startDevice called "%s"' % dev.name)
        serverName = dev.pluginProps[u'serverName']
        server = cls._servers.get(serverName)
        if server and server.connected and server.running:
            channelName = dev.pluginProps[u'channelName']
            server.sendRequest(channelName, u'alias', dev.name)
            if dev.deviceTypeId == u'analogInput':
                gain = dev.pluginProps[u'gain']
                server.sendRequest(dev.name, u'gain', gain)
                resolution = dev.pluginProps[u'resolution']
                server.sendRequest(dev.name, u'resolution', resolution)
                scaling = dev.pluginProps[u'scaling']
                if scaling != u'Default':
                    server.sendRequest(dev.name, u'scaling', scaling)
            elif dev.deviceTypeId == u'digitalInput':
                direction = u'1'
                server.sendRequest(dev.name, u'direction', direction)
                polarity = dev.pluginProps[u'polarity']
                server.sendRequest(dev.name, u'polarity', polarity)
                pullup = dev.pluginProps[u'pullup']
                server.sendRequest(dev.name, u'pullup', pullup)
            else:  # deviceTypeId == u'digitalOutput'
                direction = u'0'
                server.sendRequest(dev.name, u'direction', direction)
                if PLUGIN.pluginPrefs[u'restartClear']:
                    server.sendRequest(dev.name, u'write', u'0')
            change = dev.pluginProps[u'change']
            if isinstance(change, bool):
                change = u'true' if change else u'false'
            server.sendRequest(dev.name, u'change', change)
            if dev.pluginProps[u'periodic']:
                interval = dev.pluginProps[u'interval']
                server.sendRequest(dev.name, u'interval', interval)
            server.sendRequest(dev.name, u'read')
            LOG.info(u'started "%s"' % dev.name)

    @classmethod
    def disconnected(cls, serverName):
        LOG.log(THREAD_DEBUG, u'disconnected called "%s"' % serverName)
        dev = indigo.devices[serverName]
        dev.setErrorStateOnServer(u'Disconnected')
        for dev_ in indigo.devices.iter(u'self'):
            if dev_.pluginProps.get(u'serverName') == dev.name:
                dev_.setErrorStateOnServer(u'Server')
        LOG.info(u'stopped "%s"' % serverName)
        cls.startServer(dev)

    @classmethod
    def processMessage(cls, serverName, message):
        LOG.log(THREAD_DEBUG, u'processMessage called')
        messageSplit = message.split()
        level = int(messageSplit[0])
        LOG.log(level, u'received "%s" %s' % (serverName, message[3:]))
        if level == DATA:
            channelId = messageSplit[1]
            devName = channelId.split(u'[')[0]
            dev = indigo.devices.get(devName)
            if dev:
                value = messageSplit[2]
                if value == u'!ERROR':
                    dev.setErrorStateOnServer(u'Error')
                    return
                if not dev.enabled:
                    return
                if dev.deviceTypeId == u'analogInput':
                    try:
                        sensorValue = float(value)
                    except ValueError:
                        LOG.error(u'invalid analog value "%s" for '
                                  u'channel "%s"' % (value, channelId))
                        return
                    units = dev.pluginProps[u'units']
                    if units[0] in (u'm', u'µ', u'°'):
                        fmt = u'%i %s'
                    else:
                        fmt = u'%4.2f %s'
                    uiValue = fmt % (sensorValue, units)
                    dev.updateStateOnServer(u'sensorValue', sensorValue,
                                            uiValue=uiValue)
                    LOG.info(u'received "%s" update to "%s"'
                             % (dev.name, uiValue))
                else:
                    if value not in (u'0', u'1'):
                        LOG.error(u'invalid bit value "%s" for '
                                  u'channel "%s"' % (value, channelId))
                        return
                    state = u'on' if value == u'1' else u'off'
                    dev.updateStateOnServer(u'onOffState', state)
                    dev.updateStateImageOnServer(
                        indigo.kStateImageSel.Auto)
                    LOG.info(u'received "%s" update to "%s"'
                             % (dev.name, state))
            else:
                if PLUGIN.pluginPrefs[u'logStateChanges']:
                    LOG.warning(u'received "%s" state change on '
                                u'unassigned device %s'
                                % (serverName, devName))

    # Indigo plugin.py standard public instance methods:

    def startup(self):
        LOG.log(THREAD_DEBUG, u'startup called')

    def shutdown(self):
        LOG.log(THREAD_DEBUG, u'shutdown called')

    def validatePrefsConfigUi(self, valuesDict):
        LOG.log(THREAD_DEBUG, u'validatePrefsConfigUi called')
        LOG.setLevel(valuesDict[u'loggingLevel'])
        return True, valuesDict

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        dev = indigo.devices[devId]
        LOG.log(THREAD_DEBUG, u'validateDeviceConfigUi called "%s"; configured'
                              u' = %s' % (dev.name, dev.configured))
        values = valuesDict
        errors = indigo.Dict()

        if typeId == u'server':
            serverAddress = valuesDict[u'serverAddress']
            if serverAddress:
                ipv4 = u''
                try:
                    ipv4 = gethostbyname(serverAddress)
                except gaierror as err:
                    errno, strerr = err
                    errors[u'serverAddress'] = (u'Server address error %s %s'
                                                % (errno, strerr))
                else:
                    portNumber = valuesDict[u'portNumber']
                    if portNumber.isdecimal():
                        portNumber = int(portNumber)
                        if portNumber in VALID_PORTS:
                            values[u'socketId'] = u'%s:%s' % (ipv4, portNumber)
                        else:
                            errors[u'portNumber'] = (u'Port number not a '
                                                     u'valid PiDACS port.')
                    else:
                        errors[u'portNumber'] = (u'Port number must be an '
                                                 u'integer.')
            else:
                errors[u'serverAddress'] = u'Enter valid server address.'

            serverId = valuesDict[u'serverId']
            if not serverId:
                split1 = serverAddress.split(u'.', 1)
                split2 = split1[0].split(u'-')
                if len(split2) > 1:
                    serverId = split2[1]
                else:
                    serverId = chr(choice(range(97, 123)))
            for dev_ in indigo.devices.iter(u'self.server'):
                if (dev_.id != devId
                        and dev_.pluginProps[u'serverId'] == serverId):
                    errors[u'serverId'] = (u'Server id already in use; '
                                           u'choose again')
                    break
            values[u'serverId'] = serverId
            values[u'address'] = serverId

        else:
            serverName = valuesDict.get(u'serverName')
            if serverName:
                dev_ = indigo.devices[serverName]
                serverId = dev_.pluginProps[u'serverId']
                channelName = valuesDict[u'channelName']
                if (len(channelName) == 4
                        and channelName[:2] in PORT_TYPES
                        and channelName[2:].isdecimal()):
                    for dev_ in indigo.devices.iter(u'self'):
                        if (dev_.id != devId
                                and dev_.pluginProps.get(u'serverName') == serverName
                                and dev_.pluginProps.get(u'channelName') == channelName):
                            errors[u'channelName'] = (u'Channel name already '
                                                      u'in use; choose again.')
                            break
                    values[u'address'] = u'%s.%s' % (serverId, channelName)
                else:
                    errors[u'channelName'] = u'Invalid channel name.'
            else:
                errors[u'serverName'] = u'Select server name.'
            if typeId == u'digitalOutput':
                delay = valuesDict[u'turnOffDelay']
                delayIsNumber = delay.replace(u'.', '', 1).isdecimal()
                if not delayIsNumber:
                    errors[u'turnOffDelay'] = (u'Turn-off delay is not a '
                                               u'number.')

        if errors:
            return False, valuesDict, errors
        else:
            return True, values

    def getServers(self, filter="", valuesDict=None, typeId="", targetId=0):
        LOG.log(THREAD_DEBUG, u'getServers called')
        servers = []
        for dev in indigo.devices.iter(u'self.server'):
            servers.append(dev.name)
        return sorted(servers)

    def didDeviceCommPropertyChange(self, dev, newDev):
        LOG.log(THREAD_DEBUG, u'didDeviceCommPropertyChange called; old = '
                              u'"%s", new = "%s"' % (dev.name, newDev.name))
        change = (dev.name != newDev.name
                  or dev.deviceTypeId != newDev.deviceTypeId
                  or dev.pluginProps != newDev.pluginProps)
        LOG.log(THREAD_DEBUG, u'change = %s' % change)
        return change

    def deviceStartComm(self, dev):
        LOG.log(THREAD_DEBUG, u'deviceStartComm called "%s"' % dev.name)
        if dev.subModel != u'PiDACS':
            dev.subModel = u'PiDACS'
            dev.replaceOnServer()
        if u' ' in dev.name:
            warning = (u'startup for device "%s" deferred until final device '
                       u'name (no spaces) is specified' % dev.name)
            LOG.warning(warning)
        else:
            if dev.deviceTypeId == u'server':
                self.startServer(dev)
            else:
                self.startDevice(dev)

    def deviceStopComm(self, dev):
        LOG.log(THREAD_DEBUG, u'deviceStopComm called "%s"' % dev.name)
        if dev.deviceTypeId == u'server':
            server = self._servers.get(dev.name)
            if server and server.connected and server.running:
                for dev_ in indigo.devices.iter(u'self'):
                    if dev_.pluginProps.get(u'serverName') == dev.name:
                        server.sendRequest(dev_.name, u'reset')
                        dev_.setErrorStateOnServer(u'Server')
                server.stop()
                del self._servers[dev.name]
                dev.updateStateOnServer(key=u'status', value=u'Stopped')
                dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
        else:
            serverName = dev.pluginProps[u'serverName']
            server = self._servers.get(serverName)
            if server and server.connected and server.running:
                server.sendRequest(dev.name, u'reset')
        LOG.info(u'stopped "%s"' % dev.name)

    def actionControlDevice(self, action, dev):
        LOG.log(THREAD_DEBUG, u'actionControlDevice called "%s"' % dev.name)
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            value = 1
            action = u'"on"'
        elif action.deviceAction == indigo.kDeviceAction.TurnOff:
            value = 0
            action = u'"off"'
        elif action.deviceAction == indigo.kDeviceAction.Toggle:
            value = 0 if dev.onState else 1
            action = u'"toggle"'
        else:
            return

        serverName = dev.pluginProps[u'serverName']
        server = self._servers.get(serverName)
        if server and server.connected and server.running:
            requestId = u'write'
            if value and dev.pluginProps[u'momentary']:
                value = dev.pluginProps[u'turnOffDelay']
                requestId = u'momentary'
            server.sendRequest(dev.name, requestId, value)
            LOG.info(u'sent "%s" %s' % (dev.name, action))
        else:
            LOG.error(u'server "%s" not running; "%s" %s request ignored'
                      % (serverName, dev.name, action))

    def actionControlUniversal(self, action, dev):
        LOG.log(THREAD_DEBUG, u'actionControlUniversal called "%s"' % dev.name)
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            serverName = dev.pluginProps[u'serverName']
            server = self._servers.get(serverName)
            if server and server.connected and server.running:
                server.sendRequest(dev.name, u'read')
                LOG.info(u'sent "%s" status request' % dev.name)
            else:
                LOG.error(u'server "%s" not running; "%s" status request '
                          u'ignored' % (serverName, dev.name))
