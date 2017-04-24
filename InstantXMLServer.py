#!/usr/bin/env python
#
# Medusa Based XML server
#

RCS_ID = '$Id: InstantXMLServer.py,v 1.1.1.1 2006-08-27 10:06:30 steve Exp $'

import sys, string, os, socket, errno, struct
from StringIO import StringIO
import traceback

def getException():
    f = StringIO()
    traceback.print_exc(file=f)
    f.seek(0)
    return f.read()

import asyncore

import string

VERSION = string.split(RCS_ID,' ')[2]

PING_SLEEPTIME = 60  # maximum ping delay seconds

import socket
import asyncore
import asynchat

from xmlrpclib import loads, dumps, Boolean

from threading import RLock, Thread
from time import sleep

def clean(src):
    return src + '\0'

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
                sleep(self.client.ping_delay)  # the client may adjust the ping_delay depending on the configuration of the channels that need pings.
                self.client.do_ping()
            else:
                break
    
class chat_channel (asynchat.async_chat):

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
                        self.server.setup_ping_thread(self) # only set up pings if requested.
                        
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
                                self.server.push_line(self, xmlToSend, target_id)
                                
                if not sentValues:
                    self.server.push_line(self, xmlToSend)

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

    SERVER_IDENT = 'Chat Server (V%s)' % VERSION
    
    channel_class = chat_channel
    ping_delay = PING_SLEEPTIME
    
    spy = 0
    
    def __init__ (self, ip='', port=8518, ssecret=''):
        self.port = port
        asyncore.dispatcher.__init__(self)
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
        
    def handle_accept (self):
        conn, addr = self.accept()
        self.count = self.count + 1L
        self.log_info('Instant XML client #%ld - %s:%d' % (self.count, addr[0], addr[1]))
        self.channels[self.channel_class (self, conn, addr)] = 1
        
    def push_line (self, from_channel, line, target_id=''):
    
        #
        # push a packet to all clients in that channel. This could be more efficient for large numbers of clients.
        # That'll be version 2.
        #
        
        self.push_lock.acquire()
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
        
    def setup_ping_thread(self, client):
        """
        establish the ping thread.
        """
        if type(client.needs_ping) in [type(1.0), type(1)]:
            if self.ping_delay > client.needs_ping:
                self.ping_delay = client.needs_ping  # use client with minimum delay to set delay time
                                
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
            self.ping_delay = PING_SLEEPTIME

    def writable (self):
        return 0
        
if __name__ == '__main__':
    import sys

    ssecret = '' # default is no shared secret.
    
    if len(sys.argv) > 1:
        port = string.atoi (sys.argv[1])
    else:
        port = 8518

    if len(sys.argv) > 2:
        ssecret = sys.argv[2]
        
    s = InstantXMLServer('', port, ssecret)
    asyncore.loop()
