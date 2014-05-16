#!/usr/bin/env python3

#  rt2xmltv - Radio Times to XMLTV downloader
#
#  Copyright ©2014 Simon Arlott
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

from cachecontrol import CacheControl
from cachecontrol.caches import FileCache
from datetime import datetime
from datetime import timedelta
import itertools
import requests
import os
import yaml


BASE_URL = "http://xmltv.radiotimes.com/xmltv"

session = CacheControl(requests.session(), cache=FileCache('.http-cache'))
session.headers.update({"User-Agent": "rt2xmltv/1 " + requests.utils.default_user_agent()})


def size_fmt(num):
	for x in ["B", "KB"]:
		if num < 1024 and num > -1024:
			return "%3.1f%s" % (num, x)
		num /= 1024
	return "%3.1f%s" % (num, "MB")


def time_fmt(num):
	if num < 1:
		return "%3.1fms" % (num * 1000)
	if num < 60:
		return "%3.1fs" % (num)
	return "%dm%3.1fs" % (num // 60, num % 60)


def get(name, filename):
	global session

	print("Downloading " + name + "...", flush=True, end="")

	start = datetime.utcnow()
	r = session.get(BASE_URL + filename)
	duration = (datetime.utcnow() - start).total_seconds()
	if r.status_code != requests.codes.ok:
		print()
	r.raise_for_status()

	print(" " + size_fmt(len(r.text)) + " in " + time_fmt(duration) + " (" + size_fmt(len(r.text) / duration) + "/s)")
	return r.text


def lines(data, base):
	lines = data.splitlines()

	if len(lines) < 1 or lines[0] != "\t":
		return lines

	if len(lines) == 1 or not eula(lines[1], base):
		return []

	return lines[2:]


def eula(message, base):
	try:
		for line in open(os.path.join(base, "eula"), "rt", encoding="UTF-8"):
			if line.rstrip("\n") == message:
				return True
	except FileNotFoundError:
		pass

	print("Radio Times EULA")
	print()
	print(message)
	print()
	print("Accept? [Y/n] ", end="")
	resp = input()
	print()

	if resp in ["", "Y", "y"]:
		with open(os.path.join(base, "eula"), "at", encoding="UTF-8") as f:
			f.write(message + "\n")
		return True

	if resp not in ["N", "n"]:
		print("Invalid response")

	return False


class Channels(object):
	def __init__(self, lines):
		self.channels = {}

		for line in lines:
			(id, name) = line.split("|", 1)
			self.channels[name] = id

	def __getitem__(self, key):
		if key not in self.channels:
			raise Exception("Channel " + key + " not found")

		return get("programmes for " + key, "/" + self.channels[key] + ".dat")


def main(config="config", base=os.getcwd()):
	channels = get("channel list", "/channels.dat")
	with open(os.path.join(base, "channels.dat"), "wt", encoding="UTF-8") as f:
		f.write(channels)

	channels = Channels(lines(channels, base))
	config = yaml.load(open(os.path.join(base, config), "rt", encoding="UTF-8"))

	for channel in config["channels"]:
		data = channels[channel["name"]]


if __name__ == "__main__":
	main()
