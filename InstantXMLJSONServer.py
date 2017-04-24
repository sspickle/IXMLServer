#!/usr/bin/env python
#
# Medusa Based XMLSocket/JSON WebSocket server
#

RCS_ID = '$Id: InstantXMLJSONServer.py,v 1.1 2012-06-21 12:36:50 steve Exp $'

import sys, string, os, socket, errno, struct
from StringIO import StringIO
import traceback
from hashlib import md5, sha1
import base64

# UUIDs used by HyBi 04 and later opening handshake and frame masking.
WEBSOCKET_ACCEPT_UUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

def getException():
    f = StringIO()
    traceback.print_exc(file=f)
    f.seek(0)
    return f.read()

import asyncore

import string

VERSION = string.split(RCS_ID,' ')[2]

PING_SLEEPTIME = 10   # seconds

import socket
import asyncore
import asynchat

from xmlrpclib import loads, dumps
import json

from threading import RLock, Thread
from time import sleep

def clean(src):
    return src + '\0'
    
def jsonclean(src):
    return '\0' + src + '\xff'

class PingThread( Thread ):

    running = 0

    def __init__(self, client):
        Thread.__init__(self)
        self.client = client
        
        
    def pause(self):
        """
        stop pinging.
        """
        self.running = 0
        
    def run(self):
        """
        wait on xml...
        """
        self.running = 1
        while 1:
            if self.running:
                sleep(PING_SLEEPTIME)
                self.client.do_ping()
            else:
                break
    
class xml_chat_channel (asynchat.async_chat):

    def __init__ (self, server, sock, addr):
        asynchat.async_chat.__init__ (self, sock)
        self.server = server
        self.addr = addr
        self.set_terminator ('\0')
        self.data = ''
        self.xml = ''
        self.sender_id = ''
        self.needs_ping = 0
        
    def collect_incoming_data (self, data):
        self.server.log_info('in collect.. ' + `data`)
        self.data = self.data + data
        
    def found_terminator (self):
        self.server.log_info('in found term... ')
        line = self.data
        self.data = ''
        self.xml = self.xml + line
        xmlToSend = self.xml
        self.xml = ''

        try:
            values, mName = loads(xmlToSend)
        except:
            exc = getException()
            self.server.log_info('Incomplete/Bad XML (%s) from %s %s' % (`self.xml`, self.sender_id, exc))
            return

        self.server.log_info('Got XML! (%s) "%s" from %s' % (`values` + ":" + `mName`, `xmlToSend`, self.sender_id))
            
        if not self.sender_id:
            if values:
                values = values[0]
                self.server.log_info('Found type(values) of "%s"' % type(values))
                if type(values) == type({}):
                    if self.server.ssecret:
                        if self.server.ssecret != values.get('ssecret',''):  # if the server 
                            return
                    self.sender_id = values.get('sender_id','')
                    self.needs_ping = values.get('send_ping',0)
                    if self.needs_ping:
                        self.server.setup_ping_thread(self)
                    
                    if not self.sender_id:
                        self.sender_id = None
                        self.push(clean(dumps(({'Error':'Error.. bad sender_id:"%s"' % `values`},))))
                    else:
                        self.greet()
        else:
            if values:
                sentValues = 0
                self.server.log_info('Found type(values) of "%s"' % type(values))
                if type(values) in [type([]), type(())]:
                    cmdDict = values[0]
                    if type(cmdDict) == type({}):
                        command = cmdDict.get('command','')
                        if command:
                            sentValues = 1
                            self.server.log_info('Command received from: %s (%s)' % (self.sender_id, command))
                            self.handle_command(command)
                        else:
                            target_id = cmdDict.get('target_id','')
                            if target_id:
                                sentValues = 1
                                self.server.log_info('targeted data received from: %s to %s' % (self.sender_id, target_id))
                                self.server.push_line(self, values, target_id)
                                
                if not sentValues:
                    self.server.push_line(self, values)

    def greet (self):
        self.push(clean(dumps(({'connected': ('sender_id="%s"' % self.sender_id)},))))
            
    def handle_command (self, command):
        import types
        command_line = string.split(command)
        name = 'cmd_%s' % command_line[0]
        if hasattr (self, name):
                # make sure it's a method...
            method = getattr (self, name, None)
            if type(method) == type(self.handle_command):
                method (command_line[1:])
            else:
                self.push(clean(dumps(({'unknown command':' %s' % command_line[0]},))))
                
    def cmd_quit (self, args):
        self.server.push_line (self, dumps(({'message':('text="%s left"' % self.sender_id)},)))
        self.push (clean(dumps(({'message':' text="Goodbye!"'},))))
        self.close_when_done()
        
    # alias for '/quit' - '/q'
    cmd_q = cmd_quit
    
    def push_line (self, sender_id, line):
        self.push (clean(line))
        
    def handle_close (self):
        self.server.log_info('Sender %s closed connection' % self.sender_id)
        self.close()
        
    def close (self):
        del self.server.channels[self]
        asynchat.async_chat.close (self)
        
    def get_sender_id (self):
        if self.sender_id is not None:
            return self.sender_id
        else:
            return 'Unknown'

    def get_channel_id(self):
        if self.sender_id is not None:
            sep = self.sender_id.find(':')
            if sep > 0:
                return self.sender_id[:sep]
        return ''

handshake = '\
HTTP/1.1 101 Web Socket Protocol Handshake\r\n\
Upgrade: WebSocket\r\n\
Connection: Upgrade\r\n\
Sec-WebSocket-Origin: %s\r\n\
Sec-WebSocket-Location: ws://%s/\r\n\r\n%s\r\n'
            
class json_chat_channel (asynchat.async_chat):

    def __init__ (self, server, sock, addr):
        asynchat.async_chat.__init__ (self, sock)
        self.server = server
        self.addr = addr
        self.set_terminator ('\r\n\r\n')
        self.negotiating = True
        self.data = ''
        self.json = ''
        self.sender_id = ''
        self.needs_ping = 0
        
    def collect_incoming_data (self, data):
        self.server.log_info('in collect.. ' + `data`)
        self.data = self.data + data
        
    def getMD5(self, key1, key2, last8):
        """
        Given the two keys and the last 8 bytes.. compute the md5 response
        """
        n1=[]
        s1=0
        n2=[]
        s2=0
        for c in key1:
            if c.isdigit():
                n1.append(c)
            if c.isspace():
                s1+=1
    
        for c in key2:
            if c.isdigit():
                n2.append(c)
            if c.isspace():
                s2+=1
    
        d1 = int(''.join(n1))
        d2 = int(''.join(n2))
        z1=d1/s1
        z2=d2/s2
        
        print "Key 1 has %d spaces:" % s1, z1
        print "Key 2 has %d spaces:" % s2, z2
    
        mdThing = struct.pack(">LL", z1, z2) + last8
        return md5(mdThing).digest()
        
    def compute_accept(self, key):
        """Computes value for the Sec-WebSocket-Accept header from value of the
        Sec-WebSocket-Key header.
        """
    
        accept_binary = sha1(
            key + WEBSOCKET_ACCEPT_UUID).digest()
        accept = base64.b64encode(accept_binary)
    
        return (accept, accept_binary)
            
    def found_terminator (self):
        self.server.log_info('in json found term... ' + `self.get_terminator()`)
        self.server.log_info('current data:' + `self.data`)
        self.server.log_info('current json:' + `self.json`)
        if self.negotiating:
            if self.get_terminator() == '\r\n\r\n':
                #
                # we're still getting headers.... get the last 8 bytes
                #
                self.data = self.data + '\r\n\r\n'
                self.set_terminator(8)

            elif self.get_terminator() == 0:

                self.server.log_info("We have data:" + `self.data`)

                headerdata = self.data.split('\r\n')
                headers = {}
                self.data = ''
                
                for i in range(len(headerdata)):
                    print i,'->',`headerdata[i]`
                    firstCol = headerdata[i].find(':')
                    if firstCol>0:
                        key = headerdata[i][:firstCol]
                        val = headerdata[i][firstCol+2:]
                        headers[key] = val
    
    
                key1 = headers.get('Sec-WebSocket-Key1','')
                key2 = headers.get('Sec-WebSocket-Key2','')
                origin = headers.get('Origin','')
                host = headers.get('Host','')
                last8 = headerdata[-1]
                handshaken = True
                
                response =  handshake % (origin, host, self.getMD5(key1, key2, last8))
                #self.server.log_info("Sending back:" + response)
                self.set_terminator('\xff')
                self.negotiating = False
                self.push(response)
        else:
            line = self.data
            self.data = ''
            self.json = self.json + line
            self.server.log_info('Looking for json in:' + self.json)
            jsonToSend = self.json
            self.json = ''
            if jsonToSend[0] == '\x00':
                jsonToSend=jsonToSend[1:]
            try:
                dict = json.loads(jsonToSend)
            except:
                exc = getException()
                self.server.log_info('Incomplete/Bad JSON (%s) from %s %s' % (`self.json`, self.sender_id, exc))
                return
    
            self.server.log_info('Got JSON! (%s) "%s" from %s' % (`dict`, `jsonToSend`, self.sender_id))
                
            if not self.sender_id:
                if dict:
                    values = dict
                    self.server.log_info('Found type(values) of "%s"' % type(values))
                    if type(values) == type({}):
                        self.sender_id = values.get('sender_id','')
                        
                        if not self.sender_id:
                            self.sender_id = None
                            self.push(clean(dumps(({'Error':'Error.. bad sender_id:"%s"' % `values`},))))
                        else:
                            self.greet()
            else:
                if dict:
                    values = dict
                    sentValues = 0
                    self.server.log_info('Found type(values) of "%s"' % type(values))
                    if type(values) in [type([]), type(())]:
                        cmdDict = values[0]
                        if type(cmdDict) == type({}):
                            command = cmdDict.get('command','')
                            if command:
                                sentValues = 1
                                self.server.log_info('Command received from: %s (%s)' % (self.sender_id, command))
                                self.handle_command(command)
                            else:
                                target_id = cmdDict.get('target_id','')
                                if target_id:
                                    sentValues = 1
                                    self.server.log_info('targeted data received from: %s to %s' % (self.sender_id, target_id))
                                    self.server.push_line(self, values, target_id)
                                    
                    if not sentValues:
                        self.server.push_line(self, values)

    def greet (self):
        self.server.log_info('Sending greeting back...')
        line = jsonclean(json.dumps({'connected': ('sender_id="%s"' % self.sender_id)}))
        self.server.log_info('Line looks like:' + `line`)
        self.push(line)
        self.push(line)
            
    def handle_command (self, command):
        import types
        command_line = string.split(command)
        name = 'cmd_%s' % command_line[0]
        if hasattr (self, name):
                # make sure it's a method...
            method = getattr (self, name, None)
            if type(method) == type(self.handle_command):
                method (command_line[1:])
            else:
                self.push (clean(dumps(({'unknown command':' %s' % command_line[0]},))))
                
    def cmd_quit (self, args):
        self.server.push_line (self, dumps(({'message':('text="%s left"' % self.sender_id)},)))
        self.push (clean(dumps(({'message':' text="Goodbye!"'},))))
        self.close_when_done()
        
    # alias for '/quit' - '/q'
    cmd_q = cmd_quit
    
    def push_line (self, sender_id, line):
        self.push (clean(line))
        
    def handle_close (self):
        self.server.log_info('Sender %s closed connection' % self.sender_id)
        self.close()
        
    def close (self):
        del self.server.channels[self]
        asynchat.async_chat.close (self)
        
    def get_sender_id (self):
        if self.sender_id is not None:
            return self.sender_id
        else:
            return 'Unknown'

    def get_channel_id(self):
        if self.sender_id is not None:
            sep = self.sender_id.find(':')
            if sep > 0:
                return self.sender_id[:sep]
        return ''

class InstantXMLServer(asyncore.dispatcher):

    SERVER_IDENT = 'XML Chat Server (V%s)' % VERSION
    
    channel_class = xml_chat_channel
    
    spy = 0
    
    def __init__ (self, ip='', port=8518, ssecret=''):
        asyncore.dispatcher.__init__(self)
        self.port = port
        self.create_socket (socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind ((ip, port))
        self.log_info('InstantXML server started\n\tAddress: %s\n\tPort: %s' % (ip,port) )
        self.listen (5)
        self.channels = {}
        self.count = 0L
        self.ssecret = ssecret
        self.ping_thread = None  # if pings are requested by a client we'll set this up.
        self.push_lock = RLock()
        self.sserv = None

    def setSharedServer(self, sserv):
        self.sserv = sserv
        
    def handle_accept (self):
        conn, addr = self.accept()
        self.count = self.count + 1L
        self.log_info('Instant XML client #%ld - %s:%d' % (self.count, addr[0], addr[1]))
        self.channels[self.channel_class (self, conn, addr)] = 1
        
    def push_line (self, from_channel, values, target_id='', forward=True):
    
        #
        # push a packet to all clients in that channel. This could be more efficient for large numbers of clients.
        # That'll be version 2.
        #
        
        self.push_lock.acquire()
        line = dumps((values,))
        sender_id = from_channel.get_sender_id()
        if self.spy:
            if target_id:
                self.log_info('Instant XML transmit %s: %s\r\n for %s only' % (sender_id, line, target_id))
            else:
                self.log_info('Instant XML transmit %s: %s\r\n' % (sender_id, line))

        for c in self.channels.keys():
            if c is not from_channel:
                self.log_info('checking %s against %s' % (c.get_channel_id(), from_channel.get_channel_id()))
                if c.get_channel_id() == from_channel.get_channel_id():
                    if target_id:
                        #
                        # if there is a target_id, only send to that channel.
                        #
                        if c.sender_id == target_id:
                            c.push (clean(line))
                    else:
                        c.push (clean(line))
                        
        self.push_lock.release()
        
        if self.sserv and forward:
            self.sserv.sendMsg(from_channel, values, target_id, self)

    def setup_ping_thread(self, client):
        """
        establish the ping thread.
        """
        if not self.ping_thread:
            self.ping_thread = PingThread(self)
            self.ping_thread.start()
            
    def do_ping(self):
        self.push_lock.acquire()
        pingcount = 0
        for c in self.channels.keys():
            if c.needs_ping:
                pingcount += 1
                c.push(clean(dumps(({'message':'ping'},))))
                
        self.push_lock.release()
        
        if pingcount == 0:
            self.log_info('Ping count fell to zero... stopping ping thread.')
            self.ping_thread.pause()
            self.ping_thread = None

    def writable (self):
        return 0

class InstantJSONServer(asyncore.dispatcher):

    SERVER_IDENT = 'JSON Chat Server (V%s)' % VERSION
    
    channel_class = json_chat_channel
    
    spy = 0
    
    def __init__ (self, ip='', port=8519):
        asyncore.dispatcher.__init__(self)
        self.port = port
        self.create_socket (socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind ((ip, port))
        self.log_info('InstantJSON server started\n\tAddress: %s\n\tPort: %s' % (ip,port) )
        self.listen (5)
        self.channels = {}
        self.count = 0L
        self.ping_thread = None  # if pings are requested by a client we'll set this up.
        self.push_lock = RLock()
        self.sserv = None

    def setSharedServer(self, sserv):
        self.sserv = sserv
        
    def handle_accept (self):
        conn, addr = self.accept()
        self.count = self.count + 1L
        self.log_info('Instant JSON client #%ld - %s:%d' % (self.count, addr[0], addr[1]))
        self.channels[self.channel_class (self, conn, addr)] = 1
        
    def push_line (self, from_channel, values, target_id='', forward=True):
    
        #
        # push a packet to all clients in that channel. This could be more efficient for large numbers of clients.
        # That'll be version 2.
        #
        
        self.push_lock.acquire()
        line = json.dumps(values)
        sender_id = from_channel.get_sender_id()
        if self.spy:
            if target_id:
                self.log_info('Instant JSON transmit %s: %s\r\n for %s only' % (sender_id, line, target_id))
            else:
                self.log_info('Instant JSON transmit %s: %s\r\n' % (sender_id, line))

        for c in self.channels.keys():
            if c is not from_channel:
                self.log_info('checking %s against %s' % (c.get_channel_id(), from_channel.get_channel_id()))
                if c.get_channel_id() == from_channel.get_channel_id():
                    if target_id:
                        #
                        # if there is a target_id, only send to that channel.
                        #
                        if c.sender_id == target_id:
                            c.push (jsonclean(line))
                    else:
                        c.push (jsonclean(line))
                        
        self.push_lock.release()
        if self.sserv and forward:
            self.sserv.sendMsg(from_channel, values, target_id, self)
        
    def setup_ping_thread(self, client):
        """
        establish the ping thread.
        """
        if not self.ping_thread:
            self.ping_thread = PingThread(self)
            self.ping_thread.start()
            
    def do_ping(self):
        self.push_lock.acquire()
        pingcount = 0
        for c in self.channels.keys():
            if c.needs_ping:
                pingcount += 1
                c.push(clean(dumps(({'message':'ping'},))))
                
        self.push_lock.release()
        
        if pingcount == 0:
            self.log_info('Ping count fell to zero... stopping ping thread.')
            self.ping_thread.pause()
            self.ping_thread = None

    def writable (self):
        return 0

class SharedServers:

    def __init__(self):
        self.servers = []
        
    def addServer(self, server):
        self.servers.append(server)
        
    def sendMsg(self, from_channel, values, target_id='', server=''):
        for s in self.servers:
            if s != server:
                s.push_line( from_channel, values, target_id, forward=False)
                
if __name__ == '__main__':
    import sys

    ssecret = '' # default is no shared secret.
    
    if len(sys.argv) > 1:
        port = string.atoi (sys.argv[1])
    else:
        port = 8518

    if len(sys.argv) > 2:
        ssecret = sys.argv[2]
        
    s1 = InstantXMLServer('', port, ssecret)
    s2 = InstantJSONServer()
    
    sserv = SharedServers()
    sserv.addServer(s1)
    sserv.addServer(s2)
    
    s1.setSharedServer(sserv)
    s2.setSharedServer(sserv)
    
    asyncore.loop()
