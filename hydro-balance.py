#!/usr/bin/env python
# balance.py
"""
Communicate with analytical balance and print running average of flow rates

Currently supports Denver Instruments balance and Metler balance
"""

__version__ = "1.5"

import sys, time
import logging, logging.handlers

from twisted.protocols.basic import LineReceiver
from twisted.internet import stdio, reactor
from twisted.internet.serialport import SerialPort
from twisted.internet.task import LoopingCall

comport = "/dev/ttyS0"
baud = 9600

balance_logger = logging.getLogger('balance_logger')
info_logger = logging.getLogger('info_logger')

LOGFILE = "balance-log.log"

loghandler = logging.FileHandler(LOGFILE)
loghandler.setFormatter(logging.Formatter('%(asctime)s: %(message)s'))
balance_logger.addHandler(loghandler)
balance_logger.setLevel(logging.INFO)

infohandler = logging.StreamHandler(sys.stdout)
infohandler.setFormatter(logging.Formatter('%(asctime)s: %(message)s'))
info_logger.addHandler(infohandler)
info_logger.setLevel(logging.DEBUG)
    
def movingAve(col,n):
    return (sum(col[-n:]) / float(n))

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
              info_logger.warning("BAD LINE: %s" % line)  
        else:
            info_logger.warning("BAD LINE: %s" % line)


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
            info_logger.warning("BAD LINE: %s" % line)

    def sendWeightRequest(self):
        self.sendLine("SI") # Metler appears to always report mass in g

class KeyboardInput(LineReceiver):
    delimiter = '\n' # unix terminal style newlines. remove this line
                     # for use with Telnet
    def __init__(self,bal):
        self.bal = bal
        #LineReceiver.__init__()
        
    def connectionMade(self):
        info_logger.debug("balance control")

    def lineReceived(self, line):
        """Keyboard commands"""
        if line:
            if line == "q" : reactor.stop()
            elif line == "c" : self.bal.startReceiving()

class HydroFlow():
    """Class to handle main program flow. Keyboard input, balance input, and flow
calculations.

    """

    def __init__(self, serialProtocolType, interval, flowInterval, runningAverageN):
        self.prot = serialProtocolType(self)
        self.values = [0,]
        self.times = [0,]
        self.flows = [0,]
        self.aveFlows =[0,]
        self.runningAverageN = runningAverageN
        self.interval = interval
        self.flowInterval = flowInterval

    def startReceiving(self, port = comport):
        info_logger.info("Starting receiving")
        info_logger.info("Print Interval = %d, Flow interval = %d * %d = %d s, running average n = %d (%d s)" % 
                         (self.interval, self.interval, self.flowInterval, self.interval*self.flowInterval, self.runningAverageN, self.runningAverageN*self.interval*self.flowInterval))
        self.ser = SerialPort(self.prot, port, reactor, baudrate=baud) 
        self.printInterval = LoopingCall(self.getWeight)
        self.printInterval.start(self.interval)     
        
    def stopReceiving(self):
        self.prot.stopProducing()

    def getWeight(self):
        self.prot.sendWeightRequest()

    def valueReceived(self,val):
        ctime = time.time()
        self.flows.append( (val-self.values[-1]) / (ctime - self.times[-1]))
        self.values.append(val)
        self.times.append(ctime)
        fn = min(len(self.values), self.flowInterval)
        self.aveFlows.append( (self.values[-1] - self.values[-fn]) / (self.times[-1] - self.times[-fn]))
        n = min(len(self.aveFlows), self.runningAverageN)
        #print val
        info_logger.info( "%.10f\t%.10f\t%.10f\t%.10f" % (self.values[-1], self.flows[-1], self.aveFlows[-1], movingAve(self.aveFlows, n )))


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
    parser.add_option("-i", "--interval", type="int", dest="interval", default=5,
                      help="Set measurement interval for flow calculation, default=%default")
    parser.add_option("-f", "--flowinterval", type="int", dest="flowInterval", default=6,
                      help="Set measurement interval for flow calculation, default=%default")
    parser.add_option("-a", "--average", type="int", dest="averageN", default=4,
                      help="Set number of measurements for running average calculation, default=%default")
    parser.add_option("-b", "--balance", type="string", dest="model", default="Metler",
					  help="Set balance model. ('Metler' or 'Denver'), default=%default")
                                          

    (options, args) = parser.parse_args()

    info_logger.debug("Starting program")


    if options.model == "Metler" :
        serialProtType = serialProtMetler
    elif options.model == "Denver" :
        serialProtType = serialProtDenver
    else :
        info_logger.error("Unknown balance model: %s" % options.model)

    theHydroFlow = HydroFlow(serialProtType, options.interval, 
                             options.flowInterval, options.averageN)
    theHydroFlow.startReceiving()
    stdio.StandardIO(KeyboardInput(theHydroFlow))
    reactor.run()
        
if __name__=="__main__":
    main()
    
