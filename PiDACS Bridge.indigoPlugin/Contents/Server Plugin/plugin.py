# coding=utf-8
"""
 PACKAGE:  indigo plugin interface to PiDACS (PiDACS-Bridge)
  MODULE:  plugin.py
   TITLE:  primary Python module in the PiDACS indigo plugin bundle
FUNCTION:  plugin is a PiDACS client that can connect to multiple PiDACS
           servers (instances of pidacs) and interface with indigo GUIs and
           device objects.
   USAGE:  plugin.py is included in a standard indigo plugin bundle.
  AUTHOR:  papamac
 VERSION:  1.6.3
    DATE:  August 1, 2021


MIT LICENSE:

Copyright (c) 2018-2021 David A. Krause, aka papamac

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

CHANGE LOG:

1.6.2   12/27/2020  Change display state names and formats to be consistent
                    with indigo conventions.
1.6.3     8/1/2021  Correct errors in generating server requests for universal
                    actions (turnOn, turnOff, toggle).
"""

__author__ = u'papamac'
__version__ = u'1.6.3'
__date__ = u'August 1, 2021'

from logging import addLevelName, getLogger, NOTSET
from random import choice
from socket import gaierror, gethostbyname
from time import sleep

import indigo
from papamaclib.colortext import DATA
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
CONFIG_REQUESTS = (u'change',    u'dutycycle',  u'frequency',  u'gain',
                   u'interval',  u'polarity',   u'pullup',     u'resolution',
                   u'scaling',   u'units')


class PluginServer(MessageSocket):
    """
    **************************** needs work ***********************************
    """

    # Private method:

    def __init__(self, dev, *args, **kwargs):
        LOG.threaddebug(u'PluginServer.__init__ called "%s"', dev.name)
        MessageSocket.__init__(self, dev.name, *args, **kwargs)
        self._dev = dev
        self._server = dev.pluginProps[u'serverAddress']
        self._portNumber = int(dev.pluginProps[u'portNumber'])

    # Public methods:

    def run(self):
        LOG.threaddebug(u'PluginServer.run called "%s"', self._dev.name)
        self.running = True

        # Connect to PiDACS server.

        sleep(2)
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
            LOG.error(u'PluginServer.run: will try connecting again in %s',
                      messageTime)
            for i in range(sleepTime):
                if not self.running:
                    return
                sleep(1)
        else:
            return

        # Connected; update indigo server states.

        self._dev.setErrorStateOnServer(None)
        self._dev.updateStateOnServer(key=u'status', value=u'running')
        self._dev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
        LOG.debug(u'started "%s" using socket "%s"', self._dev.name, self.name)

        # Start all PiDACS devices connected to server.

        for dev in indigo.devices.iter(u'self'):
            if (dev.pluginProps.get(u'serverName') == self._dev.name
                    and dev.enabled
                    and u' ' not in dev.name):
                Plugin.startDevice(dev)

        # Start message processing run loop.

        LOG.threaddebug(u'PluginServer.run: starting run loop "%s"',
                        self._dev.name)
        while self.running:
            message = self.recv()
            if message and self._process_message:
                self._process_message(self._reference_name, message)
        LOG.threaddebug(u'PluginServer.run: run loop ended "%s"',
                        self._dev.name)

    def sendRequest(self, *args):
        LOG.threaddebug(u'PluginServer.sendRequest called "%s"',
                        self._dev.name)
        request = u' '.join((str(arg) for arg in args))
        self.send(request)
        LOG.debug(u'PluginServer.sendRequest: sent [%s]', request)


class Plugin(indigo.PluginBase):
    """
    **************************** needs work ***********************************
    """

    # Class attribute:

    _servers = {}

    # Private methods:

    def __init__(self, pluginId, pluginDisplayName,
                 pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName,
                                     pluginVersion, pluginPrefs)
        global PLUGIN
        PLUGIN = self

    def __del__(self):
        LOG.threaddebug(u'Plugin.__del__ called')
        indigo.PluginBase.__del__(self)

    # Public class methods that are accessible from instances of both the
    # PluginServer class and this Plugin class:

    @classmethod
    def startServer(cls, dev):
        LOG.threaddebug(u'Plugin.startServer called "%s"', dev.name)
        server = PluginServer(dev, disconnected=cls.disconnected,
                              process_message=cls.processMessage,
                              recv_timeout=SERVER_TIMEOUT)
        cls._servers[dev.name] = server
        server.start()

    @classmethod
    def startDevice(cls, dev):
        LOG.threaddebug(u'Plugin.startDevice called "%s"', dev.name)
        serverName = dev.pluginProps[u'serverName']
        server = cls._servers.get(serverName)
        if server and server.connected and server.running:
            channelName = dev.pluginProps[u'channelName']
            server.sendRequest(channelName, u'alias', dev.name)
            if dev.deviceTypeId == u'digitalInput':
                server.sendRequest(channelName, u'direction', u'input')
            elif dev.deviceTypeId in (u'digitalOutput', u'pwmOutput'):
                server.sendRequest(channelName, u'direction', u'output')
            for prop in dev.pluginProps:
                if prop in CONFIG_REQUESTS:
                    value = dev.pluginProps[prop]
                    server.sendRequest(channelName, prop, value)
            if (dev.deviceTypeId == u'digitalOutput'
                    and PLUGIN.pluginPrefs[u'restartClear']):
                server.sendRequest(channelName, u'write')
            else:
                server.sendRequest(channelName, u'read')
            dev.setErrorStateOnServer(None)
            LOG.debug(u'started "%s"', dev.name)
        else:
            LOG.debug(u'not started "%s" no server', dev.name)

    @classmethod
    def disconnected(cls, serverName):
        LOG.threaddebug(u'Plugin.disconnected called "%s"', serverName)
        dev = indigo.devices[serverName]
        dev.setErrorStateOnServer(u'disconnected')
        for dev_ in indigo.devices.iter(u'self'):
            if dev_.pluginProps.get(u'serverName') == dev.name:
                dev_.setErrorStateOnServer(u'server')
        LOG.debug(u'stopped "%s"', serverName)
        cls.startServer(dev)

    @classmethod
    def processMessage(cls, serverName, message):
        LOG.threaddebug(u'Plugin.processMessage called')
        messageSplit = message.split()
        level = int(messageSplit[0])
        LOG.log(level, u'received "%s" %s', serverName, message[3:])
        if level == DATA:
            channelId = messageSplit[1]
            devName = channelId.split(u'[')[0]
            dev = indigo.devices.get(devName)
            if dev:
                value = messageSplit[2]
                if value == u'!ERROR':
                    dev.setErrorStateOnServer(u'error')
                    return
                if not dev.enabled:
                    return
                if dev.deviceTypeId == u'analogInput':
                    try:
                        sensorValue = float(value)
                    except ValueError:
                        LOG.error(u'Plugin.processMessage: invalid analog '
                                  u'value %s for channel %s', value, channelId)
                        return
                    units = u''
                    fmt = u'%.2f %s'
                    if len(messageSplit) > 3:
                        units = messageSplit[3]
                        if units[0] in (u'm', u'µ', u'°'):
                            fmt = u'%i %s'
                    uiValue = fmt % (sensorValue, units)
                    dev.updateStateOnServer(u'sensorValue', sensorValue,
                                            uiValue=uiValue)
                    dev.updateStateImageOnServer(indigo.
                                                 kStateImageSel.EnergyMeterOff)
                    LOG.info(u'received "%s" update to %s', dev.name, uiValue)
                else:
                    if value not in (u'0', u'1'):
                        LOG.error(u'Plugin.processMessage: invalid bit value '
                                  u'%s for channel %s', value, channelId)
                        return
                    state = u'on' if value == u'1' else u'off'
                    dev.updateStateOnServer(u'onOffState', state)
                    LOG.info(u'received "%s" update to %s', dev.name, state)
            else:
                if PLUGIN.pluginPrefs[u'logUnexpectedData']:
                    LOG.warning(u'received "%s" unexpected DATA message %s ',
                                serverName, message[3:])

    # Indigo plugin.py standard public instance methods:

    def startup(self):
        addLevelName(DATA, u'DATA')
        self.indigo_log_handler.setLevel(NOTSET)
        level = self.pluginPrefs[u'loggingLevel']
        LOG.setLevel(u'THREADDEBUG' if level == u'THREAD' else level)
        LOG.threaddebug(u'Plugin.startup called')
        LOG.debug(self.pluginPrefs)

    def shutdown(self):
        LOG.threaddebug(u'Plugin.shutdown called')

    def validatePrefsConfigUi(self, valuesDict):
        LOG.threaddebug(u'Plugin.validatePrefsConfigUi called')
        level = valuesDict[u'loggingLevel']
        LOG.setLevel(u'THREADDEBUG' if level == u'THREAD' else level)
        return True, valuesDict

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        dev = indigo.devices[devId]
        LOG.threaddebug(u'Plugin.validateDeviceConfigUi called "%s"; '
                        u'configured = %s', dev.name, dev.configured)
        values = valuesDict
        errors = indigo.Dict()

        if typeId == u'server':
            serverAddress = valuesDict[u'serverAddress']
            if serverAddress:
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
                                and (dev_.pluginProps.get(u'serverName')
                                     == serverName)
                                and (dev_.pluginProps.get(u'channelName')
                                     == channelName)):
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
                try:
                    delay = float(delay)
                except ValueError:
                    errors[u'turnOffDelay'] = (u'Turn-off delay is not a '
                                               u'number.')
                else:
                    if not 0 <= delay <= 10:
                        errors[u'turnOffDelay'] = (u'Turn-off delay must be '
                                                   u'>= 0 and <= 10 sec')

            elif typeId == u'pwmOutput':
                frequency = valuesDict[u'frequency']
                try:
                    frequency = float(frequency)
                except ValueError:
                    errors[u'frequency'] = u'Frequency is not a number.'
                else:
                    if not 0 < frequency <= 1000:
                        errors[u'frequency'] = (u'Frequency must be > 0 and '
                                                u'<= 100 Hz')
                dutycycle = valuesDict[u'dutycycle']
                try:
                    dutycycle = float(dutycycle)
                except ValueError:
                    errors[u'dutycycle'] = u'Duty Cycle is not a number.'
                else:
                    if not 0 <= dutycycle <= 100:
                        errors[u'dutycycle'] = (u'Duty Cycle must be >= 0 and '
                                                u'<= 100 %')

        if errors:
            return False, valuesDict, errors
        else:
            return True, values

    def getServers(self, filter="", valuesDict=None, typeId="", targetId=0):
        LOG.threaddebug(u'Plugin.getServers called')
        servers = []
        for dev in indigo.devices.iter(u'self.server'):
            servers.append(dev.name)
        return sorted(servers)

    def didDeviceCommPropertyChange(self, dev, newDev):
        LOG.threaddebug(u'Plugin.didDeviceCommPropertyChange called; old = '
                        u'"%s", new = "%s"', dev.name, newDev.name)
        change = (dev.name != newDev.name
                  or dev.deviceTypeId != newDev.deviceTypeId
                  or dev.pluginProps != newDev.pluginProps)
        LOG.threaddebug(u'change = %s', change)
        return change

    def deviceStartComm(self, dev):
        LOG.threaddebug(u'Plugin.deviceStartComm called "%s"', dev.name)
        if dev.subModel != u'PiDACS':
            dev.subModel = u'PiDACS'
            dev.replaceOnServer()
        if u' ' in dev.name:
            warning = (u'Plugin.deviceStartComm: deferred startup "%s"; '
                       u'space(s) in device name' % dev.name)
            LOG.warning(warning)
            dev.setErrorStateOnServer(u'name')
        else:
            if dev.deviceTypeId == u'server':
                self.startServer(dev)
            else:
                self.startDevice(dev)

    def deviceStopComm(self, dev):
        LOG.threaddebug(u'Plugin.deviceStopComm called "%s"', dev.name)
        if ' ' not in dev.name:  # Stop device only if it was started.
            if dev.deviceTypeId == u'server':
                server = self._servers.get(dev.name)
                if server and server.connected and server.running:
                    for dev_ in indigo.devices.iter(u'self'):
                        if dev_.pluginProps.get(u'serverName') == dev.name:
                            server.sendRequest(
                                dev_.pluginProps[u'channelName'], u'reset')
                            dev_.setErrorStateOnServer(u'server')
                    server.stop()
                    del self._servers[dev.name]
                    dev.updateStateOnServer(key=u'status', value=u'stopped')
                    dev.updateStateImageOnServer(indigo.kStateImageSel.
                                                 SensorOff)
            else:  # Not a server.
                serverName = dev.pluginProps[u'serverName']
                server = self._servers.get(serverName)
                if server and server.connected and server.running:
                    server.sendRequest(dev.pluginProps[u'channelName'],
                                       u'reset')
            LOG.debug(u'stopped "%s"', dev.name)

    def actionControlDevice(self, action, dev):
        LOG.threaddebug(u'Plugin.actionControlDevice called "%s"', dev.name)

        # Check for valid action/device combinations and define the requestId
        # and value needed to perform the action on the server.  Invalid
        # action/device combinations will be left with the requestId and/or
        # value set to None.

        requestId = value = None
        if dev.deviceTypeId == u'digitalOutput':
            if action.deviceAction == indigo.kDeviceAction.TurnOn:
                if dev.pluginProps[u'momentary']:
                    requestId = u'momentary'
                    value = dev.pluginProps[u'turnOffDelay']
                else:
                    requestId = u'write'
                    value = u'on'
            elif action.deviceAction == indigo.kDeviceAction.TurnOff:
                requestId = u'write'
                value = u'off'
            elif (action.deviceAction == indigo.kDeviceAction.Toggle
                  and not dev.pluginProps[u'momentary']):
                requestId = u'write'
                value = u'off' if dev.onState else u'on'
        elif dev.deviceTypeId == u'pwmOutput':
            requestId = u'pwm'
            if action.deviceAction == indigo.kDeviceAction.TurnOn:
                value = u'on'
            elif action.deviceAction == indigo.kDeviceAction.TurnOff:
                value = u'off'

        if requestId and value:

            # Valid action requested for the device; check the server status.
            # Send the request if the server is OK.

            serverName = dev.pluginProps[u'serverName']
            server = self._servers.get(serverName)
            if server and server.connected and server.running:
                server.sendRequest(dev.name, requestId, value)
                LOG.info(u'sent "%s" %s', dev.name, action.deviceAction)
            else:
                LOG.error(u'Plugin.actionControlDevice: server "%s" not '
                          u'running; "%s" %s request ignored', serverName,
                          dev.name, action.deviceAction)
        else:
            LOG.warning(u'Plugin.actionControlDevice: invalid action %s '
                        u'requested for device "%s"; request ignored',
                        action.deviceAction, dev.name)

    def actionControlUniversal(self, action, dev):
        LOG.threaddebug(u'Plugin.actionControlUniversal called "%s"', dev.name)
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            serverName = dev.pluginProps[u'serverName']
            server = self._servers.get(serverName)
            if server and server.connected and server.running:
                server.sendRequest(dev.name, u'read')
                LOG.info(u'sent "%s" status request', dev.name)
            else:
                LOG.error(u'Plugin.actionControlUniversal: server "%s" not '
                          u'running; "%s" status request ignored', serverName,
                          dev.name)
