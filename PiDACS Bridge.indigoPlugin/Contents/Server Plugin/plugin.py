#! /usr/bin/env python

import indigo
from threading import Thread
from time import sleep

from pidacs_global import *


###############################################################################

class Server(Thread):

    # Class attributes:

    nextSrvNum = 0
    plugin = None
    servers = None

    # Class methods:

    @staticmethod
    def initializeServers(plugin):
        maxSrvNum = Server.nextSrvNum - 1
        for dev in indigo.devices.iter('self'):
            srvNum = int(dev.pluginProps[u'address'].split(u'.')[0])
            if srvNum > maxSrvNum:
                maxSrvNum = srvNum
        Server.nextSrvNum = maxSrvNum + 1
        Server.plugin = plugin
        Server.servers = {}

    @staticmethod
    def displayChannelAssignments():
        for sockId in Server.servers:
            srv = Server.servers[sockId]
            chans = []
            for devId in srv.devices:
                dev = indigo.devices[devId]
                channel = dev.pluginProps[u'channel']
                chans.append(channel)
            srvAddr = u'"%s"' % srv.srvAddr
            Server.plugin.debugLog(u'assigned %-21s srv %d: %s'
                % (srvAddr, srv.srvNum, sorted(chans)))

    @staticmethod
    def getServer(dev=None, srvAddr=None, sockId=None,):
        if dev:
            srvAddr = dev.pluginProps[u'srvAddr']
            sockId = dev.pluginProps[u'sockId']
        if sockId in Server.servers:
            return Server.servers[sockId]
        else:
            if dev:
                srvNum = int(dev.pluginProps[u'address'].split(u'.')[0])
            else:
                srvNum = Server.nextSrvNum
                Server.nextSrvNum += 1
            srv = Server.servers[sockId] = Server(srvAddr, sockId, srvNum)
            return srv

    # Private instance methods:

    def __init__(self, srvAddr, sockId, srvNum):
        self.srvAddr = srvAddr
        self.sockId = sockId
        self.srvNum = srvNum
        self.sock = None
        self.dtRecvd = None
        self.devices = []
        self.running = False
        Thread.__init__(self, name='rasPiIOPluginServer',
                        target=self._processServerData)

    def _disableServerDevices(self, errMsg):
        indigo.server.log(errMsg, isError=True)
        indigo.server.log(u'disabling all devices "%s"'
                          % self.srvAddr, isError=True)
        for devId in self.devices:
            indigo.device.enable(devId, value=False)
            dev = indigo.devices[devId]
            indigo.server.log('disabled "%s"' % dev.name, isError=True)
        indigo.variable.updateValue(u'serverShutDown', value=self.srvAddr)
        sleep(0.5)
        indigo.variable.updateValue(u'serverShutDown', value=u'None')
        return

    def _processServerData(self):
        self.plugin.debugLog(u'_processServerData started "%s" %d'
                             % (self.srvAddr, self.ident))
        while self.running:
            try:
                data = recv_msg(self, self.sock, self.dtRecvd)
                if not self.running:
                    continue
            except OSError as errMsg:
                errMsg = 'recv error "%s" %s' % (self.srvAddr, errMsg)
                break
            except BrokenPipe:
                errMsg = 'server disconnected "%s"' % self.srvAddr
                break
            except ServerTimeout:
                errMsg = 'server timeout "%s"' % self.srvAddr
                break
            self.dtRecvd = datetime.now()
            sAddr = u'"%s"' % self.srvAddr
            self.plugin.debugLog(u'received %-21s %s' % (sAddr, data))
            try:
                dtSent = datetime.strptime(data[:26],
                                           '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                errMsg = u'invalid datetime in data record "%s"'\
                          % self.srvAddr
                indigo.server.log(errMsg, isError=True)
                continue
            latency = (self.dtRecvd - dtSent).total_seconds()
            if latency > LATENCY_LIMIT:
                indigo.server.log(u'late data "%s" %5.3f' % (self.srvAddr,
                                  latency), isError=True)
            indigo.server.log(data)
            dataList = data[26:].split()
            dataId = dataList[0]
            if dataId in (u'change:', u'value:'):
                channel = dataList[1]
                valueStr = dataList[2]
                value = (float(valueStr) if u'.' in valueStr else
                         int(valueStr))
                for devId in self.devices:
                    dev = indigo.devices[devId]
                    chan = dev.pluginProps[u'channel']
                    if chan == channel:
                        if dev.enabled and dev.configured:
                            state = u'on' if value else u'off'
                            dev.updateStateOnServer('onOffState', state)
                            dev.updateStateImageOnServer(
                                indigo.kStateImageSel.Auto)
                            indigo.server.log(u'received "%s" update to '
                                              u'"%s"' % (dev.name, state))
                            break
                else:
                    if dataId != u'v':
                        indigo.server.log(
                            u'received "%s" state change on unassigned '
                            u'channel %s' % (self.srvAddr, channel),
                            isError=True)
        else:
            self.plugin.debugLog(u'_processServerData ended normally "%s" %d'
                                 % (self.srvAddr, self.ident))
            return
        self._disableServerDevices(errMsg)
        self.plugin.debugLog(
            u'_processServerData ended with errors "%s" %d'
            % (self.srvAddr, self.ident))

    # Public instance methods:

    def start(self):
        self.sock = socket(AF_INET, SOCK_STREAM)
        self.sock.settimeout(1.0)
        srvIPv4, port = self.sockId.split(u':')
        try:
            self.sock.connect((srvIPv4, int(port)))
        except error as errMsg:
            indigo.server.log(u'connection error "%s" %s'
                              % (self.srvAddr, unicode(errMsg)), isError=True)
            return False
        indigo.server.log(u'connected "%s" via socket "%s"' % (self.srvAddr,
                                                               self.sockId))
        self.dtRecvd = datetime.now()
        self.running = True
        Thread.start(self)
        return True

    def stop(self):
        if self.sock is not None:
            self.sock.close()
            indigo.server.log(u'closed "%s"' % self.sockId)
        self.running = False
        del self.servers[self.sockId]

    def assignDevice(self, dev):
        self.devices.append(dev.id)

    def removeDevice(self, dev):
        if dev.id in self.devices:
            self.devices.remove(dev.id)
            if not self.devices:
                self.stop()

    def channelIsAssigned(self, channel):
        assigned = False
        for devId in self.devices:
            dev = indigo.devices[devId]
            if channel == dev.pluginProps[u'channel']:
                assigned = True
                break
        return assigned

    def sendRequest(self, *args):
        req = unicode(datetime.now())
        for arg in args:
            req = req + u' ' + unicode(arg)
        try:
            send_msg(self.sock, req)
        except OSError as errMsg:
            errMsg = 'recv error "%s" %s' % (self.srvAddr, errMsg)
        except BrokenPipe:
            errMsg = 'broken pipe to server "%s"' % self.srvAddr
        else:
            return
        self._disableServerDevices(errMsg)



###############################################################################

class Plugin(indigo.PluginBase):

    # Instance methods:

    def __init__(self, pluginId, pluginDisplayName,
                 pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName,
                                     pluginVersion, pluginPrefs)
        self.debug = False

    def startup(self):
        self.debugLog(u'startup called')
        Server.initializeServers(self)

    def shutdown(self):
        self.debugLog(u'shutdown called')

    def validateDeviceConfigUi(self, valuesDict, typeId, devId):
        dev = indigo.devices[devId]
        self.debugLog(u'validateDeviceConf called for "%s"' % dev.name)
        self.debugLog(u'dev.configured = %s' % str(dev.configured))
        errorsDict = indigo.Dict()
        srvAddr = valuesDict[u'srvAddr']
        try:
            srvIPv4 = gethostbyname(srvAddr)
        except error as errMsg:
            errorsDict[u'srvAddr'] = (u'address resolution error: '
                                      + unicode(errMsg))
        if not valuesDict[u'port'].isdigit():
            errorsDict[u'port'] = u'Port number is not an unsigned interger'
        else:
            port = int(valuesDict[u'port'])
            if not (49152 <= port <= 65535):
                errorsDict[u'port'] = (u'Port number is not in dynamic '
                                       + 'port range')
        if len(valuesDict[u'channel']) != 4:
            errorsDict[u'channel'] = (u'Channel Id is not an '
                                      + 'unsigned interger')
        else:
            channel = valuesDict[u'channel']
        if not valuesDict[u'turnOffDelay'].isdigit():
            errorsDict[u'turnOffDelay'] = (u'Turn-off delay is not an '
                                           +'unsigned integer')
        if errorsDict:
            return False, valuesDict, errorsDict

        sockId = u'%s:%d' % (srvIPv4, port)
        srv = Server.getServer(srvAddr=srvAddr, sockId=sockId)

        if srv.channelIsAssigned(channel):
            dev = indigo.devices[devId]
            if channel != dev.pluginProps.get(u'channel', -1):
                errorsDict = indigo.Dict()
                errorsDict[u'channel'] = (u'Channel Id is already '
                                          + 'assigned')
                return False, valuesDict, errorsDict

        address = u'%s.%s' % (srv.srvNum, channel)

        vDict = valuesDict
        vDict[u'address'] = address
        vDict[u'sockId'] = sockId
        return True, vDict

    def deviceStartComm(self, dev):
        self.debugLog(u'devicesStartComm called for "%s"' % dev.name)
        dev.subModel = u'rasPiIO'
        dev.replaceOnServer()
        srv = Server.getServer(dev)
        channel = dev.pluginProps[u'channel']
        if srv.channelIsAssigned(channel):
            self.debugLog(u'duplicate channel "%s" device deconfigured'
                          % dev.name)
            dev.configured = False
            dev.replaceOnServer()
            newProps = dev.pluginProps
            del newProps[u'address']
            del newProps[u'channel']
            dev.replacePluginPropsOnServer(newProps)
            indigo.PluginBase.deviceStartComm(self, dev)
            return

        srv.assignDevice(dev)
        Server.displayChannelAssignments()

        if not srv.running:
            if not srv.start():
                indigo.device.enable(dev.id, value=False)
                indigo.server.log(u'disabled "%s"' % dev.name, isError=True)
                indigo.PluginBase.deviceStartComm(self, dev)
                return

        if dev.deviceTypeId == u'digitalInput':
            direction = 1
            polarity = 1 if dev.pluginProps[u'polarity'] == u'Inverted' else 0
            pullup = 1 if dev.pluginProps[u'pullup'] else 0
        else:
            direction = polarity = pullup = 0
        srv.sendRequest(channel, 'direction', direction)
        srv.sendRequest(channel, 'polarity', polarity)
        srv.sendRequest(channel, 'pullup', pullup)
        indigo.PluginBase.deviceStartComm(self, dev)

    def deviceStopComm(self, dev):
        self.debugLog(u'devicesStopComm called for "%s"' % dev.name)
        srv = Server.getServer(dev)
        srv.removeDevice(dev)
        Server.displayChannelAssignments()
        indigo.PluginBase.deviceStopComm(self, dev)

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
        srv = Server.getServer(dev)
        channel = dev.pluginProps[u'channel']
        srv.sendRequest(channel, 'write', value)
        indigo.server.log(u'sent "%s" %s' % (dev.name, action))
        if value and dev.pluginProps[u'momentaryTurnOn']:
            delay = int(dev.pluginProps[u'turnOffDelay'])
            if not delay:
                sleep(0.5)
            indigo.device.turnOff(dev.id, delay=delay)

    def actionControlUniversal(self, action, dev):
        if action.deviceAction == indigo.kUniversalAction.RequestStatus:
            srv = Server.getServer(dev)
            channel = dev.pluginProps[u'channel']
            srv.sendRequest(channel, 'read')
            indigo.server.log(u'sent "%s" status request' % dev.name)