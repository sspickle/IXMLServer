#
# ServerThread runs an instance of InstantXMLServer in a thread
# so the rest of the app can keep on ticking... 
#

import sys
import string
from socket import *
from time import sleep
import asyncore


from threading import RLock, Thread
from InstantXMLServer import InstantXMLServer
#from InstantXMLJSONServer import InstantXMLServer, InstantJSONServer, SharedServers

DEFAULT_PORT=8518

class Server( Thread ):

    running = 0

    def __init__(self, port=DEFAULT_PORT, ssecret=''):
        Thread.__init__(self)
        
        self.s1 = InstantXMLServer('', port, ssecret)
        #self.s2 = InstantJSONServer()
    
        #self.sserv = SharedServers()
        #self.sserv.addServer(self.s1)
        #self.sserv.addServer(self.s2)
    
        #self.s1.setSharedServer(self.sserv)
        #self.s2.setSharedServer(self.sserv)
    
    def run(self):
        """
        Run the server
        """
        self.running = 1
        asyncore.loop()

