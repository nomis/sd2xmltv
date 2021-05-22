#!/usr/bin/env python3

#  sdlineups - Schedules Direct Lineup Management
#
#  Copyright 2017,2021 Simon Arlott
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

from pprint import pprint
import argparse
import requests_cache

import sd2xmltv

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument('--add', type=str)
	parser.add_argument('--remove', type=str)
	parser.add_argument('--country', type=str)
	parser.add_argument('--postalcode', type=str)
	args = parser.parse_args()

	sd = sd2xmltv.SD2XMLTV()

	with sd2xmltv.no_cache():
		pprint(sd2xmltv.get("lineups", "/lineups"))

		if args.country and args.postalcode:
			pprint(sd2xmltv.get("lineup search", "/headends", query={ "country": args.country, "postalcode": args.postalcode }))

		if args.add:
			ret = sd2xmltv.put("Add lineup " + args.add, "/lineups/" + args.add)
			pprint(ret)

		if args.remove:
			ret = sd2xmltv.delete("Remove lineup " + args.remove, "/lineups/" + args.remove)
			pprint(ret)
