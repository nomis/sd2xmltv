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
from xml.sax.saxutils import XMLGenerator
import enum
import itertools
import linecache
import requests
import os
import yaml


BASE_URL = "http://xmltv.radiotimes.com/xmltv"

session = CacheControl(requests.session(), cache=FileCache('.http-cache'))
session.headers.update({"User-Agent": "rt2xmltv/1 " + requests.utils.default_user_agent()})


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
	resp = input()
	print()

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
	def __init__(self, channels, base):
		self.channels = channels
		self.base = base
		self.now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
		self.files = {}

	def _write_element(self, g, name, value, attrs={}):
		if value:
			g.startElement(name, attrs)
			if not isinstance(value, bool):
				g.characters(value)
			g.endElement(name)

	def write(self, filedate, id, programme):
		if filedate < self.now:
			return

		if filedate not in self.files:
			f = open(os.path.join(self.base, filedate.strftime("tv-%Y%m%d.xmltv")), "wb")
			g = XMLGenerator(f, "UTF-8")
			g.startDocument()
			f.write("<!DOCTYPE tv SYSTEM \"xmltv.dtd\">\n".encode("UTF-8"))
			g.startElement("tv", {"source-info-name": "Radio Times"})
			f.write("\n".encode("UTF-8"))
			for channel in self.channels:
				g.startElement("channel", {"id": channel["id"]})
				self._write_element(g, "display-name", channel["disp"] if "disp" in channel else channel["name"])
				g.endElement("channel")
				f.write("\n".encode("UTF-8"))
			self.files[filedate] = (f, g)

		(f, g) = self.files[filedate]
		g.startElement("programme", {
			"start": programme[Fields.start].strftime("%Y%m%d%H%M%S"),
			"stop": programme[Fields.stop].strftime("%Y%m%d%H%M%S"),
			"channel": id
		})

		self._write_element(g, "title", programme[Fields.title])
		self._write_element(g, "sub-title", ": ".join(filter(None, [programme[Fields.sub_title], programme[Fields.episode]])))
		self._write_element(g, "desc", programme[Fields.desc])

		if programme[Fields.director] or programme[Fields.cast]:
			g.startElement("credits", {})
			self._write_element(g, "director", programme[Fields.director])
			for actor in programme[Fields.cast]:
				self._write_element(g, "actor", actor)
			g.endElement("credits")

		self._write_element(g, "year", programme[Fields.year])

		if programme[Fields.widescreen] or programme[Fields.black_and_white]:
			g.startElement("video", {})
			if programme[Fields.widescreen]:
				self._write_element(g, "aspect", "16:9")
			if programme[Fields.black_and_white]:
				self._write_element(g, "colour", "no")
			g.endElement("video")

		self._write_element(g, "premiere", programme[Fields.premiere])
		self._write_element(g, "new", programme[Fields.new_series])
		self._write_element(g, "subtitles", programme[Fields.subtitles], {"type": "teletext"})

		if programme[Fields.star_rating]:
			g.startElement("star-rating", {})
			self._write_element(g, "value", programme[Fields.star_rating] + "/5")
			g.endElement("star-rating")

		if programme[Fields.certificate]:
			g.startElement("rating", {"system": "BBFC"})
			self._write_element(g, "value", programme[Fields.certificate])
			g.endElement("rating")

		if programme[Fields.film]:
			self._write_element(g, "category", "Film")

		if programme[Fields.genre] not in ["", "Film", "film", "No Genre"]:
			self._write_element(g, "category", programme[Fields.genre])

		g.endElement("programme")
		f.write("\n".encode("UTF-8"))

	def close(self):
		for (f, g) in self.files.values():
			g.endElement("tv")
			g.endDocument()
			f.close()


_count = itertools.count()
class Fields(enum.IntEnum):
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
				raise Exception(("Fields in line %d != %d: " % len(data), len(Fields)) + repr(line))

			for field in BOOL_FIELDS:
				data[field] = data[field] == "true"

			if data[Fields.cast]:
				actors = set()
				for actor in [x.split("*") for x in data[Fields.cast].split("|" if "|" in data[Fields.cast] else ",")]:
					if len(actor) == 1:
						actors.add(actor[0])
					else:
						actors.add(actor[1] + " (" + actor[0] + ")")
				data[Fields.cast] = actors

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
			if start.hour < 6:
				filedate -= timedelta(1)

			yield (filedate, data)

	def write(self, files):
		print("Processing programmes for " + self.channel["name"] + "...", flush=True, end="")
		start = datetime.utcnow()
		id = self.channel["id"]
		for (filedate, programme) in iter(self):
			files.write(filedate, id, programme)
		duration = (datetime.utcnow() - start).total_seconds()
		print(" " + items_fmt(len(self.lines)) + " in " + time_fmt(duration) + " (" + items_fmt(len(self.lines) / duration) + "/s)")


def main(config="config", base=os.getcwd()):
	channels = get("channel list", "/channels.dat")
	with open(os.path.join(base, "channels.dat"), "wt", encoding="UTF-8") as f:
		f.write(channels)

	channels = Channels(lines(channels, base))
	config = yaml.load(open(os.path.join(base, config), "rt", encoding="UTF-8"))

	programmes = []
	for channel in config["channels"]:
		programmes.append(Programmes(channel, lines(channels[channel["name"]], base)))

	files = Files(config["channels"], base)
	for item in programmes:
		item.write(files)
	files.close()

if __name__ == "__main__":
	main()
