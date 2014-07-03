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
from enum import IntEnum
from robotexclusionrulesparser import RobotExclusionRulesParser
from time import sleep
from xml.sax.saxutils import XMLGenerator
import collections
import itertools
import linecache
import requests
import os
import yaml


BASE_URL = "http://xmltv.radiotimes.com/xmltv"
USER_AGENT = "rt2xmltv/1 " + requests.utils.default_user_agent() + " (+https://github.com/lp0/rt2xmltv/)"

session = CacheControl(requests.session(), cache=FileCache('.http-cache'))
session.headers.update({"User-Agent": USER_AGENT})
robot = RobotExclusionRulesParser()


def size_fmt(num):
	for x in ["B", "KB"]:
		if num < 1024 and num > -1024:
			return "%.1f%s" % (num, x)
		num /= 1024
	return "%.1f%s" % (num, "MB")


def time_fmt(num):
	if num < 1:
		return "%.1fms" % (num * 1000)
	if num < 60:
		return "%.1fs" % (num)
	return "%dm%.1fs" % (num // 60, num % 60)

def items_fmt(num):
	if isinstance(num, int):
		return str(num)
	return "%.1f" % (num)


def get(name, filename):
	url = BASE_URL + filename
	allowed = robot.is_allowed(USER_AGENT, url)
	delay = robot.get_crawl_delay(USER_AGENT)
	if delay is None:
		delay = 0.1
	if allowed:
		sleep(delay)

	print("Downloading " + name + "...", flush=True, end="")
	try:
		if not allowed:
			raise Exception("Not allowed to download " + url)

		start = datetime.utcnow()
		r = session.get(url)
		duration = (datetime.utcnow() - start).total_seconds()
		r.raise_for_status()
		print(" " + size_fmt(len(r.text)) + " in " + time_fmt(duration) + " (" + size_fmt(len(r.text) / duration) + "/s)")
	except Exception as e:
		print(" " + str(e))
		raise

	if r.headers["Content-Type"] == "text/plain":
		r.encoding = "UTF-8"
	return r.text


def load_robots_txt():
	try:
		robot.parse(get("robots.txt", "/robots.txt"))
	except:
		pass


def lines(data, base):
	"""Split data up into lines, automatically checking and removing the EULA"""

	lines = data.splitlines()

	if len(lines) < 1 or lines[0] != "\t":
		return lines

	if len(lines) == 1 or not eula(lines[1], base):
		return []

	return lines[2:]


def eula(message, base):
	"""Prompt if the EULA has not already been accepted"""

	EULA_FILE = os.path.join(base, "eula")

	try:
		for line in linecache.getlines(EULA_FILE):
			if line.rstrip("\n") == message:
				return True
	except FileNotFoundError:
		pass

	print("Radio Times EULA")
	print()
	print(message)
	print()
	print("Accept? [Y/n] ", end="")
	try:
		resp = input()
	except:
		print()
		raise

	if resp in ["", "Y", "y"]:
		with open(EULA_FILE, "at", encoding="UTF-8") as f:
			f.write(message + "\n")
		linecache.checkcache(EULA_FILE)
		return True

	if resp not in ["N", "n"]:
		print("Invalid response")

	return False


class Channels(dict):
	def __init__(self, lines):
		super()

		for line in lines:
			(id, name) = line.split("|", 1)
			self[name] = id

	def __getitem__(self, key):
		if key not in self:
			raise Exception("Channel " + key + " not found")

		return get("programmes for " + key, "/" + dict.__getitem__(self, key) + ".dat")


class Files(object):
	def __init__(self, config, base):
		self.config = config
		self.base = base
		self.now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
		self.files = {}

	def _write_element(self, g, name, value, attrs={}):
		if value:
			g.startElement(name, attrs)
			if isinstance(value, list):
				for item in value:
					self._write_element(g, *item)
			elif isinstance(value, tuple):
				self._write_element(g, *value)
			elif not isinstance(value, bool):
				g.characters(value)
			g.endElement(name)

	def write(self, filedate, id, programme):
		if programme[Fields.start].hour < self.config["files"]["start_hour"]:
			filedate -= timedelta(1)

		if filedate < self.now:
			return

		if filedate not in self.files:
			f = open(os.path.join(self.base, filedate.strftime("tv-%Y%m%d.xmltv")), "wb")
			g = XMLGenerator(f, "UTF-8")
			g.startDocument()
			f.write("<!DOCTYPE tv SYSTEM \"xmltv.dtd\">\n".encode("UTF-8"))
			g.startElement("tv", {"source-info-name": "Radio Times"})
			f.write("\n".encode("UTF-8"))
			for channel in self.config["channels"]:
				self._write_element(g, "channel", ("display-name", channel["disp"] if "disp" in channel else channel["name"]), {"id": channel["id"]})
				f.write("\n".encode("UTF-8"))
			self.files[filedate] = (f, g)

		(f, g) = self.files[filedate]
		attrs = collections.OrderedDict()
		attrs["channel"] = id
		attrs["start"] = programme[Fields.start].strftime("%Y%m%d%H%M%S")
		attrs["stop"] = programme[Fields.stop].strftime("%Y%m%d%H%M%S")
		g.startElement("programme", attrs)

		self._write_element(g, "title", programme[Fields.title])
		self._write_element(g, "sub-title", ": ".join(filter(None, [programme[Fields.sub_title], programme[Fields.episode]])))
		self._write_element(g, "desc", programme[Fields.desc])

		if programme[Fields.director] or programme[Fields.cast]:
			self._write_element(g, "credits", [("director", programme[Fields.director])] + [("actor", actor) for actor in programme[Fields.cast]])

		self._write_element(g, "year", programme[Fields.year])

		if programme[Fields.widescreen] or programme[Fields.black_and_white]:
			self._write_element(g, "video", [
				("aspect", "16:9" if programme[Fields.widescreen] else None),
				("colour", "no" if programme[Fields.black_and_white] else None)
			])

		self._write_element(g, "premiere", programme[Fields.premiere])
		self._write_element(g, "new", programme[Fields.new_series])
		self._write_element(g, "subtitles", programme[Fields.subtitles], {"type": "teletext"})

		if programme[Fields.star_rating]:
			self._write_element(g, "star-rating", ("value", programme[Fields.star_rating]))

		if programme[Fields.certificate]:
			self._write_element(g, "rating", ("value", programme[Fields.certificate]), {"system": "BBFC"})

		self._write_element(g, "category", programme[Fields.film])
		self._write_element(g, "category", programme[Fields.genre])

		g.endElement("programme")
		f.write("\n".encode("UTF-8"))

	def close(self):
		for (f, g) in self.files.values():
			g.endElement("tv")
			g.endDocument()
			f.close()


_count = itertools.count()
class Fields(IntEnum):
	title = next(_count)
	sub_title = next(_count)
	episode = next(_count)
	year = next(_count)
	director = next(_count)
	cast = next(_count)
	premiere = next(_count)
	film = next(_count)
	repeat = next(_count)
	subtitles = next(_count)
	widescreen = next(_count)
	new_series = next(_count)
	deaf_signed = next(_count)
	black_and_white = next(_count)
	star_rating = next(_count)
	certificate = next(_count)
	genre = next(_count)
	desc = next(_count)
	choice = next(_count)
	date = next(_count)
	start = next(_count)
	stop = next(_count)
	duration_mins = next(_count)

BOOL_FIELDS = [
	Fields.premiere,
	Fields.film,
	Fields.repeat,
	Fields.subtitles,
	Fields.widescreen,
	Fields.new_series,
	Fields.deaf_signed,
	Fields.black_and_white,
	Fields.choice
]


class Programmes(object):
	def __init__(self, channel, lines):
		self.channel = channel
		self.lines = lines

	def __iter__(self):
		for line in self.lines:
			data = line.split("~")
			if len(data) != len(Fields):
				raise Exception("Fields in line %d != %d: " % (len(data), len(Fields)) + repr(line))

			for field in BOOL_FIELDS:
				data[field] = data[field] == "true"

			if data[Fields.cast]:
				actors = []
				for actor in [x.split("*") for x in data[Fields.cast].split("|" if "|" in data[Fields.cast] else ",")]:
					if len(actor) == 1:
						actors.append(actor[0])
					else:
						actors.append(actor[1] + " (" + actor[0] + ")")
				data[Fields.cast] = actors

			if data[Fields.star_rating]:
				data[Fields.star_rating] += "/5"

			if data[Fields.film]:
				data[Fields.film] = "Film"

				if data[Fields.genre].lower() == "film":
					data[Fields.genre] = ""

			if data[Fields.genre].lower() == "no genre":
				data[Fields.genre] = "";

			(day, month, year) = map(int, data[Fields.date].split("/"))
			(start_hour, start_minute) = map(int, data[Fields.start].split(":"))
			(stop_hour, stop_minute) = map(int, data[Fields.stop].split(":"))

			start = datetime(year, month, day, start_hour, start_minute)
			stop = datetime(year, month, day, stop_hour, stop_minute)
			if stop < start:
				stop += timedelta(1)

			data[Fields.start] = start
			data[Fields.stop] = stop

			filedate = start.replace(hour=0, minute=0)

			yield (filedate, data)

	def write(self, files):
		print("Processing programmes for " + self.channel["name"] + "...", flush=True, end="")
		try:
			start = datetime.utcnow()
			id = self.channel["id"]
			for (filedate, programme) in iter(self):
				files.write(filedate, id, programme)
			duration = (datetime.utcnow() - start).total_seconds()
			print(" " + items_fmt(len(self.lines)) + " in " + time_fmt(duration) + " (" + items_fmt(len(self.lines) / duration) + "/s)")
		except:
			print()
			raise

def main(config="config", base=os.getcwd()):
	load_robots_txt()

	channels = get("channel list", "/channels.dat")
	with open(os.path.join(base, "channels.dat"), "wt", encoding="UTF-8") as f:
		f.write(channels)

	channels = Channels(lines(channels, base))
	config = yaml.safe_load(open(os.path.join(base, config), "rt", encoding="UTF-8"))
	config.setdefault("files", {})
	config["files"].setdefault("start_hour", 6)

	programmes = []
	for channel in config["channels"]:
		programmes.append(Programmes(channel, lines(channels[channel["name"]], base)))

	files = Files(config, base)
	for item in programmes:
		item.write(files)
	files.close()

if __name__ == "__main__":
	main()
