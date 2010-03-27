#!/usr/bin/python
#----------------------------------------------------------------------------
# Module for communication with various online services.
#----------------------------------------------------------------------------
# Copyright 2010, Martin Kolman
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#---------------------------------------------------------------------------
from base_module import ranaModule
import urllib
import googlemaps

def getModule(m,d):
  return(onlineServices(m,d))

class onlineServices(ranaModule):
  """Module for communication with various online services."""
  
  def __init__(self, m, d):
    ranaModule.__init__(self, m, d)
    
#  def update(self):
#    self.elevFromGeonames(50, 50)
#    # Get and set functions are used to access global data
#    self.set('num_updates', self.get('num_updates', 0) + 1)
#    #print "Updated %d times" % (self.get('num_updates'))

  def elevFromGeonames(self, lat, lon):
    """get elevation in meters for the specified latitude and longitude from geonames"""
    url = 'http://ws.geonames.org/srtm3?lat=%f&lng=%f' % (lat,lon)
    try:
      query = urllib.urlopen(url)
    except:
      "onlineServices: getting elevation from geonames retuned an error"
      return 0
    return query.read()

  def getGmapsInstance(self):
    """get a google maps wrapper instance"""
    key = self.get('googleAPIKey', None)
    if key == None:
      print "onlineServices: a google API key is needed for using the google maps services"
      return None
    gmap = googlemaps.GoogleMaps(key)
    return gmap

  def googleLocalQuery(self, query):
    gmap = self.getGmapsInstance()
    numresults = int(self.get('GLSResults', 8))
    local = gmap.local_search(query, numresults)
    return local

  def googleLocalQueryLL(self, query, lat, lon):
    separator = " "
    LL = "%f,%f" % (lat,lon)
    queryWithLL = query + separator + LL
    local = self.googleLocalQuery(queryWithLL)
    return local


if(__name__ == "__main__"):
  a = example({}, {})
  a.update()
  a.update()
  a.update()
