#!/usr/bin/env python3

from cachecontrol import CacheControl
from cachecontrol.caches import FileCache
from datetime import datetime
from datetime import timedelta
import requests


BASE_URL = "http://xmltv.radiotimes.com/xmltv"

session = CacheControl(requests.session(), cache=FileCache('.http-cache'))
session.headers.update({"User-Agent": "rt2xmltv/1 " + requests.utils.default_user_agent()})


def size_fmt(num):
	for x in ["B", "KB"]:
		if num < 1024 and num > -1024:
			return "%3.1f%s" % (num, x)
		num /= 1024
	return "%3.1f%s" % (num, "MB")


def get(name, filename):
	global session

	print("Downloading " + name + "...", flush=True, end="")

	start = datetime.utcnow()
	r = session.get(BASE_URL + filename)
	duration = (datetime.utcnow() - start).total_seconds()
	if r.status_code != requests.codes.ok:
		print()
	r.raise_for_status()

	print(" " + size_fmt(len(r.text)) + " (" + size_fmt(len(r.text) / duration) + "/s)")
	return r.text


def main():
	channels = get("channel list", "/channels.dat")


if __name__ == "__main__":
	main()
