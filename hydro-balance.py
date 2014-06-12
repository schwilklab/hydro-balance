#!/usr/bin/env python
# balance.py
"""
Communicate with Denver Instruments balance
"""

__version__ = "1.4"

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
        #LineReceiver.__init__(self)

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


class inputProtocol(LineReceiver):
    delimiter = '\n' # unix terminal style newlines. remove this line
                     # for use with Telnet
    def __init__(self,bal):
            self.bal = bal
        #LineReceiver.__init__()
        
    def connectionMade(self):
        info_logger.debug("balance control")

    def lineReceived(self, line):
        # blank lines means log current values
        if not line:
            self.bal.logValue()
        else :
#            self.bal.stopReceiving()
#            print menu
            if line == "q" : reactor.stop()
            elif line == "c" : self.bal.startReceiving()
            # elif line == "a" : self.bal.averageN = get_num()
            # elif line == "i" : self.bal.interval = get_num()
#            else: print menu



class Balance():

    def __init__(self, interval, flowInterval, runningAverageN):
        self.prot = serialProtDenver(self)
        self.values = [0,]
        self.times = [0,]
        self.flows = [0,]
        self.aveFlows =[0,]
        self.runningAverageN = runningAverageN
        self.interval = interval
        self.flowInterval = flowInterval
        

    def startReceiving(self, port = comport):
        info_logger.info("Starting receiving")
        info_logger.info("Interval = %f, flow interval = %f, runninge Ave n = %f" % 
                         (self.interval, self.flowInterval, self.runningAverageN))
        self.ser = SerialPort(self.prot,port,reactor,baudrate=baud) 
        self.prot.sendLine("SET SE OFF") # turn off echo
        self.printInterval = LoopingCall(self.printVal)
        self.printInterval.start(self.interval)     
        
    def stopReceiving(self):
        self.prot.stopProducing()

    def printVal(self):
        self.prot.sendLine("DO PR")
        
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
        
    # def logValue(self):
    #     info_logger.info("Logged value")
    #     balance_logger.info( "%f\t%f\t%f" % (self.values[-1], self.flows[-1], (self.values[-1] - self.values[-runningAverageN]) / (self.times[-1] - self.times[-runningAverageN])))

        
    # def tare(self):
    #     self.ser.write("T\n")
#        self.ser.readline() # eat the response

    
 #   def set_time(self):
 #       self.ser.write("SET TT %s\n" % time.strftime("%H:%m:%s"))
 #       self.ser.readline() # throw away






# def set_logfile():
#     try:
#         logfilename = input( "Enter log file name: ")
#         lfile = open(logfilename,'a')
#         LOGFILE = lfile
#     except :
#         print "error opening file"
    

def get_num():
    try:
        newtime = int(input("Enter number: "))
        return newtime
    except :
        print "Error reading number"
    return 1


   
def main():
	"""Command-line tool.  See balance.py -h for help.
	"""

	#set default input and output
	# input = sys.stdin
	# output = sys.stdout
	
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

                                          

      	(options, args) = parser.parse_args()
	# if options.verbose:
	# 	balance_logger.setLevel(logging.INFO)



        #bal = SimBalance()  # to simulate
        #ser = serial.Serial(comport, baud, timeout=1)

        info_logger.debug("Starting program")

        bal = Balance(options.interval, options.flowInterval, options.averageN)      
        bal.startReceiving()
        stdio.StandardIO(inputProtocol(bal))
        reactor.run()
        


if __name__=="__main__":
    main()
    
