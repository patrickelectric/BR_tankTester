#!/usr/bin/env python
import datetime
import os
import sys
import time

from argparse import ArgumentParser

import dropbox
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError, AuthError

import pigpio
import serial

# DEFAULT VALUES
# Dropbox token
TOKEN = ''

WELCOME_TEXT = """
Welcome to Tankinator test platform !
This script automates tank testing by running the thruster for a set duration while recording data,
with a long duration pause between each throttle level for tank to settle.
Push ctrl+c to exit at any time.
"""
parser = ArgumentParser(description=WELCOME_TEXT)
parser.add_argument(
		"--power-supply-serial",
		dest="power_supply_serial",
		required=False,
		type=str,
		default="/dev/ttyUSB0",
		help="Serial to communicate with power supply."
)
parser.add_argument(
		"--force-sensor-serial",
		dest="force_sensor_serial",
		required=False,
		type=str,
		default="/dev/ttyACM0",
		help="Serial to communicate with force sensor."
)
parser.add_argument(
		"--force-sensor-serial",
		dest="rpm_sensor_serial",
		required=False,
		type=str,
		default="/dev/ttyACM1",
		help="Serial to communicate with force sensor."
)

args = parser.parse_args()

print(WELCOME_TEXT)

# min and max throttle
MIN_THROTTLE = 1000
MAX_THROTTLE = 2000
# in TWHOI = 25.25, T200 = 25.625, T500X14 = 26.56
MECH_VERTICAL = 26.56
# in advtg = vert/horiz
MECH_HORIZ = 29.938
# in T200 = 14, T100 = 12
POLE_COUNT = 14

# clear screen
os.system('clear')

# initialize raspberry gpio
pi = pigpio.pi() # initialize servo style ESC control
pi.set_servo_pulsewidth(18, MIN_THROTTLE) # set initial PWM

# mmax must always be more than minimum.
# Swap motor wires to change direction!
time.sleep(5)

# Power supply output
# scale rs232 to usb
power_supply_serial = serial.Serial(
	    port=args.power_supply_serial,\
	    baudrate=19200,\
	    parity=serial.PARITY_NONE,\
	    stopbits=serial.STOPBITS_ONE,\
	    bytesize=serial.EIGHTBITS,\
	    timeout=3)

# Force sensor
force_sensor_serial = serial.Serial(
	    port=args.force_sensor_serial,\
	    baudrate=19200,\
	    parity=serial.PARITY_NONE,\
	    stopbits=serial.STOPBITS_ONE,\
	    bytesize=serial.EIGHTBITS,\
	    timeout=3)

# RPM sensor
rpm_sensor_serial = serial.Serial(
	    port=args.rpm_sensor_serial,\
            baudrate=19200,\
            parity=serial.PARITY_NONE,\
            stopbits=serial.STOPBITS_ONE,\
            bytesize=serial.EIGHTBITS,\
            timeout=3)

force_sensor_serial.flushInput()# clear input before taking reading for rough sync to seperate Arduino :(
rpm_sensor_serial.flushInput()# same ^^
scale_level = (force_sensor_serial.readline()) # Arduino configured to output at 10hz of this script
scale_level = (rpm_sensor_serial.readline()) #same^^
print("The current reading of the force sensor is %s" % scale_level)
test_name = raw_input('Enter name of this test: ')
timenow='{date:%Y.%m.%d %H.%M.%S}.csv'.format( date=datetime.datetime.now() )
fname = test_name + ' ' + timenow #create filename from user name and time at start of test
d_steps = input('Duration of each throttle step (seconds) (Adam says 3sec, with 20 second pause between)')
d_steps = d_steps+1 
num_steps = input('# of steps from 0 to full throttle (one direction - if wrong, swap 2 motor wires)')
settle_time = 20 #seconds between throttle steps. Change to input if frequently varied across tests
loop_period = 0.1 # 1/ this = hz
throttle_bump = (MAX_THROTTLE-MIN_THROTTLE)/num_steps # % increase of throttle level
calc_duration = (float(d_steps)*float(num_steps))+((num_steps-1)*settle_time) 
print("Test time will be: %d seconds" % calc_duration)
print("The total number of measurements will be %d." % (d_steps*num_steps/loop_period))
print("Go make something.")

time.sleep(1)
f=open("/home/pi/tankinator/BR_tankTester/%s"%fname, "a+") # write header for CSV once
f.write("Time, Force, Power, Voltage, Current, RPM, PWM, efficiency (g/w)")
f.write('\n')
f.close()
LOCALFILE = '%s'%fname #file to backup
BACKUPPATH = '/%s'%fname
prevthrottle = MIN_THROTTLE
throttle = MIN_THROTTLE #center point throttle
runmotor=1 #flag used to control data logging & output
# note start time
start_time = time.time()   
while (throttle <=MAX_THROTTLE) and (prevthrottle != MAX_THROTTLE): # exit when throttle exceeds 100% microseconds
	if ((time.time() - start_time)>d_steps) and runmotor == 0: # if the runtime is over
		pi.set_servo_pulsewidth(18,MIN_THROTTLE) #initialize
		print('Letting tank settle for %d seconds' % settle_time)
		runmotor = 1 #raise flag to allow throttle change
		if throttle == 2000:
			break
		time.sleep(settle_time)  
		start_time = time.time()
	if runmotor==1 and ((time.time()-start_time)<d_steps): #if change is ok and during next run period
		prevthrottle = throttle #used to limit ramp up
		while throttle < (prevthrottle + throttle_bump):
			throttle = throttle + int(throttle_bump) #ramping to not make it shake	
			pi.set_servo_pulsewidth(18,throttle) #initialize
		time.sleep(1)# let things settle out before starting log	
		runmotor = 0 #keep it from increasing again within same period
	try:  #to talk to power supply
		power_supply_serial.write('MEASURE:VOLTAGE:DC?') #from documentation.
		power_supply_serial.write(b'\rL1\r') #sends enter after request to get return
		VOLTAGE = float(power_supply_serial.readline()) #cast to float
		power_supply_serial.write('MEASURE:CURRENT:DC?')
		power_supply_serial.write(b'\rL1\r')
		CURRENT = float(power_supply_serial.readline())
		POWER = VOLTAGE * CURRENT #calculate the useful metric
	except:
		print("power supply comm error dude")
	try: #to read the external ADC. Need to update prompts to include lever arm, remove this from Arduino sketch
		force_sensor_serial.flushInput()# clear input before taking reading for rough sync to seperate Arduino :(
		input = (force_sensor_serial.readline()) # Arduino configured to output at 10hz of this script
		FORCE = float(input)/(MECH_VERTICAL/MECH_HORIZ)#add scaling here to include lever arm input, remove from Arduino output
		efficiency = float(((FORCE*float(453.59))/POWER))
	except:
		print("sorry man, force sensor com error")

	try: #to read the external RPM sensor.
		rpm_sensor_serial.flushInput()# clear input before taking reading for rough sync to seperate Arduino :(
		input = (rpm_sensor_serial.readline()) # Arduino configured to output at 10hz of this script
		RPM = 60000000/(float(input)*(POLE_COUNT/2))#Get RPM from filtered period value, incorporate pole count
		# attempt at json readable format
		print({
				"efficiency": efficiency,
				"PWM": throttle,
				"RPM": RPM,
				"CURRENT": CURRENT,
				"VOLTAGE": VOLTAGE,
				"POWER": POWER,
				"FORCE": FORCE,
				"TIME": datetime.datetime.now().strftime("%H:%M:%S.%f")
			})
	except:
		print("sorry man, RPM sensor comm error")
	try: #to log data
		f=open("/home/pi/tankinator/BR_tankTester/%s"%fname, "a+") #open new file in append mode
		f.write(datetime.datetime.now().strftime("%H:%M:%S.%f")) # write data in csv format
		f.write(',')
		f.write("%s"%FORCE)
		f.write(',')
		f.write("%s"%POWER)
		f.write(',')
		f.write("%s"%VOLTAGE)
		f.write(',')
		f.write("%s"%CURRENT)
		f.write(',')
		f.write("%s"%RPM)
		f.write(',')
		f.write("%s"%throttle)
		f.write(',')
		f.write("%s"%efficiency)
		f.write('\n')
		f.close()
		#print "log file line logged"
	except:
		print("data not saved pal")
#	time.sleep(loop_period) #unmanaged 10hz as initially tested. may run faster? Too many #s to analyze
pi.set_servo_pulsewidth(18,MIN_THROTTLE) #turn onff motor post test
time.sleep(2)
print("test complete dude")

# Add OAuth2 access token here.
# You can generate one for yourself in the App Console.
# See <https://blogs.dropbox.com/developers/2014/05/generate-an-access-token-for-your-own-account/>
def backup():# Uploads contents of logfile to Dropbox
    with open(LOCALFILE, 'rb') as f:
        # We use WriteMode=overwrite to make sure that the settings in the file
        # are changed on upload
        print("Uploading " + LOCALFILE + " to Dropbox as " + BACKUPPATH + "...")
        try:
            dbx.files_upload(f.read(), BACKUPPATH, mode=WriteMode('overwrite'))
        except ApiError as err:
            # This checks for the specific error where a user doesn't have
            # enough Dropbox space quota to upload this file
            if (err.error.is_path() and
                    err.error.get_path().reason.is_insufficient_space()):
                sys.exit("ERROR: Cannot back up; insufficient space.")
            elif err.user_message_text:
                print(err.user_message_text)
                sys.exit()
            else:
                print(err)
                sys.exit()

if __name__ == '__main__':
    # Check for an access token
    if (len(TOKEN) == 0):
        sys.exit("ERROR: Looks like you didn't add your access token. "
            "Open up backup-and-restore-example.py in a text editor and "
            "paste in your token in line 14.")# Create an instance of a Dropbox class, which can make requests to the API.
    print("Creating a Dropbox object...")
    dbx = dropbox.Dropbox(TOKEN)
    try:# Check that the access token is valid
        dbx.users_get_current_account()
    except AuthError as err:
        sys.exit("ERROR: Invalid access token; try re-generating an "
            "access token from the app console on the web.")
    backup()    # Create a backup of the current log file
    print("Data saved to Adam's dropbox by TANKINATOR!!!!!!")
