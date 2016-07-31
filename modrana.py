#!/usr/bin/env python
# -*- coding: utf-8 -*-
#----------------------------------------------------------------------------
# modRana main GUI.  Displays maps & much more, for use on a mobile device.
#
# Controls:
# Start by clicking on the main menu icon.
#----------------------------------------------------------------------------
# Copyright 2007-2008, Oliver White
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#----------------------------------------------------------------------------
import subprocess
import sys
import time

startTimestamp = time.time()
import os
import marshal
import imp
import platform

# initialize logging
from core import modrana_log
from core.signal import Signal
modrana_log.init_logging()
import logging
log = logging.getLogger("")

# qrc handling
from core import qrc
USING_QRC = qrc.is_qrc
qrc.handle_qrc()

def setCorrectCWD():
    # change to folder where the main modRana file is located
    # * this enables to run modRana with absolute path without adverse
    # effect such as modRana not finding modules or
    currentAbsolutePath = os.path.dirname(os.path.abspath(__file__))
    if USING_QRC:
        # we are running from qrc, so just use the qrc:/ prefix as CWD,
        # no need to chdir
        currentAbsolutePath = "qrc:/"
    else:
        os.chdir(currentAbsolutePath)
    # append the path to the bundle directory so that modRana can fall-back
    # to the it's bundled modules if a given module is not available on the system
    # - at the same just a simple "import foo" import is enough and
    #   "from core.bundle import foo" is not needed
    sys.path.append(os.path.join(currentAbsolutePath, 'core', 'bundle'))
    # do the same thing for the backports folder, which serves a similar role
    # as the bundle folder (TODO: merge content of backports to bundle ?)
    sys.path.append(os.path.join(currentAbsolutePath, 'core', 'backports'))
    #sys.path.append(os.path.join('core', 'bundle'))
    #sys.path.append(os.path.join("qrc:/", 'core', 'bundle'))
    # add the modules folder to path, so that third-party modules (such as Upoints),
    # that expect to be placed to path work correctly
    # NOTE: most of those modules were moved to the core/bundle
    # directory so it might be possible to get rid of this in the
    # future
    sys.path.append(os.path.join(currentAbsolutePath, 'modules'))
    sys.path.append(os.path.join(currentAbsolutePath, 'modules/device_modules'))
    sys.path.append(os.path.join(currentAbsolutePath, 'modules/gui_modules'))

# before we start importing our stuff we need to correctly setup CWD
# and Python import paths
setCorrectCWD()

# import core modules/classes
from core import startup
from core import utils
from core import paths
from core import configs
from core import threads
from core import gs
from core import singleton
from core.backports import six
# record that imports-done timestamp
importsDoneTimestamp = time.time()

MAIN_MODULES_FOLDER = 'modules'
DEVICE_MODULES_FOLDER = os.path.join(MAIN_MODULES_FOLDER, "device_modules")
GUI_MODULES_FOLDER = os.path.join(MAIN_MODULES_FOLDER, "gui_modules")
ALL_MODULE_FOLDERS = [
    MAIN_MODULES_FOLDER,
    DEVICE_MODULES_FOLDER,
    GUI_MODULES_FOLDER
]


class ModRana(object):
    """
    This is THE main modRana class.
    """

    def __init__(self):
        singleton.modrana = self

        self.timing = []
        self.addCustomTime("modRana start", startTimestamp)
        self.addCustomTime("imports done", importsDoneTimestamp)

        # constants & variable initialization
        self.dmod = None # device specific module
        self.gui = None
        self.GUIString = ""
        self.optLoadingOK = None

        self.d = {} # persistent dictionary of data
        self.m = {} # dictionary of loaded modules
        self.watches = {} # List of data change watches
        self.maxWatchId = 0

        self.initInfo = {
            'modrana': self,
            'device': None, # TODO: do this directly
            'name': ""
        }

        # signals
        self.notificationTriggered = Signal()
        self.shutdown_signal = Signal()

        self.mapRotationAngle = 0 # in radians
        self.notMovingSpeed = 1 # in m/s

        # per mode options
        # NOTE: this variable is automatically saved by the
        # options module
        self.keyModifiers = {}

        # initialize threading
        threads.initThreading()

        # start timing modRana launch
        self.addTime("GUI creation")

        # add the startup handling core module
        self.startup = startup.Startup(self)
        self.args = self.startup.getArgs()

        # handle any early tasks specified from CLI
        self.startup.handleEarlyTasks()

        # early CLI tasks might need a "silent" modRana
        # so the startup announcement is here
        log.info(" == modRana Starting == ")
        # load the version string (needs to be done here
        # as PWD might change after the paths module is
        # imported, for example when running
        # with the Qt 5 GUI)
        paths.loadVersionString()
        version = paths.VERSION_STRING
        if version is None:
            version = "unknown version"
        log.info("  %s" % version)
        log.info("  Python %s" % platform.python_version())

        # load the device module now as it might override
        # the default profile directory, so it needs to be
        # before ve init the core paths module
        self._loadDeviceModule()

        # initialize the paths handling core module
        self.paths = paths.Paths(self)

        # add the configs handling core module
        self.configs = configs.Configs(configs_dir=self.paths.getProfilePath())

        # load persistent options
        self.optLoadingOK = self._loadOptions()
        self._optionsLoaded()

        # check if upgrade took place

        if self.optLoadingOK:
            savedVersionString = self.get('modRanaVersionString', "")
            versionStringFromFile = paths.VERSION_STRING
            if savedVersionString != versionStringFromFile:
                log.info("possible upgrade detected")
                self._postUpgradeCheck()

        # save current version string
        self.set('modRanaVersionString', paths.VERSION_STRING)

        # load all configuration files
        self.configs.load_all()

        # start loading other modules

        # handle tasks that require the device
        # module but not GUI
        self.startup.handleNonGUITasks()

        # then the GUI module
        self._loadGUIModule()

        # and all other modules
        self._loadModules()

        # startup done, log some statistics
        self._startupDone()

    def _postUpgradeCheck(self):
        """
        perform post upgrade checks
        """
        self.configs.upgrade_config_files()

    ##  MODULE HANDLING ##

    def _loadDeviceModule(self):
        """Load the device module"""
        if self.dmod: # don't reload the module
            return

        # get the device module string
        # (a unique device module string identificator)
        if self.args.d:
            device = self.args.d
        else: # no device specified from CLI
            # try to auto-detect the current device
            from core import platform_detection

            device = platform_detection.getBestDeviceModuleId()

        device = device.lower() # convert to lowercase

        self.initInfo["device"] = device

        # get GUI ID from the CLI argument
        if self.args.u:
            try:
                self.GUIString = self.args.u.split(":")[0].upper()
            except Exception:
                log.exception('splitting the GUI string failed')
        else: # no ID specified
            # the N900 device module needs the GUIString
            # at startup
            if device == "n900":
                self.GUIString = "GTK"

        # set the pre-import-visible GUIString
        # for the device module
        gs.GUIString = self.GUIString

        ## load the device specific module

        # NOTE: other modules need the device and GUI modules
        # during init
        deviceModulesPath = os.path.join(MAIN_MODULES_FOLDER, "device_modules")
        sys.path.append(deviceModulesPath)
        dmod_instance = self._loadModule("device_%s" % device, "device")
        if dmod_instance is None:
            log.critical("!! device module failed to load !!\n"
                         "loading the Neo device module as fail-safe")
            device = "neo"
            dmod_instance = self._loadModule("device_%s" % device, "device")
        self.dmod = dmod_instance

        # if no GUIString was specified from CLI,
        # get preferred GUI module strings from the device module

        if self.GUIString == "":
            ids = self.dmod.getSupportedGUIModuleIds()
            if ids:
                self.GUIString = ids[0]
            else:
                self.GUIString = "GTK" # fallback
                # export the GUI string
                # set the pre-import visible GUI string and subtype
        splitGUIString = self.GUIString.split(":")
        gs.GUIString = splitGUIString[0]
        if len(splitGUIString) >= 2:
            gs.GUISubtypeString = splitGUIString[1]

            # TODO: if loading GUI module fails, retry other modules in
            # order of preference as provided by the  device module

    def _loadGUIModule(self):
        """load the GUI module"""

        # add the GUI module folder to path
        GUIModulesPath = os.path.join(MAIN_MODULES_FOLDER, "gui_modules")
        sys.path.append(GUIModulesPath)
        gui = None
        splitGUIString = self.GUIString.split(":")

        GUIModuleId = splitGUIString[0]
        if len(splitGUIString) > 1:
            subtypeId = splitGUIString[1]
        else:
            subtypeId = None

        if GUIModuleId == "GTK":
            gui = self._loadModule("gui_gtk", "gui")
        elif GUIModuleId == "QML":
            gui = self._loadModule("gui_qml", "gui")
        elif GUIModuleId == "QT5":
            gui = self._loadModule("gui_qt5", "gui")

        # make device module available to the GUI module
        if gui:
            gui.setSubtypeId(subtypeId)
            gui.dmod = self.dmod
        self.gui = gui

    def _loadModules(self):
        """load all "normal" (other than device & GUI) modules"""

        log.info("importing modules:")
        start = time.clock()

        # make shortcut for the loadModule function
        loadModule = self._loadModule

        # get possible module names
        moduleNames = self._getModuleNamesFromFolder(MAIN_MODULES_FOLDER)
        # load if possible
        for moduleName in moduleNames:
            # filter out .py
            moduleName = moduleName.split('.')[0]
            loadModule(moduleName, moduleName[4:])

        log.info("Loaded all modules in %1.2f ms, initialising" % (1000 * (time.clock() - start)))
        self.addTime("all modules loaded")

        # make sure all modules have the device module and other variables before first time
        for m in self.m.values():
            m.modrana = self # make this class accessible from modules
            m.dmod = self.dmod

            # run what needs to be done before firstTime is called
        self._modulesLoadedPreFirstTime()

        start = time.clock()
        for m in self.m.values():
            m.firstTime()

        # run what needs to be done after firstTime is called
        self._modulesLoadedPostFirstTime()

        log.info( "Initialization complete in %1.2f ms" % (1000 * (time.clock() - start)) )

        # add last timing checkpoint
        self.addTime("all modules initialized")

    def _getModuleNamesFromFolder(self, folder, prefix='mod_'):
        """list a given folder and find all possible module names
        Module names:
        Module names start with the "mod_" and don't end with .pyc or .pyo.
        Consequences:
        Valid modules need to have an existing .py file or be folder-modules
        (don't name a folder module mod_foo.pyc :) ), even if they are
        actually loaded from the .pyc or .pyo in the end.
        This is done so that dangling .pyc/.pyo file from a module
        that was removed are not loaded by mistake.
        This situation shouldn't really happen if modRana is installed from a package,
        as all .pyc files are purged during package upgrade and regenerated."""
        if USING_QRC:
            # if we are running from qrc, we need to use the pyotherside function for enumerating
            # the modules stored in the qrc "bundle"
            import pyotherside 
            moduleNames = filter(
                lambda x: x[0:len(prefix)] == prefix, pyotherside.qrc_list_dir(os.path.join("/", folder))
            )
        else:
            moduleNames = filter(
                lambda x: x[0:len(prefix)] == prefix, os.listdir(folder)
            )

        # remove the extension
        moduleNames = map(lambda x: os.path.splitext(x)[0], moduleNames)
        # return a set of unique module names
        # * like this, two module names will not be returned if there are
        # both py and pyc files
        return set(moduleNames)

    def _listAvailableDeviceModulesByID(self):
        moduleNames = self._getModuleNamesFromFolder(DEVICE_MODULES_FOLDER, prefix='device_')
        # remove the device_ prefix and return the results
        # NOTE: .py, .pyc & .pyo should be removed already in _getModuleNamesFromFolder()
        # also sort the module names alphabetically
        return sorted(map(lambda x: x[7:], moduleNames))

    def _listAvailableGUIModulesByID(self):
        return self._getModuleNamesFromFolder(GUI_MODULES_FOLDER)

    def _loadModule(self, importName, moduleName):
        """load a single module by name from path"""
        startM = time.clock()
        fp = None
        try:
            if USING_QRC:
                # we need to use importlib for importing modules from qrc,
                # the "old" imp modules seems to be unable to do that
                import importlib
                a = importlib.import_module(importName)
            else:
                fp, pathName, description = imp.find_module(importName, ALL_MODULE_FOLDERS)
                a = imp.load_module(importName, fp, pathName, description)

            module = a.getModule(self, moduleName, importName)
            self.m[moduleName] = module
            log.info(" * %s: %s (%1.2f ms)",
                     moduleName,
                     self.m[moduleName].__doc__,
                     (1000 * (time.clock() - startM))
            )
            return module
        except Exception:
            log.exception("module: %s/%s failed to load", importName, moduleName)
            return None
        finally:
            if fp:
                fp.close()

    def _optionsLoaded(self):
        """This is run after the persistent options dictionary is
        loaded from storage
        """
        # tell the log manager what where it should store log files
        modrana_log.log_manager.log_folder_path = self.paths.getLogFolderPath()

        # check if logging to file should be enabled
        if self.get('loggingStatus', False):
            logCompression = self.get('compressLogFile', False)
            modrana_log.log_manager.enable_log_file(compression=logCompression)
        else:
            modrana_log.log_manager.clear_early_log()
            # tell log manager log file is not needed and that it should
            # purge early log messages it is storing in case file log is enabled

        # add a watch on the loggingStatus key, so that log file can be enabled
        # and disabled at runtime with immediate effect
        self.watch("loggingStatus", self._logFileCB)

    def _logFileCB(self, _key, _oldValue, newValue):
        """Convenience function turning the log file on or off"""
        if newValue:
            logCompression = self.get('compressLogFile', False)
            modrana_log.log_manager.enable_log_file(compression=logCompression)
        else:
            modrana_log.log_manager.disable_log_file()

    def _modulesLoadedPreFirstTime(self):
        """this is run after all the modules have been loaded,
        but before their first time is called"""

        # and mode change
        self.watch('mode', self._modeChangedCB)
        # cache key modifiers
        self.keyModifiers = self.d.get('keyModifiers', {})
        # check if own Quit button is needed
        if self.gui.showQuitButton():
            menus = self.m.get('menu', None)
            if menus:
                menus.addItem('main', 'Quit', 'quit', 'menu:askQuit')

    def _modulesLoadedPostFirstTime(self):
        """this is run after all the modules have been loaded,
        after before their first time is called"""

        # check if redrawing time should be logged
        if 'showRedrawTime' in self.d and self.d['showRedrawTime'] == True:
            self.showRedrawTime = True

        # run any tasks specified by CLI arguments
        self.startup.handlePostFirstTimeTasks()


    def getModule(self, name, default=None):
        """
        return a given module instance, return default if no instance
        with given name is found
        """
        return self.m.get(name, default)

    def getModules(self):
        """
        return the dictionary of all loaded modules
        """
        return self.m

    ## STARTUP AND SHUTDOWN ##

    def _startupDone(self):
        """called when startup has been finished"""

        # report startup time
        self.reportStartupTime()

        # check if loading options failed
        if self.optLoadingOK:
            self.gui.notify("Loading saved options failed", 7000)

        # start the mainloop or equivalent
        self.gui.startMainLoop()

    def shutdown(self):
        """
        start shutdown cleanup and stop GUI main loop
        when finished
        """
        start_timestamp = time.clock()
        log.info("Shutting-down modules")
        for m in self.m.values():
            m.shutdown()
        # trigger the shudown signal
        self.shutdown_signal()
        self._saveOptions()
        modrana_log.log_manager.disable_log_file()
        log.info("Shutdown complete (%s)" % utils.get_elapsed_time_string(start_timestamp))


    ## OPTIONS SETTING AND WATCHING ##

    def get(self, name, default=None, mode=None):
        """Get an item of data"""

        # check if the value depends on current mode
        if name in self.keyModifiers.keys():
            # get the current mode
            if mode is None:
                mode = self.d.get('mode', 'car')
            if mode in self.keyModifiers[name]['modes'].keys():
                # get the dictionary with per mode values
                multiDict = self.d.get('%s#multi' % name, {})
                # return the value for current mode
                return multiDict.get(mode, default)
            else:
                return self.d.get(name, default)

        else: # just return the normal value
            return self.d.get(name, default)

    def set(self, name, value, save=False, mode=None):
        """Set an item of data,
        if there is a watch set for this key,
        notify the watcher that its value has changed"""

        oldValue = self.get(name, value)

        if name in self.keyModifiers.keys():
            # get the current mode
            if mode is None:
                mode = self.d.get('mode', 'car')
                # check if there is a modifier for the current mode
            if mode in self.keyModifiers[name]['modes'].keys():
                # save it to the name + #multi key under the mode key
                try:
                    self.d['%s#multi' % name][mode] = value
                except KeyError: # key not yet created
                    self.d['%s#multi' % name] = {mode: value}
            else: # just save to the key as usual
                self.d[name] = value
        else: # just save to the key as usual
            self.d[name] = value

        self._notifyWatcher(name, oldValue)
        # options are normally saved on shutdown,
        # but for some data we want to make sure they are stored and not
        # lost for example because of power outage/empty battery, etc.
        if save:
            options = self.m.get('options')
            if options:
                options.save()

    def optionsKeyExists(self, key):
        """Report if a given key exists"""
        return key in self.d.keys()

    def purgeKey(self, key):
        """remove a key from the persistent dictionary,
        including possible key modifiers and alternate values"""
        if key in self.d:
            oldValue = self.get(key, None)
            del self.d[key]
            # purge any key modifiers
            if key in self.keyModifiers.keys():
                del self.keyModifiers[key]
                # also remove the possibly present
                # alternative states for different modes"""
                multiKey = "%s#multi" % key
                if multiKey in self.d:
                    del self.d[multiKey]
            self._notifyWatcher(key, oldValue)
            return True
        else:
            log.error("can't purge a not-present key: %s", key)

    def watch(self, key, callback, args=None, runNow=False):
        """add a callback on an options key
        callback will get:
        key, newValue, oldValue, *args

        NOTE: watch ids should be >0, so that they evaluate as True
        """
        if not args: args = []
        nrId = self.maxWatchId + 1
        id = "%d_%s" % (nrId, key)
        self.maxWatchId = nrId # TODO: recycle ids ? (alla PID)
        if key not in self.watches:
            self.watches[key] = [] # create the initial list
        self.watches[key].append((id, callback, args))
        # should we now run the callback one ?
        # -> this is useful for modules that configure
        # themselves according to an options value at startup
        if runNow:
            currentValue = self.get(key, None)
            callback(key, currentValue, currentValue, *args)
        return id

    def removeWatch(self, id):
        """remove watch specified by the given watch id"""
        (nrId, key) = id.split('_')
        if key in self.watches:
            remove = lambda x: x[0] == id
            self.watches[key][:] = [x for x in self.watches[key] if not remove(x)]
        log.error("can't remove watch - key does not exist, watchId: %s", id)

    def _notifyWatcher(self, key, oldValue):
        """run callbacks registered on an options key
        HOW IT WORKS
        * the watcher is notified before the key is written to the persistent
        dictionary, so that it can react before the change is visible
        * the watcher gets the key and both the new and old values
        """
        callbacks = self.watches.get(key, None)
        if callbacks:
            for item in callbacks:
                (id, callback, args) = item
                # rather supply the old value than None
                newValue = self.get(key, oldValue)
                if callback:
                    if callback(key, oldValue, newValue, *args) == False:
                        # remove watches that return False
                        self.removeWatch(id)
                else:
                    log.error("invalid watcher callback :", callback)

    def addKeyModifier(self, key, modifier=None, mode=None, copyInitialValue=True):
        """add a key modifier
        NOTE: currently only used to make value of some keys
        dependent on the current mode"""
        options = self.m.get('options', None)
        # remember the old value, if not se use default from options
        # if available
        if options:
            defaultValue = options.getKeyDefault(key, None)
        else:
            defaultValue = None
        oldValue = self.get(key, defaultValue)
        if mode is None:
            mode = self.d.get('mode', 'car')
        if key not in self.keyModifiers.keys(): # initialize
            self.keyModifiers[key] = {'modes': {mode: modifier}}
        else:
            self.keyModifiers[key]['modes'][mode] = modifier

        # make sure the multi mode dictionary exists
        multiKey = '%s#multi' % key
        multiDict = self.d.get(multiKey, {})
        self.d[multiKey] = multiDict

        # if the modifier is set for the first time,
        # do we copy the value from the normal key or not ?
        if copyInitialValue:
            # check if the key is unset for this mode
            if mode not in multiDict:
                # set for first time, copy value
                self.set(key, self.d.get(key, defaultValue), mode=mode)
                # notify watchers
        self._notifyWatcher(key, oldValue)

    def removeKeyModifier(self, key, mode=None):
        """remove key modifier
        NOTE: currently this just makes the key independent
        on the current mode"""
        # if no mode is provided, use the current one
        if mode is None:
            mode = self.d.get('mode', 'car')
        if key in self.keyModifiers.keys():
            # just remove the key modifier preserving the alternative values
            if mode in self.keyModifiers[key]['modes'].keys():
                # get the previous value
                options = self.m.get('options', None)
                # remember the old value, if not se use default from options
                # if available
                if options:
                    defaultValue = options.getKeyDefault(key, None)
                else:
                    defaultValue = None
                oldValue = self.get(key, defaultValue)
                del self.keyModifiers[key]['modes'][mode]
                # was this the last key ?
                if len(self.keyModifiers[key]['modes']) == 0:
                    # no modes registered - unregister from modifiers
                    # TODO: handle non-mode modifiers in the future
                    del self.keyModifiers[key]
                    # notify watchers
                self._notifyWatcher(key, oldValue)
                # done
                return True
            else:
                log.error("can't remove modifier that is not present")
                log.error("key: %s, mode: %s", key, mode)
                return False
        else:
            log.error("key %s has no modifier and thus cannot be removed", key)
            return False

    def hasKeyModifier(self, key):
        """return if a key has a key modifier"""
        return key in self.keyModifiers.keys()

    def hasKeyModifierInMode(self, key, mode=None):
        """return if a key has a key modifier"""
        if mode is None:
            mode = self.d.get('mode', 'car')
        if key in self.keyModifiers.keys():
            return mode in self.keyModifiers[key]['modes'].keys()
        else:
            return False

    def notify(self, message, msTimeout=0, icon=""):
        log.info("modRana notify: %s", message)
        # trigger the notification signal - this will
        # trigger an actual notification by one of the
        # notification systems connected to the notification
        # signal (if any)
        self.notificationTriggered(message, msTimeout, icon)


        # notify = self.m.get('notification')
        # if notify:
        #     # the notification module counts timeout in seconds
        #     sTimeout = msTimeout / 1000.0
        #     notify.handleNotification(message, sTimeout, icon)

    def sendMessage(self, message):
        m = self.m.get("messages", None)
        if m is not None:
            log.info("Sending message: " + message)
            m.routeMessage(message)
        else:
            log.error("No message handler, can't send message.")


    def getModes(self):
        """return supported modes"""
        modes = {
            'cycle': 'Cycle',
            'walk': 'Foot',
            'car': 'Car',
            'train': 'Train',
            'bus': 'Bus',
        }
        return modes

    def getModeLabel(self, modeName):
        """get a label for a given mode"""
        try:
            return self.getModes()[modeName]
        except KeyError:
            log.error('mode %s does not exist and thus has no label' % modeName)
            return None

    def _modeChangedCB(self, key=None, oldMode=None, newMode=None):
        """handle mode change in regards to key modifiers and option key watchers"""
        # get keys that have both a key modifier and a watcher
        keys = filter(lambda x: x in self.keyModifiers.keys(), self.watches.keys())
        # filter out only those keys that have a modifier for the new mode
        # or had a modifier in the previous mode
        # otherwise their value would not change and thus
        # triggering a watch is not necessary
        keys = filter(
            lambda x: newMode in self.keyModifiers[x]['modes'].keys() or oldMode in self.keyModifiers[x][
                'modes'].keys(),
            keys)
        for key in keys:
            # try to get some value if the old value is not available
            options = self.m.get('options', None)
            # remember the old value, if not se use default from options
            # if available
            if options:
                defaultValue = options.getKeyDefault(key, None)
            else:
                defaultValue = None
            oldValue = self.get(key, defaultValue)
            # notify watchers
            self._notifyWatcher(key, oldValue)


    def _removeNonPersistentOptions(self, inputDict):
        """keys that begin with # are not saved
        (as they mostly contain data that is either time sensitive or is
        reloaded on startup)
        ASSUMPTION: keys are strings of length>=1"""
        try:
            return dict((k, v) for k, v in six.iteritems(inputDict) if k[0] != '#')
        except Exception:
            log.exception('options: error while filtering options\nsome nonpersistent keys might have been left in\nNOTE: keys should be strings of length>=1')
            return self.d

    def _saveOptions(self):
        """save the persistent dictionary to file"""
        log.info("saving options")
        try:
            f = open(self.paths.getOptionsFilePath(), "wb")
            # remove keys marked as nonpersistent
            self.d['keyModifiers'] = self.keyModifiers
            d = self._removeNonPersistentOptions(self.d)
            marshal.dump(d, f, 2)
            f.close()
            log.info("options successfully saved")
        except IOError:
            log.exception("can't save options")
        except Exception:
            log.exception("saving options failed")

    def _loadOptions(self):
        """load the persistent dictionary from file"""
        log.info("loading options")
        try:
            f = open(self.paths.getOptionsFilePath(), "rb")
            newData = marshal.load(f)
            f.close()
            purgeKeys = ["fix"]
            for key in purgeKeys:
                if key in newData:
                    del newData[key]
            for k, v in newData.items():
                self.set(k, v)
            success = True
            #print("Options content")
            #for key, value in newData.iteritems():
            #    print(key, value)


        except Exception:
            e = sys.exc_info()[1]
            log.exception("exception while loading saved options")
            #TODO: a yes/no dialog for clearing (renaming with timestamp :) the corrupted options file (options.bin)
            success = False

        self.overrideOptions()
        return success

    def overrideOptions(self):
        """
        without this, there would not be any projection values at start,
        because modRana does not know, what part of the map to show
        """
        self.set('centred', True) # set centering to True at start to get setView to run
        self.set('editBatchMenuActive', False)

    ## PROFILE PATH ##

    def getProfilePath(self):
        """return the profile folder (create it if it does not exist)
        NOTE: this function is provided here in the main class as some
        ordinary modRana modules need to know the profile folder path before the
        option module that normally handles it is fully initialized
        (for example the config module might need to copy default
        configuration files to the profile folder in its init)
        """
        # get the path
        modRanaProfileFolderName = '.modrana'
        userHomePath = os.getenv("HOME", "")
        profileFolderPath = os.path.join(userHomePath, modRanaProfileFolderName)
        # make sure it exists
        utils.createFolderPath(profileFolderPath)
        # return it
        return profileFolderPath

    ## STARTUP TIMING ##

    def addTime(self, message):
        timestamp = time.time()
        self.timing.append((message, timestamp))
        return timestamp

    def addCustomTime(self, message, timestamp):
        self.timing.append((message, timestamp))
        return timestamp

    def reportStartupTime(self):
        if self.timing:
            log.info("** modRana startup timing **")

            # log device identificator and name
            if self.dmod:
                deviceName = self.dmod.getDeviceName()
                deviceString = self.dmod.getDeviceIDString()
                log.info("# device: %s (%s)" % (deviceName, deviceString))

            tl = self.timing
            startupTime = tl[0][1] * 1000
            lastTime = startupTime
            totalTime = (tl[-1][1] * 1000) - startupTime
            for i in tl:
                (message, t) = i
                t *= 1000# convert to ms
                timeSpent = t - lastTime
                timeSinceStart = t - startupTime
                log.info("* %s (%1.0f ms), %1.0f/%1.0f ms", message, timeSpent, timeSinceStart, totalTime)
                lastTime = t
            log.info("** whole startup: %1.0f ms **" % totalTime)
        else:
            log.info("* timing list empty *")

modrana = None
dmod = None
gui = None
def start(argv=None):
    """This function is used when starting modRana with PyOtherSide.
    When modRana is started from PyOtherSide there is no sys.argv,
    so QML needs to pass it from its side.

    :param list argv: arguments the program got on cli or arguments
                      injected by QML
    """
    if not argv: argv = []
    # only assign fake values to argv if argv is empty or missing,
    # so that real command line arguments are not overwritten
    if not hasattr(sys, "argv") or not isinstance(sys.argv, list) or not sys.argv:
        log.debug("argv from QML:\n%s", argv)
        sys.argv = ["modrana.py"]
    # only log full argv if it was extended
    if argv:
        sys.argv.extend(argv)
        log.debug("full argv:\n%s", sys.argv)

    global modrana
    global dmod
    global gui
    modrana = ModRana()
    dmod = modrana.dmod
    gui = modrana.gui

if __name__ == "__main__":
    # check if reload has been requested
    reloadArg = "--reload"
    if len(sys.argv) >= 3 and sys.argv[1] == reloadArg:
        # following argument is path to the modRana main class we want to reload to,
        # optionally followed by any argument for the main class
        log.info(" == modRana Reloading == ")
        reloadPath = sys.argv[2]
        callArgs = [reloadPath]
        callArgs.extend(sys.argv[3:])
        subprocess.call(callArgs)
    else:
        start()


