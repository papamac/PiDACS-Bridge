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
__version__ = '0.9.7'
__date__ = 'August 14, 2019'

import indigo
from logging import addLevelName
from logging import NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL
from random import choice
from threading import Thread
from time import sleep

from pidacs_global import *

PORT_TYPES = (u'ab', u'ga', u'gb', u'gg', u'gp')
THREAD_DEBUG = 5
LOG = None
PLUGIN = None


class PiDACS(Thread):

    # Class attributes:

    servers = {}

    @classmethod
    def setErrorState(cls, serverName, err=True):
        srvDev = indigo.devices.get(serverName)
        srvState = u'Error' if err else None
        clientState = u'Server' if err else None
        if srvDev:
            srvDev.setErrorStateOnServer(srvState)
        for dev in indigo.devices.iter(u'self'):
            name = dev.pluginProps.get(u'serverName')
            if name == serverName:
                dev.setErrorStateOnServer(clientState)

    # Instance methods:

    def __init__(self, serverName):
        self._socketId = None
        self._socket = None
        self._dtRecvd = None
        self.running = False
        Thread.__init__(self, name=serverName)

    def start(self):

        # Attempt connection to server.

        self._socket = socket(AF_INET, SOCK_STREAM)
        self._socket.settimeout(SOCKET_TIMEOUT)
        srvDev = indigo.devices[self.name]
        ipv4, portNumber = srvDev.pluginProps[u'socketId'].split(u':')
        try:
            self._socket.connect((ipv4, int(portNumber)))
        except error as err:

            # Connection failed; set errors state on all devices.

            LOG.error(u'connection error "%s" %s' % (self.name, err))
            self.setErrorState(self.name)
            return

        self._socketId = u'%s:%i' % self._socket.getsockname()
        LOG.info(u'connected "%s" via socket "%s"'
                 % (self.name, self._socketId))

        # Connection succeeded; complete server startup.

        self.running = True
        self._dtRecvd = datetime.now()
        Thread.start(self)
        self.servers[self.name] = self
        srvDev.updateStateOnServer(key=u'status', value=u'Running')
        srvDev.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
        self.setErrorState(self.name, False)
        LOG.debug(u'server "%s" started' % self.name)
            
    def stop(self):
        self._socket.close()
        LOG.info(u'closed "%s"' % self._socketId)
        self.running = False
        del (self.servers[self.name])
        srvDev = indigo.devices.get(self.name)
        if srvDev:
            srvDev.updateStateOnServer(key=u'status', value=u'Stopped')
            srvDev.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
        LOG.debug(u'server "%s" stopped' % self.name)

    def run(self):
        LOG.log(THREAD_DEBUG, u'thread "%s" started' % self.name)
        while self.running:
            try:
                message = recv_msg(self, self._socket, self._dtRecvd)
                if not self.running:
                    continue
            except OSError as err:
                errMsg = 'recv error "%s" %s' % (self.name, err)
                break
            except BrokenPipe:
                errMsg = 'disconnected "%s"' % self.name
                break
            except ServerTimeout:
                errMsg = 'timeout "%s"' % self.name
                break

            self._dtRecvd = datetime.now()
            dtMessage = message[:DATETIME_LENGTH]
            try:
                dtSent = datetime.strptime(dtMessage, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                LOG.warning(u'invalid datetime %s" "%s"'
                            % (self.name, dtMessage))
                continue
            latency = (self._dtRecvd - dtSent).total_seconds()
            if latency > LATENCY:
                LOG.warning(u'late message "%s"; lartency = %3.1f secs'
                            % (self.name, latency))
            messageList = message[DATETIME_LENGTH:].split()
            level = int(messageList[0])
            name = u'"%s"' % self.name
            messageText = message[DATETIME_LENGTH + 4:]
            LOG.log(level, u'received %-18s %s' % (name, messageText))
            if level == DATA:
                channelId = messageList[1]
                devName = channelId.split(u'[')[0]
                dev = indigo.devices.get(devName)
                if dev:
                    value = messageList[2]
                    if value == u'!ERROR':
                        dev.setErrorStateOnServer(u'Error')
                        continue
                    if not dev.enabled:
                        continue
                    if dev.deviceTypeId == u'analogInput':
                        valueIsanumber = value.replace(u'.', '', 1).isdecimal()
                        if not valueIsanumber:
                            LOG.error(u'invalid analog value "%s" for'
                                      u'channel "%s"' % (value, channelId))
                            continue
                        sensorValue = float(value)
                        units = dev.pluginProps[u'units']
                        uiValue = u'%5.2f %s' % (sensorValue, units)
                        dev.updateStateOnServer('sensorValue', sensorValue,
                                                uiValue=uiValue)
                        LOG.info(u'received "%s" update to "%s"'
                                 % (dev.name, uiValue))
                    else:
                        if value not in (u'0', u'1'):
                            LOG.error(u'invalid bit value "%s" for '
                                      u'channel "%s"' % (value, channelId))
                            continue
                        state = u'on' if value == u'1' else u'off'
                        dev.updateStateOnServer('onOffState', state)
                        dev.updateStateImageOnServer(
                                indigo.kStateImageSel.Auto)
                        LOG.info(u'received "%s" update to "%s"'
                                 % (dev.name, state))
                else:
                    if PLUGIN.pluginPrefs[u'logStateChanges']:
                        LOG.warning(u'received "%s" state change on '
                                    u'unassigned device %s'
                                    % (self.name, devName))
        else:
            LOG.log(THREAD_DEBUG, u'thread "%s" ended normally' % self.name)
            return

        LOG.error(errMsg)
        self.stop()
        self.setErrorState(self.name)
        LOG.log(THREAD_DEBUG, u'thread "%s" ended with errors' % self.name)

    def sendRequest(self, *args):
        if self.running:
            req = unicode(datetime.now())
            for arg in args:
                req = req + u' ' + unicode(arg)
            try:
                send_msg(self._socket, req)
            except OSError as err:
                errMsg = 'send error "%s" %s' % (self.name, err)
            except BrokenPipe:
                errMsg = 'broken pipe to server "%s"' % self.name
            else:
                return

            LOG.error(errMsg)
            self.stop()
            self.setErrorState(self.name)


class Plugin(indigo.PluginBase):

    # Instance methods:

    def __init__(self, pluginId, pluginDisplayName,
                 pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName,
                                     pluginVersion, pluginPrefs)
        addLevelName(DATA, u'DATA')
        self.indigo_log_handler.setLevel(NOTSET)
        level = eval(pluginPrefs[u'loggingLevel'])
        global LOG, PLUGIN
        LOG = self.logger
        LOG.setLevel(level)

        PLUGIN = self
        LOG.debug(pluginPrefs)

    def startup(self):
        LOG.debug(u'startup called')

    def shutdown(self):
        LOG.debug(u'shutdown called')

    def validatePrefsConfigUi(self, valuesDict):
        LOG.debug(u'validatePrefsConfigUi called')
        level = eval(valuesDict[u'loggingLevel'])
        LOG.setLevel(level)
        return True, valuesDict

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        dev = indigo.devices[devId]
        LOG.debug(u'validateDeviceConfigUi called for "%s"' % dev.name)
        LOG.debug(u'dev.configured = %s' % dev.configured)
        values = valuesDict
        errors = indigo.Dict()

        if typeId == 'server':
            serverAddress = valuesDict[u'serverAddress']
            ipv4 = ''
            try:
                ipv4 = gethostbyname(serverAddress)
            except gaierror as err:
                errors[u'serverAddress'] = (u'Address resolution error: %s'
                                            % err)
            portNumber = valuesDict[u'portNumber']
            if portNumber.isdecimal():
                portNumber = int(portNumber)
                if portNumber not in DYNAMIC_PORT_RANGE:
                    errors[u'portNumber'] = (u'Port number not in dynamic '
                                             u'port range.')
            else:
                errors[u'portNumber'] = u'Port number is not an integer.'
            values[u'socketId'] = u'%s:%s' % (ipv4, portNumber)
            serverId = valuesDict[u'serverId']
            if not serverId:
                split1 = serverAddress.split(u'.', 1)
                split2 = split1[0].split(u'-')
                if len(split2) > 1:
                    serverId = split2[1]
                else:
                    serverId = chr(choice(range(97, 123)))
            for srvDev in indigo.devices.iter(u'self.server'):
                if srvDev.id == devId:
                    continue
                if srvDev.pluginProps[u'serverId'] == serverId:
                    errors[u'serverId'] = (u'Server Id already in use; '
                                           u'choose again')
                    break
            values[u'serverId'] = serverId
            values[u'address'] = serverId

        else:
            serverName = valuesDict[u'serverName']
            srvDev = indigo.devices[serverName]
            serverId = srvDev.pluginProps[u'serverId']
            channelName = valuesDict[u'channelName']
            goodName = (len(channelName) == 4
                        and channelName[:2] in PORT_TYPES
                        and channelName[2:].isdecimal())
            if not goodName:
                errors[u'channelName'] = u'Invalid channel name'
            values[u'address'] = u'%s.%s' % (serverId, channelName)
            if typeId == u'digitalOutput':
                delay = valuesDict[u'turnOffDelay']
                delayIsanumber = delay.replace(u'.', '', 1).isdecimal()
                if not delayIsanumber:
                    errors[u'turnOffDelay'] = (u'Turn-off delay is not a '
                                               u'number')

        if errors:
            return False, valuesDict, errors
        else:
            return True, values

    def getServers(self, filter="", valuesDict=None, typeId="", targetId=0):
        LOG.debug(u'called getServers')
        servers = []
        for dev in indigo.devices.iter(u'self.server'):
            servers.append(dev.name)
        return sorted(servers)

    def didDeviceCommPropertyChange(self, dev, newDev):
        LOG.debug(u'didDeviceCommPropertyChange called: old = "%s", new = "%s"'
                  % (dev.name, newDev.name))
        change = (dev.name != newDev.name
                  or dev.deviceTypeId != newDev.deviceTypeId
                  or dev.pluginProps != newDev.pluginProps)
        LOG.debug(u'change = %s' % change)
        return change

    def deviceStartComm(self, dev):
        self.debugLog(u'devicesStartComm called for "%s"' % dev.name)
        if dev.subModel != u'PiDACS':
            dev.subModel = u'PiDACS'
            dev.replaceOnServer()
        if u' ' in dev.name:
            LOG.warning(u'startup for device "%s" deferred until final device '
                        u'name (no spaces) is specified' % dev.name)
        else:
            typeId = dev.deviceTypeId
            if typeId == u'server':
                if dev.name in PiDACS.servers:
                    LOG.critical(u'server "%s" already in servers dictionary'
                                 % dev.name)
                server = PiDACS(dev.name)
                server.start()
                if server.running:
                    for ioDev in indigo.devices.iter(u'self'):
                        if (ioDev.enabled and ioDev.deviceTypeId != u'server'
                                and ioDev.pluginProps[u'serverName']
                                == dev.name):
                            self.deviceStartComm(ioDev)
            else:
                serverName = dev.pluginProps[u'serverName']
                server = PiDACS.servers.get(serverName)
                if server and server.running:
                    channelName = dev.pluginProps[u'channelName']
                    server.sendRequest(channelName, u'alias', dev.name)
                    if typeId == u'analogInput':
                        resolution = dev.pluginProps[u'resolution']
                        server.sendRequest(dev.name, u'resolution', resolution)
                        gain = dev.pluginProps[u'gain']
                        server.sendRequest(dev.name, u'gain', gain)
                        scaling = dev.pluginProps[u'scaling']
                        if scaling != u'Default':
                            server.sendRequest(dev.name, u'scaling', scaling)
                    elif typeId == u'digitalInput':
                        direction = u'1'
                        server.sendRequest(dev.name, u'direction', direction)
                        polarity = dev.pluginProps[u'polarity']
                        server.sendRequest(dev.name, u'polarity', polarity)
                        pullup = dev.pluginProps[u'pullup']
                        server.sendRequest(dev.name, u'pullup', pullup)
                    else:  # deviceTypeId == u'digitalOutput'
                        direction = u'0'
                        server.sendRequest(dev.name, u'direction', direction)
                        if self.pluginPrefs[u'restartClear']:
                            server.sendRequest(dev.name, u'write', '0')
                    change = dev.pluginProps[u'change']
                    if isinstance(change, bool):
                        change = u'true' if change else u'false'
                    server.sendRequest(dev.name, u'change', change)
                    if dev.pluginProps[u'periodic']:
                        interval = dev.pluginProps[u'interval']
                        server.sendRequest(dev.name, u'interval', interval)
                    server.sendRequest(dev.name, u'read')
                    sleep(0.5)

    def deviceStopComm(self, dev):
        LOG.debug(u'devicesStopComm called for "%s"' % dev.name)
        if dev.deviceTypeId == u'server':
            server = PiDACS.servers.get(dev.name)
            if server:
                server.stop()

    def actionControlDevice(self, action, dev):
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
        server = PiDACS.servers.get(serverName)
        if server and server.running:
            requestId = 'write'
            if value and dev.pluginProps[u'momentary']:
                value = dev.pluginProps[u'turnOffDelay']
                requestId = 'momentary'
            server.sendRequest(dev.name, requestId, value)
            LOG.info(u'sent "%s" %s' % (dev.name, action))
        else:
            LOG.error(u'server "%s" not running; "%s" %s request ignored'
                      % (serverName, dev.name, action))

    def actionControlUniversal(self, action, dev):
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            serverName = dev.pluginProps[u'serverName']
            server = PiDACS.servers.get(serverName)
            if server and server.running:
                server.sendRequest(dev.name, 'read')
                LOG.info(u'sent "%s" status request' % dev.name)
            else:
                LOG.error(u'server "%s" not running; "%s" status request '
                          u'ignored' % (serverName, dev.name))
