import usb.core
import usb.util

import serial

import json

from simplerouter import Router
from webob import Response

PRESETS_PATH = "."
PRESETS_FILE = "presets.json"

PORT = 8000

NZXT_VENDOR_ID = 0x2433
X41_PRODUCT_ID = 0xb200

class Kraken:
	def __init__(self, vid, pid):
		self.vendor = vid
		self.product = pid
		self._find()
		
	def _find(self):
		devices = list(usb.core.find(idVendor=self.vendor, idProduct=self.product, find_all=True))
		count = len(devices)
		if count == 0:
			print("NZXT Kraken: Not found")
			self.device = None
		elif count == 1:
			self.device = devices[0];
			print("NZXT Kraken: Connected")
		else:
			print("NZXT Kraken: Too many devices")
			self.device = None
		
	def light_X41(self, colours=[0,0,0], alt_colours=[0,0,0], alt_interval=1, blink_interval=1, enabled=True, alternating=False, blinking=False):			
		self._init_X41()
		data = [0x10] + colours + alt_colours + [0x00, 0x00, 0x00, 0x3c, alt_interval, blink_interval, enabled, alternating, blinking, 0x00, 0x00, 0x01]
		self.device.write(2, data)
		return self._status_X41()
		
	def _init_X41(self):
		self.device.set_configuration()
		self.device.ctrl_transfer(0x40, 2, 0x0002)
		self.device.ctrl_transfer(0x40, 2, 0x0001)
		
	def _status_X41(self):
		data = self.device.read(0x82, 64)
		status = {
			"fan": 256 * data[0] + data[1],
			"pump": 256 * data[8] + data[9],
			"temp": data[10]
		}
		return status
			
	def claim(self):
		if self.device.is_kernel_driver_active(0):
			print('Detaching kernel driver..')
			self.device.detach_kernel_driver(0)

	def declaim(self):
		if not self.device.is_kernel_driver_active(0):
			print('Reattaching kernel driver..')
			usb.util.dispose_resources(self.device)
			self.device.attach_kernel_driver(0)
			
class Hue:
	def __init__(self, port):
		self.ser = serial.Serial(port, 256000)
		channel_1 = self._write([0x8d, 0x01], response=5)
		print("NZXT HUE+: " + str(channel_1[4]) + " LED strips on channel 1")
		channel_2 = self._write([0x8d, 0x02], response=5)
		print("NZXT HUE+: " + str(channel_2[4]) + " LED strips on channel 2")
		
	def light_controller(self, enabled=True):
		data = [0x46, 0x00, 0xc0, 0x00, 0x00]
		if enabled:
			data.extend([0x00, 0xff])
		else:
			data.extend([0xff, 0x00])
		
		return str(self._write(data))
		
	def _fixed(self, channel=1, colours=[0,0,0], solid=True, enabled=True, **kwargs):
		
		mode = 0x00
		
		if not enabled:
			colours = [0,0,0]
			solid = True
	
		data = [0x4b, channel, mode, 0x00, 0x00]
		colours = self._GRBtoRGB(colours)
		if solid:
			for i in range(40):
				data += colours[0:3]
		else:
			data += colours
			
		return str(self._write(data))
		
	def _spectrum_wave(self, channel=1, backward=False, speed=2, **kwargs):
		mode = 0x02
		data = [0x4b, channel, mode, backward * 16, speed] # TODO replace with bitshift
		for i in range(120):
			data += [0x00]
		return str(self._write(data))
		
	def light_strip(self, **kwargs):
		mode = kwargs.get("mode", 0)
		if mode == 0:
			return self._fixed(**kwargs)
		elif mode == 2:
			return self._spectrum_wave(**kwargs)
		
	def _write(self, data, response=1):
		self.ser.write(bytearray(data))
		read = bytearray(response)
		self.ser.readinto(read)
		return read
		
	def _GRBtoRGB(self, GRB):
		data = list(GRB)
		for i in range(len(data)//3):
			data[i*3], data[(i*3)+1] = data[(i*3)+1], data[i*3]
		return data

def colour(request):
	colour = request.urlvars['colour'].lower()
	
	response = {
		"success": False
	}
	
	if presets.get(colour) == None:
		return Response(json=response)
	elif presets.get(colour).get("alt") != None:
		colour = presets.get(colour).get("alt")
	
	for device, func in active.items():
		
		c = colour
		
		redirects = 0
		while redirects < 10:
			redirects += 1
			if presets.get(c) == None:
				break
			preset = presets.get(c)
			#if preset.get('alt') != None:
			#	c = preset.get('alt')
			#else:
			if preset.get(device) == None:
				break
			elif not isinstance(preset.get(device), dict) or preset.get(device).get('alt') == None:
				status = func(**preset[device])
				response["success"] = True
				response[device] = status
				break
				#return Response(json={'success': True, 'colour': colour, 'fan': status['fan'], 'pump': status['pump'], 'temp': status['temp']})
			else:
				c = preset.get(device).get('alt')
		
	
	return Response(json=response)
			
router = Router()

router.add_route('/colour/{colour}', colour)
application = router.as_wsgi

active = {}

if __name__=='__main__':
	with open(PRESETS_PATH + "\\" + PRESETS_FILE) as file:
		presets = json.loads(file.read())
	X41 = Kraken(NZXT_VENDOR_ID, X41_PRODUCT_ID)
	active["x41"] = X41.light_X41
	hue = Hue('COM3')
	active["hue_controller"] = hue.light_controller
	active["hue"] = hue.light_strip
	
	from wsgiref.simple_server import make_server
	make_server('', PORT, application).serve_forever()
	