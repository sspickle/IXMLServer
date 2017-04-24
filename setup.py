"""
Script for building the example:

Usage:
    python setup.py py2app
"""
from distutils.core import setup
import py2app

infoPlist = dict(
    CFBundleName = "IXMLServer",
    CFBundleVersion = "1.11",
    CFBundleGetInfoString = "IXML Server $Revision $, Copyright 2012 Silicon Prairie Ventures Inc.",
    NSHumanReadableCopyright = "Copyright 2012 Silicon Prairie Ventures Inc.")

setup(
    name="IXML Server",
    app=["IXMLServer.py"],
    data_files=["English.lproj"],
    options=dict(py2app=dict(
        plist=infoPlist,
        )
    )
)
