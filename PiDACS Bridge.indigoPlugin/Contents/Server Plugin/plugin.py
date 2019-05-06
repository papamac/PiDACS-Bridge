#! /usr/bin/env python

import indigo
from logging import NOTSET, DEBUG, INFO, WARNING, ERROR, CRITICAL
from random import choice
from threading import Thread

from pidacs_global import *

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
        Thread.__init__(self, name=serverName,
                        target=self._processServerMessages)

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
        LOG.debug(u'server "%s" stopped' % self.name)

    def _processServerMessages(self):
        LOG.log(5, u'thread "%s" started' % self.name)
        while self.running:
            try:
                message = recv_msg(self, self._socket, self._dtRecvd)
                if not self.running:
                    continue
            except OSError as err:
                errMsg = 'recv error "%s" %s' % (self.name, err)
                break
            except BrokenPipe:
                errMsg = 'server disconnected "%s"' % self.name
                break
            except ServerTimeout:
                errMsg = 'server timeout "%s"' % self.name
                break

            self._dtRecvd = datetime.now()
            name = u'"%s"' % self.name
            LOG.debug(u'received %-21s %s' % (name, message))
            try:
                dtSent = datetime.strptime(message[:26],
                                           '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                LOG.warn(u'invalid datetime in message "%s"' % self.name)
                continue
            latency = (self._dtRecvd - dtSent).total_seconds()
            if latency > LATENCY:
                LOG.warn(u'late message "%s" %3.1f' % (self.name, latency))
            messageList = message[26:].split()
            messageId = messageList[0]
            if messageId in (u'change:', u'value:'):
                devName = messageList[1].split(u'|')[0]
                valueStr = messageList[2]
                value = float(valueStr) if u'.' in valueStr else int(valueStr)
                dev = indigo.devices.get(devName)
                if dev:
                    if dev.enabled:
                        state = u'on' if value else u'off'
                        dev.updateStateOnServer('onOffState', state)
                        dev.updateStateImageOnServer(
                                indigo.kStateImageSel.Auto)
                        LOG.info(u'received "%s" update to "%s"'
                                 % (dev.name, state))
                else:
                    if PLUGIN.pluginPrefs[u'logStateChanges']:
                        LOG.warn(u'received "%s" state change on unassigned '
                                 u'device %s' % (self.name, devName))
        else:
            LOG.log(5, u'thread "%s" ended normally' % self.name)
            return

        LOG.error(errMsg)
        self.stop()
        self.setErrorState(self.name)
        LOG.log(5, u'thread "%s" ended with errors' % self.name)

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
        self.indigo_log_handler.setLevel(NOTSET)
        level = eval(pluginPrefs.get(u'loggingLevel', u'5'))
        global LOG, PLUGIN
        LOG = self.logger
        LOG.setLevel(level)
        PLUGIN = self
        LOG.debug(pluginPrefs)

    def startup(self):
        LOG.debug(u'startup called')

    def shutdown(self):
        LOG.debug(u'shutdown called')

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        dev = indigo.devices[devId]
        LOG.debug(u'validateDeviceConf called for "%s"' % dev.name)
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
            if portNumber.isnumeric():
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
                        and channelName[:2] in ('ga', 'gb', 'gg', 'gp')
                        and channelName[2:].isnumeric())
            if not goodName:
                errors[u'channelName'] = u'Invalid channel name'
            values[u'address'] = u'%s.%s' % (serverId, channelName)
            if typeId == u'digitalOutput':
                delay = valuesDict[u'turnOffDelay']
                if not delay.replace(u'.', u'').isnumeric():
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
            LOG.warn(u'startup for device "%s" deferred until final device '
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
                    if typeId == u'digitalInput':
                        direction = u'1'
                        polarity = dev.pluginProps[u'polarity']
                        pullup = dev.pluginProps[u'pullup']
                    else:  # deviceTypeId == u'digitalOutput'
                        direction = polarity = pullup = u'0'

                    channelName = dev.pluginProps[u'channelName']
                    server.sendRequest(channelName, u'alias', dev.name)
                    server.sendRequest(dev.name, u'direction', direction)
                    server.sendRequest(dev.name, u'polarity', polarity)
                    server.sendRequest(dev.name, u'pullup', pullup)
                    server.sendRequest(dev.name, u'read')
                    if (typeId == u'digitalOutput'
                            and self.pluginPrefs[u'restartClear']):
                        server.sendRequest(dev.name, u'write', '0')
                    if dev.pluginProps[u'change']:
                        server.sendRequest(dev.name, u'change', '1')
                    if dev.pluginProps[u'periodic']:
                        interval = dev.pluginProps[u'interval']
                        server.sendRequest(dev.name, u'interval', interval)

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
