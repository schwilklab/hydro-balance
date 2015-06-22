#!/usr/bin/env python
# balance.py
"""Communicate with analytical balance.

See the config.ini file for settings.

`sbalance.py` supports two mode currently: a simple mass logging mode (with the
update interval set in the config file) or a mode which prints running averages
of flow rates used for measuring hydraulic conductance. Choose "mode = log" or
"mode = "hydro".

Code currently supports serial communication with Metler balances and with
Denver Instruments balances. Set the type as "model = Denver" or "model =
Metler" in the config file. Also make sure that the com port and baud rate are
set correctly in the config file. The code assumes 8-N-1 (8 data bits, no
parity bit and 1 stop bit) -- this may have to be set on the balance interface.
For example, our Metler analytical balance had different defaults and baud and
bit settings had to be set using the balance menus.

"""

__version__ = "1.6"

import sys, time
import logging, logging.handlers

from twisted.protocols.basic import LineReceiver
from twisted.internet import stdio, reactor
from twisted.internet.serialport import SerialPort
from twisted.internet.task import LoopingCall


# configuration file
from ConfigParser import SafeConfigParser
config = SafeConfigParser()
# defaults:
config.add_section('main')
config.set('main', 'mode', 'hydro')
config.set('main', 'model', 'Metler')
config.set('main', 'comport', '/dev/ttyS0')
config.set('main', 'baud', '9600')
config.set('main', 'update_interval', '5')

config.add_section('hydro')
config.set('hydro', 'flow_interval', '6') # multiplier of update measurement
                                         # interval for flow calculation
config.set('hydro', 'average_N', '4') # number of measurements for running
                                    # average calculation

# logging
balance_logger = logging.getLogger('balance_logger')
LOGFILE = time.strftime("%Y%m%d-%H%M%S") + "-balance.log"

loghandler = logging.FileHandler(LOGFILE)
screenhandler = logging.StreamHandler(sys.stdout)
loghandler.setFormatter(logging.Formatter('%(asctime)s\t%(message)s'))
screenhandler.setFormatter(logging.Formatter('%(asctime)s\t%(message)s'))
balance_logger.addHandler(loghandler)
balance_logger.addHandler(screenhandler)
balance_logger.setLevel(logging.INFO)

    
def movingAve(col,n):
    return (sum(col[-n:]) / float(n))

class serialProtDummy(LineReceiver):
    """Produce dummy output for testing"""
    def __init__(self, bal):
        self.bal = bal
        self.inc = 0

    def sendWeightRequest(self):
        self.inc = self.inc+1
        self.bal.valueReceived(self.inc)

    def stopProducing(self):
        self.inc=0


class serialProtDenver(LineReceiver):
    """Denver Instruments serial protocol"""
    def __init__(self, bal):
        self.bal = bal
        self.sendLine("SET SE OFF") # turn off echo for Denver balance

    def lineReceived(self, line):
        """Should be either a balance value or a time, Values in format: "1 +
        0.0000\r\n", time in format: "09:10:37\r\n" """

        if line[2] == ":" :
            self.bal.timeReceived(line)
        elif  line [2] == "+" or line[2] == "-" :
            try:
              sign = line[2] 
              v = line[3:].strip()
              val = float(v)
              if sign=="-" :  val = 0- val
              self.bal.valueReceived(val)
            except:
              balance_logger.warning("BAD LINE: %s" % line)  
        else:
            balance_logger.warning("BAD LINE: %s" % line)


    def sendWeightRequest(self):
        self.sendLine("DO PR") # Denver just prints out what is on screen, so
                               # units must be set on the balance itself

class serialProtMetler(LineReceiver):
    """Metler Toledo serial protocol (MT-SICS).

Weight Line in form: 'ID Status WeightValue Unit'

TODO: handle error and other line output forms
"""
    def __init__(self, bal):
        self.bal = bal
        #LineReceiver.__init__(self)

    def lineReceived(self, line):
        #print("LINE:" + line)
        (ID, Status, WeightValue, Unit) = line.split()

        try:
            #v = WeightValue.strip()
            val = float(WeightValue)
            if Unit == "g" :
                val = val*1000 # get in mg
            self.bal.valueReceived(val)
        except:
            balance_logger.warning("BAD LINE: %s" % line)

    def sendWeightRequest(self):
        self.sendLine("SI") # Metler appears to always report mass in g

class KeyboardInput(LineReceiver):
    """Class for checking for q state"""
    delimiter = '\n' # unix terminal style newlines. remove this line
                     # for use with Telnet
    def __init__(self,bal):
        self.bal = bal
        
    def connectionMade(self):
        balance_logger.debug("balance control")

    def lineReceived(self, line):
        """Keyboard commands"""
        self.clearLineBuffer()
        if line:
            if line == "q" : 
               reactor.stop()

class Balance():
    """Handles main program flow, can be subclassed for more specialized output
than raw weights (eg hydro mode)."""

    def __init__(self, serialProtocolType, port, baud, printInterval ):
        # give the protocol a hook back to the balance object so it can send data
        self.prot = serialProtocolType(self)
        self.printInterval = printInterval
        self.port = port
        self.baud = baud

    def stopReceiving(self):
        self.prot.stopProducing()

    def getWeight(self):
        self.prot.sendWeightRequest()

    def startReceiving(self):
        self.tag = raw_input('Enter a label: ')
        try :
            self.ser = SerialPort(self.prot, self.port, reactor, baudrate=self.baud)
        except :
            self.ser = None
            balance_logger.error("Could not connect to serial port %s at %d baud" % (self.port, self.baud))

        self.time = time.time()
        self.getWeightLoop = LoopingCall(self.getWeight)
        self.getWeightLoop.start(self.printInterval)

    def valueReceived(self,val):
        log_time = time.time() - self.time
        balance_logger.info("%s\t%.10f\t%.10f" % (self.tag, log_time, val))


class HydroFlow(Balance):
    """Class for hydraulic conductance measurements.  Does flow calculations.

    """

    def __init__(self, serialProtocolType, port, baud, printInterval, flowInterval, runningAverageN):
        Balance.__init__(self, serialProtocolType, port, baud, printInterval)
        self.values = [0,]
        self.times = [0,]
        self.flows = [0,]
        self.aveFlows =[0,]
        self.runningAverageN = runningAverageN
        self.interval = printInterval
        self.flowInterval = flowInterval

    def startReceiving(self):
        balance_logger.info("Starting receiving")
        balance_logger.info("Print Interval = %d, Flow interval = %d * %d = %d s, running average n = %d (%d s)" % 
                         (self.interval, self.interval, self.flowInterval, 
                          self.interval*self.flowInterval, self.runningAverageN, 
                          self.runningAverageN*self.interval*self.flowInterval))
        try :
            self.ser = SerialPort(self.prot, self.port, reactor, baudrate=self.baud) 
        except :
            self.ser = None
            balance_logger.error("Could not connect to serial port %s at %d baud" % (self.port, self.baud))

        self.getWeightLoop = LoopingCall(self.getWeight)
        self.getWeightLoop.start(self.interval)
        
    def valueReceived(self,val):
        ctime = time.time()
        self.flows.append( (val-self.values[-1]) / (ctime - self.times[-1]))
        self.values.append(val)
        self.times.append(ctime)
        fn = min(len(self.values), self.flowInterval)
        self.aveFlows.append( (self.values[-1] - self.values[-fn]) / (self.times[-1] - self.times[-fn]))
        n = min(len(self.aveFlows), self.runningAverageN)
        #print val
        balance_logger.info( "%.10f\t%.10f\t%.10f\t%.10f" % (self.values[-1], self.flows[-1], self.aveFlows[-1], movingAve(self.aveFlows, n )))


def main():
    """Command-line tool.  See balance.py -h for help.
    """

    from optparse import OptionParser
	
    usage = """
    usage: %prog [options]
    """

    parser = OptionParser(usage=usage, version ="%prog " + __version__)
    # parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False,
    # 				  help="Print INFO messages to stdout, default=%default")
    parser.add_option("-c", "--config", type="string", dest="configfile", default="config.ini",
                      help="Configuration file, default=%default")

    (options, args) = parser.parse_args()

    balance_logger.debug("Starting program")

    config.read(options.configfile)

    if config.get("main", "model") == "Metler" :
        serialProtType = serialProtMetler
    elif  config.get("main", "model") == "Denver" :
        serialProtType = serialProtDenver
    else :
        balance_logger.error("Unknown balance model: %s. Using dummy output for testing" 
                             % config.get("main", "model"))
        serialProtType = serialProtDummy

    port = config.get("main", "comport")
    baud = config.getint("main", "baud")
    printInterval = config.getint("main", "update_interval")

    if config.get("main", "mode") == "hydro" :
        theBalance = HydroFlow(serialProtType, port, baud, printInterval, 
                               config.getint("hydro", "flow_interval"), 
                               config.getint("hydro", "average_N"))
    else :
        theBalance = Balance(serialProtType, port, baud, printInterval)

    theBalance.startReceiving()
    stdio.StandardIO(KeyboardInput(theBalance))
    reactor.run()

    # and write the options to a file
    with open('config.ini', 'w') as f:
        config.write(f)
        
if __name__=="__main__":
    main()
    
