## LAST UPDATE 04/03/2019 AT 11:45 PM ##
## THIS IS UNFINISHED CODE PLS HELP ##
## TODO LIST: ##
# - FUNCTION TO READ COMMANDS FROM WIFI AND PROCESS THEM - VENT / DISCONNECT !!!!!!!

from datetime import datetime
from csv import writer
from adafruit_ads1x15.ads1115 import P0,P1,P2,P3
import threading
import time
import board
import load_cell as lc
import RocketThermocouple as tc
import pressure_transducer as pt
from SendToFlask import sendData
## import Server   # doesn't work
# import QuickDisconnect as qd
try:
    import RPi.GPIO as GPIO  # RPi.GPIO documentation: https://sourceforge.net/p/raspberry-gpio-python/wiki/
except:
    print("Error importing RPi.GPIO!  This is probably because you need superuser privileges.  You can achieve this by using 'sudo' to run your script")

### LIST OF UNDEFINED VARIABLES, CONSTANTS --- UPDATE as NEEDED ###

#spi = busio.SPI(board.SCK_1, MOSI=board.MOSI_1, MISO=board.MISO_1)

### BLASTED PINS FOR SENSORS AND DETECTION WHATNOT ###

EMERG_MBVALVE_SHUTOFF_PIN = 4 # what is this?
MBVALVE_DETECT_PIN = 12
# DISCONNECT_DETECT_PIN = 16
FUEL_SOLENOID_DETECT_PIN = 16
VENT_VALVE_DETECT_PIN = 25
EMATCH_DETECT_PIN = 13

PT_CHANNELS = [P0,P1,P2]
# TC_CS_PINS = [17,27,22,5,6,13]
#TC_CS_PINS = [board.D17,board.D27]
TC_CS_PINS = [board.D17, board.D27, board.D22, board.D5, board.D6, board.D26]
#LC_SEL_TUPLES = ((0, 0), None)
LC_SEL_TUPLES = ((0, 0), (0, 1), (1, 0))

CRIT_T = 309.5
CRIT_P = 7240.0

Is_Critical = False

### VARIABLES TO STORE SENSOR OBJECTS ###
data = []
QDSTATE = False # false for closed true for open
VENTVALVE = False # false for closed true for open

# Where load cell objects are stored
# To access the last reading of an individual load cell i,
# use LOAD_CELLS[i].last_reading
LOAD_CELLS = []
global Ser     # Serial port

# Place to put TC objects
TCs = []

# Place to put PT objects
PTs = []

def init():
    # Initialize load cell serial and GPIO, then instantiate load cell objects
    Ser = lc.begin()
    for select_tuple in LC_SEL_TUPLES:  ## soo... LC_SEL_TUPLES is supposed to come from that external configuration file, but I don't know how to do that yet...
        if select_tuple:
            LOAD_CELLS.append(lc.Load_Cell(select_tuple, Ser))

    spi = tc.begin();
    # Initialize thermocouples
    for cs_pin in TC_CS_PINS:
        TCs.append(tc.Thermocouple(cs_pin, spi))

    # Initialize PTs
    for pt_chan in PT_CHANNELS:
        PTs.append(pt.PressureTransducer(pt_chan))

    # Configure GPIO pin for telling the ignition computer to close the motorized ball valve in an emergency:
    GPIO.setup(EMERG_MBVALVE_SHUTOFF_PIN, GPIO.OUT)
    GPIO.setup(MBVALVE_DETECT_PIN, GPIO.IN)
    GPIO.output(EMERG_MBVALVE_SHUTOFF_PIN, False)

    # Configure vent GPIO pins
    GPIO.setup(VENT_VALVE_DETECT_PIN, GPIO.IN)
    # GPIO.setup(VENT_VALVE_SHUTOFF_PIN, GPIO.OUT)   # Not used for cold flowa
    # GPIO.setup(DISCONNECT_DETECT_PIN, GPIO.IN)
    GPIO.setup(FUEL_SOLENOID_DETECT_PIN, GPIO.IN)
    GPIO.setup(EMATCH_DETECT_PIN, GPIO.IN)

    # # Start server listening on port 12345 to communicate with operator console (GUI).
    # Server.serverSetup()
    # threading.Thread(target=send_data_upon_request()).start()

### FUNCTIONS TO ITERATE THROUGH ALL SENSORS ###
def collectData():
    try:
        global Is_Critical
        global data
        # See here for why we need the above line: https://stackoverflow.com/questions/10851906/python-3-unboundlocalerror-local-variable-referenced-before-assignment#10852003
        data = data + tc.readThermocouples(TCs)
        ## change the critical checks to being a 2 state system so it doesnt # continuiously call emergency shutdown
        for thermocouple in TCs:
            if (thermocouple.last_reading > CRIT_T and Is_Critical == False):
                emergency_shutdown()
                Is_Critical = 1
                print('EMERGENCY SHUTDOWN: Critical Temperature detected')

        data = data + pt.readPressureTransducers(PTs)
        for sensor in PTs:
            if ((sensor.last_reading > CRIT_P) and (Is_Critical == False)):
                emergency_shutdown()
                Is_Critical = 1
                print('EMERGENCY SHUTDOWN: Critical Pressure detected')

        data = data + lc.read_load_cells(LOAD_CELLS)
   #[*TC1 (Top), *TC2 (Bottom), TC3, TC4, TC5, TC6, *PT1 (Top), *PT2 (Bottom), PT3, *LC1 (NOX mass), LC2 (Thrust), LC3, *Sol1 (Fueling), *Sol2 (Venting), *Sol3 (Disconnect), *Sol4 (Reset), *Ballvalve, *Ignition]
        data.append(getFuelSolState())
        data.append(getVentState())
        data = data + [0, 0]   # pads out spot that would have been occupied with disconnect/reset states
        # data.append(getDisconnectState())
        data.append(getBallValveState())
        data.append(getEmatchState())
    except Exception as e:
        print("!!! Error in colletData:")
        print(str(e))
        return None

### OTHER FUNCTIONS ###

# Tell ignition computer to close motorized ball valve.
# Doesn't actually close the valve (that's the igcomp's job) --- hence the name
def emergency_shutdown():
    GPIO.output(EMERG_MBVALVE_SHUTOFF_PIN, True) #this needs to be a actuate ball valve function on its own
    # Vent()

# Tell ignition computer to open venting solenoid
# def Vent():
#     GPIO.output(VENT_VALVE_SHUTOFF_PIN, True)
#     VENTVALVE = True
#     return VENTVALVE

## FIXME MAYBE?  Should we have a function to order the igcomp to open the ball valve?

def getFuelSolState():
    return GPIO.input(FUEL_SOLENOID_DETECT_PIN)

def getVentState():
    return GPIO.input(VENT_VALVE_DETECT_PIN)

# def getDisconnectState():
#     return GPIO.input(DISCONNECT_DETECT_PIN)

def getBallValveState():
    return GPIO.input(MBVALVE_DETECT_PIN)


def getEmatchState():
    return GPIO.input(EMATCH_DETECT_PIN)


### DATA LOGGING AND TRANSMISSION ###

#Writes data
def writedata(args):
    packet = []
    packet.append(datetime.now())
    for i in range(0,len(args)):
        packet.append(args[i])
    data_writer.writerow(packet)

## There used to be an ' import csv ' statement here and ' writer(log) ' was ' csv.writer(log) '
with open('DATA1.csv','a',newline='') as log:
    data_writer = writer(log)

    #Header row so you know what you're looking at (change as necessary)
    data_writer.writerow(['Timestamp','TC1','TC2','TC3','TC4','TC5','TC6','PT1','PT1','PT3','PT4','LC1','LC2','LC3','FuelValve','VentValve','Disconnect','Reset','BallValve','Ignition'])
    try:
        init()
    except Exception as e:
        print("Error in init()")
    while True:
        #collect all data here and assign to variables
        #slam all that shite into the writedata function (or append to a list each time a sensor is read)
        collectData()
        try:
            writedata(data)
            sendData(data)
            print(data)
            time.sleep(0.01)
            data = []
        except Exception as e:
            print("!!! Error in main DART loop whilst recording or transmitting data:")
            print(str(e))
