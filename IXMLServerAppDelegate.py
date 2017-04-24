#
#  IXMLServerAppDelegate.py
#  IXMLServer
#

from Foundation import *
from Cocoa import *

from ServerThread import Server

class IXMLServerAppDelegate(NSObject):

    def applicationDidFinishLaunching_(self, aNotification):
        self.server = Server()
        self.server.start()
