#!/usr/bin/env python3

#  sd2xmltv - Schedules Direct to XMLTV downloader
#
#  Copyright 2014-2019  Simon Arlott
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
from datetime import date
from datetime import datetime
from datetime import timedelta
from enum import IntEnum
from time import sleep
from xml.sax.saxutils import XMLGenerator
import collections
import hashlib
import itertools
import json
import os
import pytz
import re
import requests
import requests_cache
import tempfile
import tzlocal
import yaml


BASE_URL = "https://json.schedulesdirect.org/20141201"
USER_AGENT = "sa-sd2xmltv/1 " + requests.utils.default_user_agent() + " (+https://github.com/nomis/sd2xmltv/)"
TEMP_DIR_LINK = os.path.join("/", "run", "user", str(os.getuid()), "sd2xmltv")

try:
	os.stat(TEMP_DIR_LINK)
except FileNotFoundError:
	try:
		os.unlink(TEMP_DIR_LINK)
	except:
		pass
	os.symlink(tempfile.mkdtemp(prefix="sd2xmltv."), TEMP_DIR_LINK)

tz = tzlocal.get_localzone()
requests_cache.install_cache(os.path.join(TEMP_DIR_LINK, "http_cache"), allowable_methods=("GET", "POST"), include_get_headers=False, expire_after=10800)
requests_cache.core.remove_expired_responses()
session = requests.session()
session.headers.update({"User-Agent": USER_AGENT})

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


def safe_filename(text):
	return "".join([c if re.match(r"[\w-]", c) else "_" for c in text])


def get(name, filename, params=None, query=None):
	url = BASE_URL + filename

	print("Downloading " + name + "...", flush=True, end="")
	r = None
	try:
		start = datetime.utcnow()
		if params is None:
			r = session.get(url, params=query)
		else:
			r = session.post(url, json.dumps(params))
		duration = (datetime.utcnow() - start).total_seconds()
		r.raise_for_status()
		print(" " + size_fmt(len(r.text)) + " in " + time_fmt(duration) + " (" + size_fmt(len(r.text) / duration) + "/s)")
	except Exception as e:
		print(" " + str(e))
		if r is not None:
			print(r.headers)
			print(r.text)
		raise

	if r.headers["Content-Type"] == "text/plain":
		r.encoding = "UTF-8"
	return json.loads(r.text)

def put(name, filename):
	url = BASE_URL + filename

	print(name + "...", flush=True, end="")
	r = None
	try:
		start = datetime.utcnow()
		r = session.put(url)
		duration = (datetime.utcnow() - start).total_seconds()
		r.raise_for_status()
		print(" " + size_fmt(len(r.text)) + " in " + time_fmt(duration) + " (" + size_fmt(len(r.text) / duration) + "/s)")
	except Exception as e:
		print(" " + str(e))
		if r is not None:
			print(r.headers)
			print(r.text)
		raise

	if r.headers["Content-Type"] == "text/plain":
		r.encoding = "UTF-8"
	return json.loads(r.text)


class Channels(dict):
	def __init__(self, name, lineup_data):
		super()
		self.name = name
		self.data = lineup_data

		for station in filter(None, self.data["stations"]):
			self[station["name"]] = station["stationID"]

	def __getitem__(self, key):
		if key not in self:
			raise Exception("Channel " + key + " not found in " + self.name)

		return get("schedules for " + key, "/schedules", [{ "stationID": dict.__getitem__(self, key) }])


class Files(object):
	def __init__(self, config, base):
		self.config = config
		self.base = base
		self.now = tz.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None))
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
		if programme["start"].hour < self.config["files"]["start_hour"]:
			filedate -= timedelta(1)

		if filedate < self.now:
			return

		if filedate not in self.files:
			f = open(os.path.join(self.base, filedate.strftime("tv-%Y%m%d.xmltv")), "wb")
			g = XMLGenerator(f, "UTF-8")
			g.startDocument()
			f.write("<!DOCTYPE tv SYSTEM \"xmltv.dtd\">\n".encode("UTF-8"))
			g.startElement("tv", {"source-info-name": "Schedules Direct"})
			f.write("\n".encode("UTF-8"))
			for (lineup, channels) in self.config["channels"].items():
				for channel in channels:
					self._write_element(g, "channel", ("display-name", channel["disp"] if "disp" in channel else channel["name"]), {"id": channel["id"]})
					f.write("\n".encode("UTF-8"))
			self.files[filedate] = (f, g)

		(f, g) = self.files[filedate]
		attrs = collections.OrderedDict()
		attrs["channel"] = id
		attrs["start"] = programme["start"].astimezone(tz).strftime("%Y%m%d%H%M%S")
		attrs["stop"] = programme["stop"].astimezone(tz).strftime("%Y%m%d%H%M%S")
		g.startElement("programme", attrs)

		showType = programme.get("showType", "").lower()
		film = programme.get("entityType", "") == "Movie" or "film" in showType or "movie" in showType

		new_series = False
		subtitle = []
		for md in programme.get("metadata", []):
			for mdv in md.values():
				st = "s{0}".format(mdv.get("season"))
				if "totalSeasons" in mdv:
					st += "/{0}".format(mdv["totalSeasons"])

				if "episode" in mdv:
					if mdv["episode"] == 1:
						new_series = True

					st += ", e{0}".format(mdv.get("episode"))
					if "totalEpisodes" in mdv:
						st += "/{0}".format(mdv["totalEpisodes"])

				if mdv.get("season") > 0:
					subtitle.append(st)

		self._write_element(g, "title", programme["titles"][0].get("title120"))

		if "episodeTitle150" in programme:
			subtitle.append(programme.get("episodeTitle150"))
		if subtitle:
			self._write_element(g, "sub-title", ": ".join(subtitle))

		descriptions = sorted(programme.get("descriptions", {}).get("description1000", {}),
			key=lambda x: {"en-GB": -2, "en": -1}.get(x["descriptionLanguage"], 0))
		if descriptions:
			self._write_element(g, "desc", descriptions[0].get("description"))

		self._write_element(g, "credits", programme.get("cast", []))

		self._write_element(g, "year", programme.get("movie", {}).get("year"))

		if film and "originalAirDate" in programme:
			if abs(programme["start"].date() - date(*[int(x) for x in programme["originalAirDate"].split("-")])) <= timedelta(2):
				self._write_element(g, "premiere", programme.get("premiere"))

		self._write_element(g, "new", new_series)

		for rating in programme.get("contentRating", []):
			self._write_element(g, "rating", ("value", rating["code"]), {"system": rating["body"]})

		if film:
			self._write_element(g, "category", "film")
		self._write_element(g, "category", programme.get("episodeType"))
		self._write_element(g, "category", programme.get("showType"))
		for genre in programme.get("genres", []):
			self._write_element(g, "category", genre)

		g.endElement("programme")
		f.write("\n".encode("UTF-8"))

	def close(self):
		for (f, g) in self.files.values():
			g.endElement("tv")
			g.endDocument()
			f.close()


class ProgramData(dict):
	def __init__(self, schedule):
		super()

		need = []
		for program in schedule:
			if program["programID"] not in self:
				need.append(program)
		need.sort(key=lambda x: x["programID"])
		while len(need) > 0:
			data = get("program data", "/programs", [x["programID"] for x in need[0:5000]])
			for program in data:
				self[program["programID"]] = program
			need = need[5000:]


class Programmes(object):
	def __init__(self, channel, schedule):
		self.channel = channel
		if not "programs" in schedule[0]:
			print(schedule)
		self.schedule = list(itertools.chain(*[x["programs"] for x in schedule]))
		self.program_data = ProgramData(self.schedule)

	def __iter__(self):
		for program in self.schedule:
			data = self.program_data[program["programID"]].copy()

			if "cast" in data or "crew" in data:
				cast = []
				for member in sorted(data.get("cast", []) + data.get("crew", []), key=lambda x: (x["billingOrder"], x["role"], x["name"])):
					role = member["role"].lower()
					if role in ["voice"]:
						role = "actor"
					elif role in ["host", "anchor"]:
						role = "presenter"
					elif role in ["guest", "contestent"]:
						role = "guest"

					if role not in ["director", "actor", "writer", "adapter", "producer", "composer", "editor", "presenter", "commentator", "guest"]:
						continue

					name = member["name"]
					if "characterName" in member:
						name += " (" + member["characterName"] + ")"
					cast.append((role, name))
				data["cast"] = cast

			start = pytz.utc.localize(datetime.strptime(program["airDateTime"], "%Y-%m-%dT%H:%M:%SZ"))
			stop = start + timedelta(seconds=program["duration"])

			data["start"] = start
			data["stop"] = stop

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
			print(" " + items_fmt(len(self.schedule)) + " in " + time_fmt(duration) + " (" + items_fmt(len(self.schedule) / duration) + "/s)")
		except:
			print()
			raise


class SD2XMLTV(object):
	def __init__(self, config="config", base=os.getcwd()):
		self.base = base
		self.config = yaml.safe_load(open(os.path.join(self.base, config), "rt", encoding="UTF-8"))
		self.config.setdefault("files", {})
		self.config["files"].setdefault("start_hour", 6)

		with session.cache_disabled():
			token = get("token", "/token", { "username": self.config["login"]["username"], "password": hashlib.sha1(self.config["login"]["password"].encode("UTF-8")).hexdigest().lower() })
			if token["code"] != 0:
				raise Exception(token)
			session.headers.update({ "token": token["token"] })
			self.status = get("status", "/status")
			if self.status["code"] != 0:
				raise Exception(self.status)

	def main(self):
		channels = {}

		lineups = get("lineups", "/lineups")["lineups"]

		for lineup in lineups:
			lineup_channels = get("lineup " + lineup["lineup"], "/lineups/" + lineup["lineup"])
			with open(os.path.join(self.base, "channels_" + safe_filename(lineup["lineup"])), "wt", encoding="UTF-8") as f:
				f.write(json.dumps(lineup_channels, indent=2, sort_keys=True))

			channels[lineup["lineup"]] = Channels(lineup["lineup"], lineup_channels)

		programmes = []
		for (lineup, lineup_channels) in self.config["channels"].items():
			for channel in lineup_channels:
				programmes.append(Programmes(channel, channels[lineup][channel["name"]]))

		files = Files(self.config, self.base)
		for item in programmes:
			item.write(files)
		files.close()

if __name__ == "__main__":
	SD2XMLTV().main()
