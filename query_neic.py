#!/usr/bin/env python
'''
Queries the USGS Realtime EQ Notification feed for events over a given input range.
Publishes event products that pass the filter.
'''

from __future__ import print_function
import json
import os
import datetime
import argparse

import dateutil.parser
import pytz
import requests
from requests.auth import HTTPBasicAuth
from shapely.geometry import Polygon, Point
import redis
from hysds_commons.net_utils import get_container_host_ip

import build_event_product

POOL = None
REDIS_KEY = 'neic_last_query'

def main(minmag=None, starttime=None, endtime=None, updatedafter=None, alertlevel=None, slack_notification=False, polygon=None, test=False, submit=False):
    '''main method. runs tests, queries usgs, filters events, then builds products'''
    #run test aoi first if test is provided
    if test:
        build_event_product.build(get_test_event(), submit)
        return
    #build the query string from the input params
    query = build_query(minmag, starttime, endtime, updatedafter, alertlevel, polygon)
    print('Running USGS NEIC query: {0}'.format(query))
    response = run_query(query)   
    #print(response)
    events = filter_response(response, polygon)
    for event in events:
        build_event_product.build(event, submit)
    if redis:
       set_redis_query_time(response) #sets the redis query to the updated time returned from the usgs query

def build_query(minmag, starttime, endtime, updatedafter, alertlevel, polygon_string):
    '''builds a query url from the input filter params. returns the url'''
    query = 'https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson'
    #build polygon
    if polygon_string:
        if not validate_polygon_string(polygon_string):
            raise Exception('polygon string not valid geojson: {0}'.format(polygon_string))
        polygon = get_polygon(polygon_string)
        #get minimum and maximum longitude across geojson, this is needed since usgs can only use min/max lat,lons
        bounds = polygon.bounds
        query += "&minlongitude={0}&minlatitude={1}&maxlongitude={2}&maxlatitude={3}".format(bounds[0],bounds[1],bounds[2],bounds[3])
    #build start/endtime
    if starttime:
        query += '&starttime={0}'.format(validate_user_time(starttime))
    if endtime:
        query += '&endtime={0}'.format(validate_user_time(endtime))
    #if we are using redis as a key for updated after
    if updatedafter == 'redis':
        query += '&updatedafter={0}'.format(get_redis_time())
    elif updatedafter != None:
        query += '&updatedafter={0}'.format(validate_user_time(updatedafter))
    if minmag:
        query += '&minmagnitude={0}'.format(validate_decimal(minmag))
    if alertlevel:
        query += '&alertlevel={0}'.format(alertlevel)
    return query

def run_query(query):
    '''runs the input query over the given url, returning a dict object from the result text'''
    try:
        session = requests.session()
        response = session.get(query, timeout=30)
    except Exception as e:
        raise Exception('USGS Query failed: {0}\nquery: {1}'.format(e, query)) 
    #print(response)
    if response.status_code != 200:
        raise Exception("{0} status for query: {1}".format(response.status_code, query))
    return json.loads(response.text)

def filter_response(response, polygon_string):
    '''validate response and filter through polygon client-side'''
    events = []
    #parse the json for names and urls
    print('query returned %s results' % len(response['features']))
    for event in response['features']:
        lat = float(event['geometry']['coordinates'][1])
        lon = float(event['geometry']['coordinates'][0]) 
        if polygon_string: #if we're using a geojson filter
            if not validate_coverage(lat, lon, polygon_string):
                continue
        events.append(event)
    print('filtered results returned {0} total'.format(len(events)))
    return events

def validate_polygon_string(polygon_string):
    '''validates the input json polygon string is a valid geojson'''
    if polygon_string == None:
        return False
    try:
        json_polygon = json.loads(polygon_string)
        polygon = Polygon(json_polygon)
    except:
        return False
    return True    

def get_polygon(polygon_string):
    '''returns a polygon geojson object'''
    json_polygon = json.loads(polygon_string)
    return Polygon(json_polygon)

def validate_coverage(lat, lon, polygon_string):
    '''determines if the lat,lon is covered by the polygon. returns true if it is covered, false otherwise'''
    json_polygon = json.loads(polygon_string)
    polygon = Polygon(json_polygon)
    point = Point(float(lon), float(lat))
    if is_covered(point, polygon):
        return True
    return False

def is_covered(point, polygon):
    if polygon.intersects(point):
        return True
    return False

def validate_user_time(input_time):
    '''parses the time and returns in UTC format'''
    try:
        user_time = dateutil.parser.parse(input_time).replace(tzinfo=pytz.UTC)
    except:
        raise Exception('Unable to parse input time: {0}'.format(input_time))
    return user_time.strftime('%Y-%m-%dT%H:%M:%S')

def validate_decimal(input_decimal):
    '''returns a string to 0.1 sig fig'''
    try:
        return "{:.1f}".format(float(input_decimal))
    except:
        print('Input value invalid: {0}'.format(input_decimal))

def get_redis_time():
    '''get the last successful runtime from redis'''
    return redis_get(REDIS_KEY)

def redis_get(key):
    '''returns the value of the given redis key'''
    global POOL
    redis_url = 'redis://%s' % get_container_host_ip()
    POOL = redis.ConnectionPool.from_url(redis_url)
    rds = redis.StrictRedis(connection_pool=POOL)
    value = rds.get(key)
    return value

def redis_set(key, value):
    '''set redis key to the given value'''
    global POOL
    redis_url = 'redis://%s' % get_container_host_ip()
    POOL = redis.ConnectionPool.from_url(redis_url)
    rds = redis.StrictRedis(connection_pool=POOL)
    rds.set(key, value)
    return value

def get_test_event():
    '''loads test_event.json file and returns the dict'''
    test_json = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'test_event.json')
    return json.load(open(test_json))

def set_redis_query_time(usgs_response):
    usgs_time = usgs_response['metadata']['generated']
    '''sets the redis query time to the provided usgs time'''
    query_time = convert_epoch_time_to_utc(float(usgs_time)/1000)
    print('setting redis last query time to: {0}'.format(query_time))
    redis_set(REDIS_KEY, query_time)

def convert_epoch_time_to_utc(epoch_time):
    '''convert an epoch time to proper utc time'''
    dt = datetime.datetime.utcfromtimestamp(float(epoch_time)).replace(tzinfo=pytz.UTC)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] # use microseconds and convert to milli

def parser():
    '''
    Construct a parser to parse arguments
    @return argparse parser
    '''
    parse = argparse.ArgumentParser(description="Run PAGER query with given parameters")
    parse.add_argument("-m", "--minmag", required=False, default=None, help="Minimum magnitude for query", dest="minmag")
    parse.add_argument("-t", "--starttime", required=False, default=None, help="Start time for query range.", dest="starttime")
    parse.add_argument("-e", "--endtime", required=False, default=None, help="End time for query range.", dest="endtime")
    parse.add_argument("-u", "--updatedafter", required=False, default=None, help="Filter for files updated after. Use 'redis': will use redis to query for products updated since last successful query time.", dest="updatedafter")
    parse.add_argument("-a", "--alertlevel", required=False, default=None, choices=['green', 'yellow', 'orange', 'red'], help="Minimum alert level threshold for query", dest="alertlevel")
    parse.add_argument("-s", "--slack_notification", required=False, default=False, help="Key for slack notification, will notify via slack if provided.", dest="slack_notification")
    parse.add_argument("-p", "--polygon", required=False, default=None, help="Geojson polygon filter", dest="polygon")
    parse.add_argument("--test", required=False, default=False, action="store_true", help="Run a test submission. Overrides all other params", dest="test") 
    parse.add_argument("--submit", required=False, default=False, action="store_true", help="Submits the event directly. Must have datasets in working directory.", dest="submit")
    return parse

if __name__ == '__main__':
    args = parser().parse_args()
    main(minmag=args.minmag, starttime=args.starttime, endtime=args.endtime, updatedafter=args.updatedafter, alertlevel=args.alertlevel, slack_notification=args.slack_notification, polygon=args.polygon, test=args.test, submit=args.submit)

